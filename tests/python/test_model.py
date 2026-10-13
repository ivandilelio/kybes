import sys, datetime as dt
from decimal import Decimal
sys.path.insert(0, sys.argv[1] + "/libs/db-models/python/src")
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from model.generated import bind_tenant
TENANT = '00000000-0000-4000-8000-0000000000aa'
from model.generated import Base, ModelValidationError
from model.Clienti import Clienti, ClientiRepository
from model.Ordini import Ordini, OrdiniRepository
from model.RigheOrdine import RigheOrdine, RigheOrdineRepository
from model.Prodotti import Prodotti, ProdottiRepository
from model.Categorie import Categorie, CategorieRepository

eng = create_engine("sqlite://")
@event.listens_for(eng, "connect")
def fk_on(c, _): c.execute("PRAGMA foreign_keys=ON")
Base.metadata.create_all(eng)
with Session(eng) as s:
    bind_tenant(s, TENANT)
    cr, orr, rr, pr, kr = ClientiRepository(s), OrdiniRepository(s), RigheOrdineRepository(s), ProdottiRepository(s), CategorieRepository(s)
    c = cr.create(Clienti(ragione_sociale="ACME Srl", partita_iva="01234567890"))
    assert c.id is not None and c.attivo is True and c.creato_il is not None, "default/generati"
    assert cr.find_by_partita_iva("01234567890").id == c.id
    from sqlalchemy.exc import IntegrityError
    try:
        with s.begin_nested():
            cr.create(Clienti(ragione_sociale="Doppio", partita_iva="01234567890"))
        raise SystemExit("vincolo univoco non applicato")
    except IntegrityError:
        pass
    try:
        cr.create(Clienti(ragione_sociale="x" * 201)); raise SystemExit("validazione lunghezza mancata")
    except ModelValidationError as e:
        assert e.fields == {"RagioneSociale": "lunghezza massima 200"}, e.fields
    try:
        cr.update(c.id, {"id": None}); raise SystemExit("update di campo non modificabile")
    except ModelValidationError: pass
    root = kr.create(Categorie(nome="Root")); sub = kr.create(Categorie(nome="Sub", padre_id=root.id))
    assert [x.nome for x in kr.list_figlie(root.id).items] == ["Sub"] and kr.get_padre(sub.id).nome == "Root"
    p = pr.create(Prodotti(codice="P1", descrizione="Bullone", categoria_id=sub.id, attributi={"colore": "rosso"}))
    o = orr.create(Ordini(numero="2026/1", cliente_id=c.id, data=dt.date(2026, 10, 13)))
    assert o.totale == 0
    r = rr.create(RigheOrdine(ordine_id=o.id, prodotto_id=p.id, quantita=3, prezzo_unitario=Decimal("1.5000")))
    assert orr.get_cliente(o.id).ragione_sociale == "ACME Srl"
    assert [x.numero for x in cr.list_ordini(c.id).items] == ["2026/1"]
    assert [x.id for x in orr.list_by_cliente_id(c.id).items] == [o.id]
    assert [x.quantita for x in orr.list_righe(o.id).items] == [3]
    assert rr.get_prodotto(r.id).codice == "P1" and pr.get_categoria(p.id).nome == "Sub"
    assert cr.count() == 1 and cr.exists(c.id) and len(cr.list_page().items) == 1
    upd = cr.update(c.id, {"email": "info@acme.it"}); assert upd.email == "info@acme.it"
    s.commit()
    assert orr.delete(o.id) is True; s.commit()
    assert rr.count() == 0, "cascade su righe"
    assert cr.delete(c.id) is True and cr.delete(c.id) is False
    s.commit()
print("PYTHON OK: CRUD, relazioni, auto-relazione, cascade, validazione, default")
