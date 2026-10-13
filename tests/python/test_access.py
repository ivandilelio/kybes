"""Fase 2: paginazione a cursore, query dichiarate, Unit of Work (SQLAlchemy su SQLite)."""
import sys, datetime as dt
from decimal import Decimal
sys.path.insert(0, sys.argv[1] + "/libs/db-models/python/src")
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from model.generated import Base, ModelValidationError, PageRequest, run_in_transaction, isolation_for, transaction
from model.Clienti import Clienti, ClientiRepository
from model.Ordini import Ordini, OrdiniRepository
from model.Prodotti import Prodotti, ProdottiRepository
from model.RigheOrdine import RigheOrdine, RigheOrdineRepository

eng = create_engine("sqlite://")
@event.listens_for(eng, "connect")
def fk_on(c, _): c.execute("PRAGMA foreign_keys=ON")
Base.metadata.create_all(eng)
SF = sessionmaker(eng)
SQLITE_LEVELS = {"read_committed": None, "repeatable_read": None, "serializable": "SERIALIZABLE"}

def expect_invalid(fn, field):
    try:
        fn()
    except ModelValidationError as e:
        assert field in e.fields, e.fields
        return e
    raise SystemExit(f"atteso errore su {field}")

with Session(eng) as s:
    cr, orr, pr = ClientiRepository(s), OrdiniRepository(s), ProdottiRepository(s)
    a = cr.create(Clienti(ragione_sociale="Alfa"))
    b = cr.create(Clienti(ragione_sociale="Beta", attivo=False))
    cr.create(Clienti(ragione_sociale="Gamma"))
    # 25 ordini su 5 date (pareggi sulla colonna di ordinamento)
    for i in range(25):
        orr.create(Ordini(numero=f"2026/{i:03d}", cliente_id=a.id if i % 2 == 0 else b.id,
                          data=dt.date(2026, 1, 1 + i % 5), totale=Decimal(i), stato="aperto" if i % 3 else "chiuso"))
    s.commit()

    # ---- pagina completa senza duplicati né buchi, ordine data desc + id
    seen, cur, pages = [], None, 0
    while True:
        pg = orr.list_page(PageRequest(limit=7, cursor=cur))
        seen += pg.items; pages += 1
        if not pg.has_more: break
        cur = pg.next_cursor
    assert pages == 4 and len(seen) == 25 and len({o.id for o in seen}) == 25, (pages, len(seen))
    keys = [(o.data, o.id) for o in seen]
    assert keys == sorted(keys, key=lambda k: (-k[0].toordinal(), k[1])), "ordine data desc, id asc"
    # ---- ordinamento richiesto dalla UI (nomi JSON) e ordine inverso
    tot = [o.totale for o in orr.list_page(PageRequest(limit=200, sort="-totale")).items]
    assert tot == sorted(tot, reverse=True)
    nums = []
    cur = None
    while True:
        pg = orr.list_page(PageRequest(limit=10, sort="numero", cursor=cur)); nums += [o.numero for o in pg.items]
        if not pg.has_more: break
        cur = pg.next_cursor
    assert nums == sorted(nums) and len(nums) == 25
    # ---- errori del contratto
    expect_invalid(lambda: orr.list_page(PageRequest(sort="note")), "sort")
    expect_invalid(lambda: orr.list_page(PageRequest(limit=0)), "limit")
    expect_invalid(lambda: orr.list_page(PageRequest(limit=201)), "limit")
    expect_invalid(lambda: orr.list_page(PageRequest(cursor="xxx")), "cursor")
    c1 = orr.list_page(PageRequest(limit=5)).next_cursor
    expect_invalid(lambda: orr.list_page(PageRequest(limit=5, sort="numero", cursor=c1)), "cursor")  # cursore di un altro ordinamento
    assert orr.list_page().limit == 50  # default_limit
    # ---- query dichiarate
    pg = orr.list_del_cliente_dal(a.id, dt.date(2026, 1, 4), PageRequest(limit=100))
    assert pg.items and all(o.cliente_id == a.id and o.data >= dt.date(2026, 1, 4) for o in pg.items)
    assert [o.data for o in pg.items] == sorted([o.data for o in pg.items], reverse=True)
    expect_invalid(lambda: orr.list_del_cliente_dal(a.id, dt.date(2026, 1, 1), PageRequest(sort="numero")), "sort")
    aperti = orr.list_aperti_del_cliente(a.id, PageRequest(limit=100)).items
    assert aperti and all(o.stato == "aperto" and o.cliente_id == a.id for o in aperti)
    ultimo = orr.find_ultimo_del_cliente(a.id)
    assert ultimo.data == max(o.data for o in seen if o.cliente_id == a.id)
    assert orr.find_ultimo_del_cliente(cr.find_by_partita_iva("nessuno").id if cr.find_by_partita_iva("nessuno") else a.id) is not None
    orr.create(Ordini(numero="X%_1", cliente_id=a.id, data=dt.date(2026, 2, 1)))
    orr.create(Ordini(numero="XA_1", cliente_id=a.id, data=dt.date(2026, 2, 1)))
    assert [o.numero for o in orr.list_per_numero("X%", PageRequest(limit=10)).items] == ["X%_1"], "prefix protegge % e _"
    assert [o.numero for o in orr.list_per_numero("2026/00", PageRequest(limit=100)).items] == [f"2026/00{i}" for i in range(10)]
    assert [c.ragione_sociale for c in cr.list_attivi().items] == ["Alfa", "Gamma"]
    p1 = pr.create(Prodotti(codice="A", descrizione="a")); pr.create(Prodotti(codice="B", descrizione="b"))
    assert {p.codice for p in pr.list_senza_categoria()} == {"A", "B"}
    assert [p.codice for p in pr.list_per_codici(["B", "Z"])] == ["B"]
    # list_rel e list_by paginati con l'ordine della tabella figlia
    pg = cr.list_ordini(a.id, PageRequest(limit=3))
    assert len(pg.items) == 3 and pg.has_more and all(o.cliente_id == a.id for o in pg.items)
    s.commit()

# ---- Unit of Work
assert isolation_for(["Clienti"]) == "read_committed"
assert isolation_for(["Ordini", "RigheOrdine"]) == "serializable"
assert isolation_for(["Clienti", "Ordini"]) == "repeatable_read"

def crea(session):
    return ClientiRepository(session).create(Clienti(ragione_sociale="Delta")).id
new_id = run_in_transaction(SF, crea, tables=["Clienti"], levels=SQLITE_LEVELS)
with Session(eng) as s:
    assert ClientiRepository(s).get_by_id(new_id) is not None, "commit"

def fallisce(session):
    ClientiRepository(session).create(Clienti(ragione_sociale="Epsilon"))
    raise RuntimeError("errore applicativo")
try:
    run_in_transaction(SF, fallisce, tables=["Clienti"], levels=SQLITE_LEVELS)
    raise SystemExit("eccezione attesa")
except RuntimeError:
    pass
with Session(eng) as s:
    assert ClientiRepository(s).find_by_partita_iva("x") is None
    assert not [c for c in ClientiRepository(s).list_page(PageRequest(limit=100)).items if c.ragione_sociale == "Epsilon"], "rollback"

class Serialization(Exception):
    sqlstate = "40001"
calls = {"n": 0}
def conflitto(session):
    calls["n"] += 1
    ClientiRepository(session).create(Clienti(ragione_sociale=f"Zeta{calls['n']}"))
    if calls["n"] < 3:
        raise OperationalError("UPDATE", {}, Serialization())
    return calls["n"]
assert run_in_transaction(SF, conflitto, tables=["RigheOrdine"], levels=SQLITE_LEVELS, backoff_s=0) == 3
with Session(eng) as s:
    names = {c.ragione_sociale for c in ClientiRepository(s).list_page(PageRequest(limit=100)).items}
    assert "Zeta3" in names and "Zeta1" not in names and "Zeta2" not in names, "solo il tentativo riuscito resta"
calls["n"] = -10
try:
    run_in_transaction(SF, conflitto, levels=SQLITE_LEVELS, max_retries=2, backoff_s=0)
    raise SystemExit("atteso errore dopo i tentativi")
except OperationalError:
    pass
with transaction(SF, ["Clienti"], levels=SQLITE_LEVELS) as s:
    ClientiRepository(s).create(Clienti(ragione_sociale="Eta"))
print("PYTHON ACCESS OK: paginazione keyset, ordinamenti, errori del contratto, query, Unit of Work")
