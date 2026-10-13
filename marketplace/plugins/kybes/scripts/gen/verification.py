"""Catalogo dei requisiti e dei casi di test di unità, derivato dagli schemi (ISO 26262-6, verifica di unità).

Il catalogo è indipendente dal linguaggio: ogni emettitore di test lo rende in pytest, node:test, JUnit o xUnit.
ID stabili: dipendono dai nomi nello schema, non dall'ordine, quindi la tracciabilità non cambia
quando si aggiungono colonne o tabelle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import re
from pathlib import Path

from schema import ASIL, Cond, Query, Table, lifecycle_children

METHODS = {
    "req": "analisi dei requisiti",
    "eq": "classi di equivalenza",
    "bv": "valori limite",
    "eg": "error guessing",
    "mcdc": "MC/DC sulle condizioni della query",
}


@dataclass
class Requirement:
    id: str
    table: str
    text: str
    source: str            # elemento dello schema che lo origina
    asil: str


@dataclass
class TestCase:
    id: str
    table: str
    reqs: List[str]
    method: str            # chiave di METHODS
    kind: str
    title: str
    expected: str
    args: Dict = field(default_factory=dict)
    scope: str = "model"   # model: test del modello nei linguaggi; jobs: test del motore dei job (pytest)

    @property
    def slug(self) -> str:
        return self.id[3:].replace("-", "_").lower()


@dataclass
class Catalog:
    requirements: List[Requirement]
    tests: List[TestCase]
    tenant_id_type: str = "uuid"

    def for_table(self, name: str, scope: str = "model") -> List[TestCase]:
        return [t for t in self.tests if t.table == name and (scope == "all" or t.scope == scope)]


def table_asil(t: Table, default: str) -> str:
    return t.asil or default


def _req(reqs: List[Requirement], t: Table, key: str, text: str, source: str, asil: str) -> str:
    rid = f"REQ-{t.name}-{key}"
    reqs.append(Requirement(rid, t.name, text, source, asil))
    return rid


def _fk_required_targets(t: Table) -> Dict[str, str]:
    return {r.foreign_key: r.target for r in t.relations if r.kind == "many_to_one" and t.col(r.foreign_key).required}


def builder_cycles(tables: Dict[str, Table]) -> List[str]:
    """Cicli di FK obbligatorie: impossibili da soddisfare per i builder dei test."""
    out = []

    def visit(n, path):
        for tg in _fk_required_targets(tables[n]).values():
            if tg in path:
                out.append(" → ".join(path[path.index(tg):] + [tg]))
            elif tg in tables:
                visit(tg, path + [tg])
    for n in tables:
        visit(n, [n])
    return sorted(set(out))


def _query_conds(q: Query) -> List[Cond]:
    return list(q.where)


def build_catalog(tables: Dict[str, Table], default_asil: str = "B", tenant_id_type: str = "uuid") -> Catalog:
    reqs: List[Requirement] = []
    tests: List[TestCase] = []
    for n, t in tables.items():
        asil = table_asil(t, default_asil)
        src = f"schemas/db/{n}.yaml"
        add = tests.append
        r_create = _req(reqs, t, "CREATE", f"Un record valido di {n} viene inserito e riletto con gli stessi valori.", f"{src}: columns", asil)
        r_read = _req(reqs, t, "READ", f"Lettura per chiave, esistenza e conteggio di {n} restituiscono lo stato reale.", f"{src}: primary_key", asil)
        r_update = _req(reqs, t, "UPDATE", f"L'aggiornamento di {n} modifica solo i campi ammessi e rifiuta la chiave e i campi generati.", f"{src}: columns", asil)
        r_delete = _req(reqs, t, "DELETE", f"La cancellazione di {n} rimuove il record e segnala quando non esiste.", f"{src}: primary_key", asil)
        r_page = _req(reqs, t, "PAGE", f"La paginazione di {n} restituisce ogni record una sola volta e rifiuta limite, ordinamento e cursore non validi.", f"{src}: pagination", asil)
        add(TestCase(f"TC-{n}-CREATE-VALID", n, [r_create], "eq", "create_valid",
                     "inserimento di un record valido (classe di equivalenza valida)", "il record è persistito e rileggibile per chiave"))
        add(TestCase(f"TC-{n}-READ-EXISTING", n, [r_read], "req", "read_existing",
                     "lettura per chiave, esistenza e conteggio di un record esistente", "il record è restituito, exists è vero, count ≥ 1"))
        add(TestCase(f"TC-{n}-READ-MISSING", n, [r_read], "eg", "read_missing",
                     "lettura per chiave di un record inesistente", "nessun record, exists è falso"))
        cands = [c for c in t.columns if not c.primary_key and not c.generated and not c.tenant and c.name not in t.fk_columns()
                 and c.type in ("string", "text", "int", "bigint", "decimal")]
        # di preferenza una colonna non univoca; altrimenti quella univoca (il valore nuovo è comunque diverso)
        upd = next((c for c in cands if not c.unique), None) or next((c for c in cands if c.type == "string"), None)
        if upd:
            add(TestCase(f"TC-{n}-UPDATE-ALLOWED", n, [r_update], "req", "update_allowed",
                         f"aggiornamento del campo {upd.name}", "il nuovo valore è persistito", {"column": upd.name}))
        add(TestCase(f"TC-{n}-UPDATE-MISSING", n, [r_update], "eg", "update_missing",
                     "aggiornamento di un record inesistente",
                     "nessun record aggiornato né creato; il chiamante lo sa (Python e TypeScript: nessun risultato; Java e C#: errore record inesistente)"))
        add(TestCase(f"TC-{n}-UPDATE-KEY", n, [r_update], "eq", "update_key",
                     "tentativo di cambiare la chiave primaria (classe non valida)",
                     "rifiutato, la chiave resta quella originale (Python e TypeScript: errore di validazione; Java: la chiave non ha setter "
                     "e un aggiornamento senza chiave è rifiutato; C#: l'aggiornamento non trova il record)"))
        gens = [c for c in t.columns if c.generated]
        if gens:
            desc = "; ".join(f"{c.name} ({c.generated})" for c in gens)
            rid = _req(reqs, t, "GENERATED", f"Le date generate di {n} ({desc}) sono impostate dal modello alla creazione; "
                       "quelle on_update anche a ogni aggiornamento, quelle on_create non cambiano più.",
                       f"{src}: columns.*.generated", asil)
            add(TestCase(f"TC-{n}-GENERATED", n, [rid], "req", "generated_values",
                         "inserimento e poi aggiornamento di un record" if upd else "inserimento di un record",
                         "valori impostati all'inserimento; dopo l'aggiornamento on_create invariato, on_update non precedente",
                         {"columns": [(c.name, c.generated) for c in gens], "update": upd.name if upd else None}))
        add(TestCase(f"TC-{n}-DELETE", n, [r_delete], "req", "delete",
                     "cancellazione di un record esistente e poi inesistente", "prima vero, poi falso; il record non è più leggibile"))
        for c in t.columns:
            if c.primary_key or c.generated or c.tenant:
                continue
            if c.required:
                text = f"{n}.{c.name} è obbligatorio" + (f" (se assente vale {c.default!r}; un valore nullo esplicito è rifiutato)." if c.default is not None else ".")
                rid = _req(reqs, t, f"{c.name}-REQUIRED", text, f"{src}: columns.{c.name}.required", asil)
                add(TestCase(f"TC-{n}-{c.name}-NULL", n, [rid], "eq", "required_null",
                             f"inserimento con {c.name} assente (classe non valida)", f"errore di validazione su {c.name}: obbligatorio",
                             {"column": c.name}))
            else:
                rid = _req(reqs, t, f"{c.name}-OPTIONAL", f"{n}.{c.name} è facoltativo.", f"{src}: columns.{c.name}.required", asil)
                add(TestCase(f"TC-{n}-{c.name}-OPTIONAL", n, [rid], "eq", "optional_null",
                             f"inserimento con {c.name} assente (classe valida)", f"inserimento riuscito, {c.name} resta vuoto",
                             {"column": c.name}))
            if c.type == "string":
                rid = _req(reqs, t, f"{c.name}-MAXLEN", f"{n}.{c.name} accetta al massimo {c.length} caratteri.",
                           f"{src}: columns.{c.name}.length", asil)
                add(TestCase(f"TC-{n}-{c.name}-MAXLEN-AT", n, [rid], "bv", "maxlen_at",
                             f"{c.name} lungo esattamente {c.length} caratteri (limite)", "inserimento riuscito",
                             {"column": c.name, "length": c.length}))
                add(TestCase(f"TC-{n}-{c.name}-MAXLEN-OVER", n, [rid], "bv", "maxlen_over",
                             f"{c.name} lungo {c.length + 1} caratteri (limite + 1)", f"errore di validazione su {c.name}",
                             {"column": c.name, "length": c.length}))
            if c.unique:
                rid = _req(reqs, t, f"{c.name}-UNIQUE", f"{n}.{c.name} è univoco e si cerca per valore.", f"{src}: columns.{c.name}.unique", asil)
                add(TestCase(f"TC-{n}-{c.name}-FINDBY", n, [rid], "req", "find_by",
                             f"ricerca per {c.name} di un valore esistente e di uno inesistente",
                             "restituisce il record, poi nessun record", {"column": c.name}))
                add(TestCase(f"TC-{n}-{c.name}-DUPLICATE", n, [rid], "eg", "unique_duplicate",
                             f"secondo record con lo stesso {c.name}", "il database rifiuta l'inserimento", {"column": c.name}))
            if c.default is not None:
                rid = _req(reqs, t, f"{c.name}-DEFAULT", f"{n}.{c.name} vale {c.default!r} se non indicato.",
                           f"{src}: columns.{c.name}.default", asil)
                add(TestCase(f"TC-{n}-{c.name}-DEFAULT", n, [rid], "req", "default_value",
                             f"inserimento senza {c.name}", f"{c.name} vale il default", {"column": c.name, "value": c.default}))
        for r in t.relations:
            if r.kind == "many_to_one":
                rid = _req(reqs, t, f"{r.name}-REL", f"Da {n} si raggiunge {r.target} tramite {r.foreign_key}, e viceversa.",
                           f"{src}: relations.{r.name}", asil)
                add(TestCase(f"TC-{n}-{r.name}-PARENT", n, [rid], "req", "rel_parent",
                             f"lettura del {r.target} collegato, poi da una chiave inesistente",
                             f"restituisce il {r.target} con chiave uguale a {r.foreign_key}; nessun record per la chiave inesistente",
                             {"relation": r.name}))
                if t.mongo:
                    add(TestCase(f"TC-{n}-{r.name}-PARENT-MISSING", n, [rid], "eg", "mongo_parent_missing",
                                 f"inserimento con {r.foreign_key} di un {r.target} inesistente",
                                 f"errore di validazione su {r.foreign_key}: non trovato (MongoDB non ha chiavi esterne: le controlla il modello)",
                                 {"relation": r.name}))
                else:
                    add(TestCase(f"TC-{n}-{r.name}-PARENT-OBJECT", n, [rid], "eq", "rel_parent_object",
                                 f"inserimento collegando il {r.target} come oggetto invece che con la chiave",
                                 f"{r.foreign_key} è impostata dal modello e resta coerente con l'oggetto collegato", {"relation": r.name}))
                add(TestCase(f"TC-{n}-{r.foreign_key}-LISTBY", n, [rid], "req", "list_by",
                             f"pagina dei {n} con {r.foreign_key} dato", "contiene il record e solo record con quel valore",
                             {"relation": r.name}))
            else:
                rid = _req(reqs, t, f"{r.name}-CHILDREN", f"Da {n} si leggono i {r.target} collegati.", f"{src}: relations.{r.name}", asil)
                add(TestCase(f"TC-{n}-{r.name}-CHILDREN", n, [rid], "req", "rel_children",
                             f"pagina dei {r.target} collegati", "contiene il figlio e solo figli di quel record", {"relation": r.name}))
        if t.tenancy != "none":
            _tenancy_cases(t, tables, reqs, add, src, asil)
        if t.mongo:
            _mongo_cases(t, tables, reqs, add, src, asil)
        elif t.archive or t.retention:
            _lifecycle_cases(t, tables, reqs, add, src, asil)
        add(TestCase(f"TC-{n}-PAGE-WALK", n, [r_page], "req", "page_walk",
                     "scorrimento completo con limite 1", "ogni record una sola volta, ultimo cursore nullo"))
        if t.pagination.sortable:
            add(TestCase(f"TC-{n}-PAGE-SORT-EACH", n, [r_page], "eq", "page_sort_each",
                         "scorrimento completo per ogni colonna ordinabile, crescente e decrescente: "
                         + ", ".join(t.pagination.sortable),
                         "per ogni ordinamento ogni record una sola volta, nell'ordine richiesto",
                         {"sorts": [s for c in t.pagination.sortable for s in (c, "-" + c)]}))
        if len(t.pagination.sortable) >= 2:
            s1, s2 = t.pagination.sortable[:2]
            add(TestCase(f"TC-{n}-PAGE-WALK-SORT", n, [r_page], "req", "page_walk",
                         f"scorrimento completo con limite 1, ordinato per {s1} crescente e {s2} decrescente",
                         "ogni record una sola volta anche con pareggi su più colonne, ultimo cursore nullo",
                         {"sort": [s1, "-" + s2]}))
        add(TestCase(f"TC-{n}-PAGE-DEFAULT", n, [r_page], "bv", "page_default", "elenchi paginati richiesti senza pagina",
                     "si usa il limite predefinito della tabella elencata"))
        add(TestCase(f"TC-{n}-PAGE-LIMIT-LOW", n, [r_page], "bv", "page_limit", "limite 0 (sotto il minimo)",
                     "errore di validazione su limit", {"limit": 0}))
        add(TestCase(f"TC-{n}-PAGE-LIMIT-HIGH", n, [r_page], "bv", "page_limit", f"limite {t.pagination.max_limit + 1} (sopra il massimo)",
                     "errore di validazione su limit", {"limit": t.pagination.max_limit + 1}))
        add(TestCase(f"TC-{n}-PAGE-LIMIT-MAX", n, [r_page], "bv", "page_limit_ok", f"limite {t.pagination.max_limit} (massimo ammesso)",
                     "pagina restituita", {"limit": t.pagination.max_limit}))
        add(TestCase(f"TC-{n}-PAGE-SORT-INVALID", n, [r_page], "eq", "page_sort_invalid", "ordinamento su colonna non ammessa",
                     "errore di validazione su sort"))
        add(TestCase(f"TC-{n}-PAGE-CURSOR-INVALID", n, [r_page], "eg", "page_cursor_invalid", "cursore manomesso",
                     "errore di validazione su cursor"))
        for q in t.queries:
            rid = _req(reqs, t, f"Q-{q.name}", f"La query {q.name} restituisce esattamente i record che soddisfano tutte le sue condizioni.",
                       f"{src}: queries.{q.name}", asil)
            add(TestCase(f"TC-{n}-Q-{q.name}-MATCH", n, [rid], "req", "query_match",
                         f"query {q.name} con un record che soddisfa tutte le condizioni",
                         "il record è nel risultato e ogni record restituito soddisfa le condizioni", {"query": q.name}))
            for i, c in enumerate(q.where):
                if c.op == "in" and not c.has_value:
                    add(TestCase(f"TC-{n}-Q-{q.name}-{c.column}-IN-EMPTY", n, [rid], "bv", "query_empty_in",
                                 f"query {q.name} con elenco vuoto per {c.column}", "nessun record, nessun errore",
                                 {"query": q.name, "empty": i}))
            if ASIL.index(asil) >= ASIL.index("C"):
                for i, c in enumerate(_query_conds(q)):
                    add(TestCase(f"TC-{n}-Q-{q.name}-MCDC-{i + 1}", n, [rid], "mcdc", "query_mcdc",
                                 f"query {q.name}: solo la condizione {i + 1} ({c.column} {c.op}) è falsa",
                                 "il record non è nel risultato: la condizione determina da sola l'esito",
                                 {"query": q.name, "flip": i}))
    top = max((table_asil(t, default_asil) for t in tables.values()), key=ASIL.index, default=default_asil)
    _runtime(reqs, tests, top, any(not t.mongo for t in tables.values()))
    if any(t.mongo for t in tables.values()):
        _mongo_runtime(reqs, tests, top)
    if any((t.archive or t.retention) and not t.mongo for t in tables.values()):
        _jobs_runtime(reqs, tests, top)
    return Catalog(reqs, tests, tenant_id_type)


RUNTIME = "_runtime"


def ttl_column(t: Table) -> Optional[str]:
    """Colonna dell'indice TTL di una collection MongoDB: i dati di prova devono stare nel futuro, o MongoDB li cancella."""
    return t.retention.on if t.mongo and t.retention else None


def nulled_columns(q: Query, flip: Optional[int]) -> set:
    """Colonne che il record di prova di una query lascia vuote (is_null vera o not_null resa falsa)."""
    return {c.column for i, c in enumerate(q.where) if c.op in ("is_null", "not_null") and ((c.op == "is_null") != (i == flip))}


def put_over(over: Dict, column: str, expr: str, prio: int) -> None:
    """Valore di una colonna nel record di prova di una query: con più condizioni sulla stessa colonna vince la
    condizione resa falsa (MC/DC), poi quella esplicita, poi il valore di esempio di una colonna facoltativa."""
    if column not in over or prio > over[column][0]:
        over[column] = (prio, expr)


def over_values(over: Dict) -> List[str]:
    return [e for _, e in over.values()]


JOBS = "_jobs"
ENGINE_TESTS = Path(__file__).resolve().parent / "engine" / "tests" / "test_engine.py"
JOB_REQS = {
    "CONFIG": "La configurazione del job (config.json e variabili d'ambiente) è validata prima di toccare i dati; le età si calcolano "
              "con giorni esatti e mesi e anni di calendario.",
    "FORMAT": "I file Parquet hanno i tipi delle colonne della tabella; gli oggetti per chiave usano il formato documentato, uguale in tutti i linguaggi.",
    "STORAGE": "L'archivio su file, S3 e Azure Blob scrive, legge, elenca e cancella gli stessi percorsi; {tenant} separa le Organization.",
    "ARCHIVE": "Le righe più vecchie del limite passano nell'archivio a lotti, partizionate; un record con figli resta nella tabella hot.",
    "SAFE": "Lo spostamento è sicuro: file verificati (righe, chiavi, SHA-256) prima di cancellare; un errore prima del commit lascia le righe "
            "nella tabella hot, un'interruzione dopo il commit è completata dal job successivo.",
    "RETENTION": "La conservazione cancella le partizioni dell'archivio finite prima del limite (o le righe hot scadute, senza archivio).",
    "TENANT": "Il job elabora ogni tenant separatamente (colonna, schema o database) e scrive l'archivio separato per tenant.",
    "LOCK": "Un solo job alla volta lavora su una tabella (lock consultivo PostgreSQL); con la row-level security serve un ruolo che veda tutti i tenant.",
    "CLI": "La riga di comando esegue un passaggio o resta attiva, con codici di uscita distinti per errore di lavoro e di configurazione.",
}


def engine_test_cases() -> List[tuple]:
    """(caso, requisito, metodo, titolo, atteso) dai docstring di engine/tests/test_engine.py: un'unica fonte."""
    names = {v: k for k, v in METHODS.items()}
    out = []
    rx = re.compile(r'"""(TC-KYBES-JOB-[A-Z0-9-]+) · (REQ-KYBES-JOB-[A-Z]+) · ([^:]+): (.*?)\. Atteso: (.*?)\."""', re.S)
    for m in rx.finditer(ENGINE_TESTS.read_text(encoding="utf-8")):
        out.append((m.group(1), m.group(2), names[m.group(3)], " ".join(m.group(4).split()), " ".join(m.group(5).split())))
    return out


def _mongo_runtime(reqs: List[Requirement], tests: List[TestCase], asil: str) -> None:
    """Moduli comuni MongoDB: formato dei documenti, contatori, transazioni, indici."""
    def req(key, text):
        rid = f"REQ-KYBES-{key}"
        reqs.append(Requirement(rid, RUNTIME, text, "modulo comune generato (MongoDB)", asil))
        return rid
    fmt = req("MONGO-FORMAT", "I valori del modello si scrivono nei documenti MongoDB nel formato comune (uuid stringa, decimal Decimal128, "
              "bigint int64, date a mezzanotte UTC, datetime ai millisecondi) e si rileggono uguali; la ricerca per prefisso protegge "
              "i caratteri speciali delle espressioni regolari.")
    seq = req("MONGO-COUNTER", "Le chiavi intere generate sono progressive per collection.")
    tx = req("MONGO-TX", "La sessione MongoDB del modello porta il tenant; la Unit of Work MongoDB conferma il lavoro riuscito e annulla quello fallito.")
    ix = req("MONGO-INDEX", "Gli indici delle collection hanno i nomi del piano degli indici, la creazione è ripetibile e un indice univoco "
             "su una colonna facoltativa ammette più documenti senza valore.")
    for tid, r, m, kind, title, exp in [
        ("TC-KYBES-MONGO-BSON", fmt, "eq", "rt_mongo_bson", "conversione di ogni tipo verso BSON e ritorno, e del valore nullo",
         "valori uguali dopo il ritorno; nullo resta nullo"),
        ("TC-KYBES-MONGO-PREFIX", fmt, "bv", "rt_mongo_prefix", "prefisso con . * ( [ ^ $ \\", "trovato solo il documento che inizia davvero con il prefisso"),
        ("TC-KYBES-MONGO-COUNTER", seq, "req", "rt_mongo_counter", "chiavi generate in due collection", "1, 2 nella prima, 1 nella seconda"),
        ("TC-KYBES-MONGO-SESSION", tx, "eq", "rt_mongo_session", "sessione con e senza tenant", "tenant legato solo quando indicato"),
        ("TC-KYBES-MONGO-COMMIT", tx, "req", "rt_mongo_commit", "lavoro riuscito in una transazione MongoDB", "dati confermati, tenant legato"),
        ("TC-KYBES-MONGO-ROLLBACK", tx, "eq", "rt_mongo_rollback", "lavoro che solleva un errore in una transazione MongoDB",
         "dati annullati, errore propagato"),
        ("TC-KYBES-MONGO-INDEXES", ix, "req", "rt_mongo_indexes", "creazione ripetuta degli indici, documenti senza la colonna univoca facoltativa",
         "stessi indici, nessun errore; due documenti senza valore accettati"),
    ]:
        tests.append(TestCase(tid, RUNTIME, [r], m, kind, title, exp))


def _jobs_runtime(reqs: List[Requirement], tests: List[TestCase], asil: str) -> None:
    for key, text in JOB_REQS.items():
        reqs.append(Requirement(f"REQ-KYBES-JOB-{key}", JOBS, text, "motore dei job generato (jobs/generated/_engine)", asil))
    for tid, rid, method, title, expected in engine_test_cases():
        tests.append(TestCase(tid, JOBS, [rid], method, "engine", title, expected, scope="jobs"))


def _mongo_cases(t: Table, tables: Dict[str, Table], reqs: List[Requirement], add, src: str, asil: str) -> None:
    """Collection MongoDB: integrità dei riferimenti fatta dal modello e conservazione con indice TTL."""
    import mongo_plan
    n = t.name
    kids = mongo_plan.children(t, tables)
    if kids:
        rid = _req(reqs, t, "DELETE-REFS", f"La cancellazione di {n} rispetta i record collegati: con restrict è rifiutata finché ne esistono, "
                   "con set_null li scollega.", f"{src}: relations (on_delete)", asil)
        for c, r in kids:
            kind = "mongo_delete_restrict" if r.on_delete == "restrict" else "mongo_delete_set_null"
            add(TestCase(f"TC-{n}-DELETE-{c.name}-{r.name}", n, [rid], "eg" if r.on_delete == "restrict" else "req", kind,
                         f"cancellazione di un record con un {c.name} collegato ({r.name}, {r.on_delete})",
                         "rifiutata, il record resta" if r.on_delete == "restrict" else f"riuscita, {r.foreign_key} del collegato resta vuota",
                         {"child": c.name, "relation": r.name}))
    if t.pk.auto:
        add(TestCase(f"TC-{n}-KEY-GIVEN", n, [f"REQ-{n}-CREATE"], "eq", "mongo_key_given", "inserimento con la chiave già indicata",
                     "il record è salvato con quella chiave (generata solo se manca)"))
    for c in t.columns:
        if c.unique and c.nullable:
            add(TestCase(f"TC-{n}-{c.name}-UNIQUE-NULL", n, [f"REQ-{n}-{c.name}-UNIQUE"], "bv", "mongo_unique_null",
                         f"due record senza {c.name}", "entrambi accettati: l'univocità vale solo per i valori presenti, come in SQL",
                         {"column": c.name}))
    if t.retention:
        r = t.retention
        rid = _req(reqs, t, "RETENTION", f"I documenti di {n} con {r.on} più vecchia di {r.delete_after} sono cancellati da MongoDB "
                   f"(indice TTL di {mongo_plan.duration_days(r.delete_after)} giorni).", f"{src}: retention", asil)
        add(TestCase(f"TC-{n}-TTL-INDEX", n, [rid], "req", "mongo_ttl", "indici della collection dopo ensure_indexes",
                     "indice TTL sulla colonna dell'età con la durata della conservazione"))


def _lifecycle_cases(t: Table, tables: Dict[str, Table], reqs: List[Requirement], add, src: str, asil: str) -> None:
    n = t.name
    a, r = t.archive, t.retention
    if a:
        parts = ", ".join(a.partition_by) or "nessuna"
        rid = _req(reqs, t, "ARCHIVE", f"I record di {n} con {a.on} più vecchia di {a.after} passano nell'archivio {a.target} in Parquet "
                   f"(partizioni: {parts}) e lasciano la tabella hot solo dopo la verifica dei file; un record con figli resta nella tabella hot.",
                   f"{src}: archive", asil)
        add(TestCase(f"TC-{n}-JOB-ARCHIVE", n, [rid], "req", "job_archive",
                     f"un record più vecchio del limite e uno più recente, job {t.job_name}",
                     "il primo è nell'archivio nella sua partizione" + (" e come oggetto per chiave" if a.read_through else "")
                     + ", il secondo resta nella tabella hot", scope="jobs"))
        add(TestCase(f"TC-{n}-JOB-SAFE", n, [rid], "eg", "job_safe", "archivio non scrivibile durante lo spostamento",
                     "errore; il record resta nella tabella hot e l'archivio resta vuoto", scope="jobs"))
        if r:
            rr = _req(reqs, t, "RETENTION", f"Le partizioni dell'archivio di {n} sono cancellate quando finiscono prima di {r.delete_after} fa, "
                      "insieme ai loro oggetti per chiave.", f"{src}: retention", asil)
            add(TestCase(f"TC-{n}-JOB-RETENTION", n, [rr], "bv", "job_purge", f"job eseguito oltre {r.delete_after} dopo l'archiviazione",
                         "la partizione e gli oggetti per chiave non esistono più", scope="jobs"))
        if a.read_through:
            rd = _req(reqs, t, "ARCHIVE-READ", f"La lettura per chiave di {n} cerca nell'archivio un record che non è più nella tabella hot.",
                      f"{src}: archive.read_through", asil)
            add(TestCase(f"TC-{n}-ARCHIVE-READ", n, [rd], "req", "archive_read", "record solo nell'archivio, lettore legato alla sessione",
                         "getById restituisce il record con i valori archiviati"))
            add(TestCase(f"TC-{n}-ARCHIVE-READ-MISS", n, [rd], "eg", "archive_read_miss",
                         "record né nella tabella hot né nell'archivio; poi record nell'archivio ma nessun lettore legato",
                         "nessun record in entrambi i casi"))
            add(TestCase(f"TC-{n}-ARCHIVE-HOT-FIRST", n, [rd], "eq", "archive_hot_first",
                         "stessa chiave nella tabella hot e nell'archivio", "restituito il record della tabella hot"))
            if t.tenancy != "none":
                add(TestCase(f"TC-{n}-ARCHIVE-READ-TENANT", n, [rd], "eg", "archive_read_tenant",
                             "record nell'archivio del tenant A letto con il tenant B legato", "nessun record per il tenant B"))
    else:
        rr = _req(reqs, t, "RETENTION", f"I record di {n} con {r.on} più vecchia di {r.delete_after} sono cancellati dalla tabella hot.",
                  f"{src}: retention", asil)
        add(TestCase(f"TC-{n}-JOB-TTL", n, [rr], "req", "job_ttl", f"un record scaduto e uno no, job {t.job_name}",
                     "il primo è cancellato, il secondo resta", scope="jobs"))
    rid = f"REQ-{n}-ARCHIVE" if a else f"REQ-{n}-RETENTION"
    for c, rel in lifecycle_children(t, tables):
        if c.name == n or (not a and rel.on_delete != "restrict"):
            continue
        add(TestCase(f"TC-{n}-JOB-CHILD-{c.name}-{rel.name}", n, [rid], "eg", "job_children",
                     f"record con un figlio in {c.name} ({rel.name}, {rel.on_delete})", "il record resta nella tabella hot",
                     {"relation": rel.name, "child": c.name}, scope="jobs"))


def _tenancy_cases(t: Table, tables: Dict[str, Table], reqs: List[Requirement], add, src: str, asil: str) -> None:
    n = t.name
    how = {"column": "ogni metodo filtra per TenantId", "schema": "la tabella vive nello schema del tenant",
           "database": "la tabella vive nel database del tenant"}[t.tenancy]
    rid = _req(reqs, t, "TENANT", f"I dati di {n} appartengono a una Organization ({t.tenancy}: {how}): il repository lavora solo con "
               "un tenant legato alla sessione e non legge né modifica dati di un altro tenant.", f"{src}: tenancy", asil)
    add(TestCase(f"TC-{n}-TENANT-REQUIRED", n, [rid], "eg", "tenant_required", "repository su una sessione senza tenant",
                 "errore: tenant mancante, nessuna operazione eseguita"))
    if t.tenancy != "column":
        return
    add(TestCase(f"TC-{n}-TENANT-ISOLATION", n, [rid], "req", "tenant_isolation",
                 "record del tenant A letto, contato, elencato, modificato e cancellato con il tenant B legato",
                 "per il tenant B il record non esiste; resta intatto per il tenant A"))
    add(TestCase(f"TC-{n}-TENANT-ASSIGN", n, [rid], "eq", "tenant_assign",
                 "inserimento senza TenantId e con il TenantId di un altro tenant",
                 "il primo prende il tenant della sessione, il secondo è rifiutato (TenantId)"))
    uniq = [c for c in t.columns if c.unique and not c.primary_key]
    if uniq:
        add(TestCase(f"TC-{n}-TENANT-UNIQUE", n, [rid], "eq", "tenant_unique",
                     f"stesso valore di {uniq[0].name} in due tenant", "accettato: l'univocità vale per tenant",
                     {"column": uniq[0].name}))
    for r in t.relations:
        if r.kind == "many_to_one" and tables[r.target].tenancy == "column":
            add(TestCase(f"TC-{n}-{r.name}-TENANT-PARENT", n, [rid], "eg", "tenant_parent",
                         f"collegamento a un {r.target} di un altro tenant", f"errore di validazione su {r.foreign_key}: non trovato",
                         {"relation": r.name}))


# casi dei moduli comuni SQL: con sole collection MongoDB quei moduli non vengono generati
SQL_RUNTIME = {"rt_like", "rt_isolation", "rt_isolation_applied", "rt_commit", "rt_rollback",
               "rt_retry", "rt_retry_limit", "rt_retry_other", "rt_tenant_uow", "rt_archive_path", "rt_archive_file", "rt_archive_decode"}


def _runtime(reqs: List[Requirement], tests: List[TestCase], asil: str, sql: bool = True) -> None:
    """Requisiti dei moduli comuni (paginazione e Unit of Work), con l'ASIL più alto del progetto.
    Senza tabelle SQL restano paginazione (contratto e cursore), tenant e API: il resto è solo SQL."""
    first = len(reqs)

    def req(key, text):
        rid = f"REQ-KYBES-{key}"
        reqs.append(Requirement(rid, RUNTIME, text, "modulo comune generato", asil))
        return rid
    sort = req("PAGE-SORT", "L'ordinamento richiesto accetta solo colonne ammesse e la chiave, con + e -, e aggiunge la chiave per un ordine stabile.")
    cur = req("PAGE-CURSOR", "Il cursore codifica e decodifica ogni tipo ordinabile e rifiuta valori di tipo errato o ordinamenti diversi.")
    like = req("PAGE-LIKE", "Il prefisso per LIKE protegge %, _ e il carattere di escape.")
    fixed = req("PAGE-FIXED", "Una query con ordinamento fisso rifiuta un ordinamento richiesto; una tabella vuota dà una pagina senza cursore.")
    iso = req("UOW-ISOLATION", "La Unit of Work usa il livello di isolamento più severo tra le tabelle coinvolte.")
    tx = req("UOW-COMMIT", "La Unit of Work conferma il lavoro riuscito e annulla quello fallito.")
    api = req("API", "Il modello espone da punti d'ingresso stabili (indice generato e un file per tabella) entità, repository, validatori e specifiche di paginazione.")
    tenant = req("TENANT", "Il contesto del tenant si lega alla sessione e se ne scollega; i nomi di schema e database derivati "
                 "dal tenant sono sicuri; la Unit of Work lega il tenant alla transazione.")
    arch = req("ARCHIVE-READ", "Il percorso di un oggetto per chiave dell'archivio è sicuro e uguale a quello scritto dal job; "
               "il lettore su file restituisce l'oggetto o nessun dato e rifiuta percorsi fuori dalla sua cartella; "
               "ogni tipo del formato dell'archivio si decodifica nel tipo del linguaggio.")
    retry = req("UOW-RETRY", "La Unit of Work ripete il lavoro solo sui conflitti di serializzazione e sui deadlock, entro il numero massimo di tentativi.")
    for tid, r, m, kind, title, exp in [
        ("TC-KYBES-TENANT-BIND", tenant, "eq", "rt_tenant_bind", "tenant legato, cambiato, scollegato, non valido",
         "la sessione restituisce il tenant legato; senza tenant o con un valore non valido: errore"),
        ("TC-KYBES-TENANT-NAMES", tenant, "bv", "rt_tenant_names", "schema, search_path e URL del database derivati dal tenant",
         "nomi con sole minuscole, cifre e _; modello di URL senza {tenant} rifiutato"),
        ("TC-KYBES-TENANT-UOW", tenant, "req", "rt_tenant_uow", "Unit of Work con tenant",
         "la sessione della transazione è legata al tenant (su PostgreSQL anche app.tenant_id)"),
        ("TC-KYBES-ARCHIVE-PATH", arch, "eq", "rt_archive_path", "chiavi e tenant con caratteri sicuri e non sicuri",
         "lettere, cifre, _ e - restano; il resto diventa %XX in UTF-8"),
        ("TC-KYBES-ARCHIVE-FILE", arch, "eg", "rt_archive_file", "lettura di un oggetto presente, assente e fuori dalla cartella",
         "contenuto, poi nessun dato, poi errore"),
        ("TC-KYBES-ARCHIVE-DECODE", arch, "eq", "rt_archive_decode", "decodifica di ogni tipo del formato dell'archivio, con valore e nullo",
         "valori nel tipo del linguaggio; nullo resta nullo"),
        ("TC-KYBES-API-EXPORTS", api, "req", "rt_exports", "lettura di ogni simbolo esportato dall'indice e dai file per tabella",
         "ogni simbolo è definito; per ogni tabella esistono entità e repository"),
        ("TC-KYBES-SORT-KEY", sort, "eq", "rt_sort_key", "ordinamento sulla chiave, discendente", "solo la chiave, discendente"),
        ("TC-KYBES-SORT-PLUS", sort, "eq", "rt_sort_plus", "ordinamento con + esplicito", "ordine ascendente con la chiave in coda"),
        ("TC-KYBES-CURSOR-ROUNDTRIP", cur, "eq", "rt_cursor_roundtrip", "cursore con valori di ogni tipo", "i valori decodificati coincidono"),
        ("TC-KYBES-CURSOR-TYPES", cur, "eg", "rt_cursor_types", "cursore con valori di tipo errato", "errore di validazione su cursor"),
        ("TC-KYBES-CURSOR-SIGNATURE", cur, "eg", "rt_cursor_signature", "cursore prodotto con un altro ordinamento", "errore di validazione su cursor"),
        ("TC-KYBES-LIKE-ESCAPE", like, "bv", "rt_like", "prefisso con %, _ e \\", "caratteri protetti, % finale"),
        ("TC-KYBES-FIXED-SORT", fixed, "eq", "rt_fixed_sort", "ordinamento richiesto su query a ordine fisso", "errore di validazione su sort"),
        ("TC-KYBES-EMPTY-PAGE", fixed, "bv", "rt_empty_page", "pagina di una tabella vuota", "nessun record, cursore nullo"),
        ("TC-KYBES-ISOLATION", iso, "req", "rt_isolation", "isolamento per tabelle note, sconosciute e nessuna", "il più severo; read_committed per default"),
        ("TC-KYBES-ISOLATION-APPLIED", iso, "req", "rt_isolation_applied", "livello passato al driver, anche senza nomi personalizzati",
         "il driver riceve il nome del livello; nessun livello se il nome è nullo"),
        ("TC-KYBES-COMMIT", tx, "req", "rt_commit", "lavoro riuscito in transazione", "dati confermati"),
        ("TC-KYBES-ROLLBACK", tx, "eq", "rt_rollback", "lavoro che solleva un errore", "dati annullati, errore propagato"),
        ("TC-KYBES-RETRY", retry, "req", "rt_retry", "conflitto di serializzazione due volte, poi successo", "tre tentativi, resta solo l'ultimo"),
        ("TC-KYBES-RETRY-LIMIT", retry, "bv", "rt_retry_limit", "conflitti oltre il numero massimo di tentativi", "errore propagato dopo maxRetries + 1 tentativi"),
        ("TC-KYBES-RETRY-NONRETRYABLE", retry, "eg", "rt_retry_other", "errore non ritentabile", "un solo tentativo"),
    ]:
        if sql or kind not in SQL_RUNTIME:
            tests.append(TestCase(tid, RUNTIME, [r], m, kind, title, exp))
    if not sql:  # requisiti senza casi: solo SQL
        used = {r for tc in tests for r in tc.reqs}
        reqs[first:] = [r for r in reqs[first:] if r.id in used]


# ------------------------------------------------------------------ documenti di verifica

def verification_docs(cat: Catalog, tables: Dict[str, Table], test_files: Dict[str, Dict[str, str]],
                      default_asil: str, thresholds: Dict[str, Dict]) -> Dict[str, str]:
    """test_files: {lingua: {tabella: percorso del file di test generato}}."""
    from naming import MARKER
    head = f"<!-- {MARKER}. NON MODIFICARE: rigenerato dagli schemi. -->\n"
    docs: Dict[str, str] = {}
    langs = list(test_files)
    title = {"python": "Python", "typescript": "TypeScript", "csharp": "C#", "java": "Java", "jobs": "Job (pytest)"}

    o = [head + "# Requisiti di unità", "",
         "Requisiti derivati dagli schemi in `schemas/db`. L'ID è stabile: dipende dai nomi, non dall'ordine.", "",
         "| ID | ASIL | Requisito | Origine |", "|---|---|---|---|"]
    for r in cat.requirements:
        o.append(f"| `{r.id}` | {r.asil} | {r.text} | `{r.source}` |")
    docs["requirements.md"] = "\n".join(o) + "\n"

    for n, t in list(tables.items()) + [(RUNTIME, None), (JOBS, None)]:
        tcs = cat.for_table(n, "all")
        if not tcs:
            continue
        if n == JOBS:
            o = [head + "# Specifica dei test di unità: motore dei job (archiviazione e conservazione)", "",
                 f"{len(tcs)} casi di test · `jobs/generated/_engine/tests/test_engine.py`", "",
                 "| Caso | Requisiti | Metodo di derivazione | Descrizione | Esito atteso |", "|---|---|---|---|---|"]
            for tc in tcs:
                o.append(f"| `{tc.id}` | {', '.join(f'`{r}`' for r in tc.reqs)} | {METHODS[tc.method]} | {tc.title} | {tc.expected} |")
            docs["kybes-jobs.md"] = "\n".join(o) + "\n"
            continue
        if t is None:
            o = [head + "# Specifica dei test di unità: moduli comuni (paginazione, Unit of Work, archivio)", "",
                 f"{len(tcs)} casi di test", "", "| Caso | Requisiti | Metodo di derivazione | Descrizione | Esito atteso |", "|---|---|---|---|---|"]
            for tc in tcs:
                o.append(f"| `{tc.id}` | {', '.join(f'`{r}`' for r in tc.reqs)} | {METHODS[tc.method]} | {tc.title} | {tc.expected} |")
            docs["kybes-runtime.md"] = "\n".join(o) + "\n"
            continue
        o = [head + f"# Specifica dei test di unità: {n}", "",
             f"ASIL {table_asil(t, default_asil)} · {len(tcs)} casi di test · schema `schemas/db/{n}.yaml`", "",
             "| Caso | Requisiti | Metodo di derivazione | Descrizione | Esito atteso |", "|---|---|---|---|---|"]
        for tc in tcs:
            o.append(f"| `{tc.id}` | {', '.join(f'`{r}`' for r in tc.reqs)} | {METHODS[tc.method]} | {tc.title} | {tc.expected} |")
        if langs:
            o += ["", "File di test generati:", ""]
            for lg in langs:
                if n in test_files[lg]:
                    o.append(f"- {title[lg]}: `{test_files[lg][n]}`")
        docs[f"{n}.md"] = "\n".join(o) + "\n"

    o = [head + "# Matrice di tracciabilità", "",
         "Requisito → casi di test → file di test per linguaggio. Ogni caso di test compare nel nome della funzione di test "
         "(es. `TC-Clienti-CREATE-VALID` → `test_clienti_create_valid`), quindi la matrice si verifica cercando l'ID nel codice.", "",
         "| Requisito | ASIL | Casi di test | " + " | ".join(title[x] for x in langs) + " |",
         "|---|---|---|" + "---|" * len(langs)]
    by_req: Dict[str, List[TestCase]] = {}
    for tc in cat.tests:
        for r in tc.reqs:
            by_req.setdefault(r, []).append(tc)
    for r in cat.requirements:
        tcs = by_req.get(r.id, [])
        scopes = {tc.scope for tc in tcs}
        files = [f"`{test_files[lg][r.table]}`" if r.table in test_files[lg] and ("jobs" if lg == "jobs" else "model") in scopes else "—"
                 for lg in langs]
        o.append(f"| `{r.id}` | {r.asil} | {', '.join(f'`{tc.id}`' for tc in tcs) or '**nessuno**'} | " + " | ".join(files) + " |")
    uncovered = [r.id for r in cat.requirements if r.id not in by_req]
    o += ["", f"Requisiti senza casi di test: **{len(uncovered)}**."]
    docs["traceability.md"] = "\n".join(o) + "\n"

    o = [head + "# Criteri di copertura strutturale", "",
         "Soglie applicate dal controllo di fine lavoro (`coverage_gate`) sui report di copertura configurati in "
         "`verification.coverage_reports`. Il livello applicato è l'ASIL più alto tra le tabelle del progetto.", "",
         "| ASIL | Istruzioni | Rami | MC/DC |", "|---|---|---|---|"]
    for a in ASIL:
        th = thresholds.get(a, {})
        o.append(f"| {a} | {th.get('statement', '—')}{'%' if 'statement' in th else ''} | {th.get('branch', '—')}{'%' if 'branch' in th else ''} | "
                 f"{'casi di test MC/DC generati per le condizioni delle query' if a in ('C', 'D') else '—'} |")
    proj = max((table_asil(t, default_asil) for t in tables.values()), key=ASIL.index, default=default_asil)
    o += ["", f"ASIL più alto nel progetto: **{proj}**.", "",
          "La copertura MC/DC strutturale non è misurabile con gli strumenti di copertura comuni per Python, TypeScript, Java e C#. "
          "Per ASIL C e D kybes genera casi di test che dimostrano l'effetto indipendente di ogni condizione delle query dichiarate, "
          "e applica la copertura dei rami come misura strutturale. Per la certificazione serve uno strumento qualificato secondo "
          "ISO 26262-8."]
    docs["coverage.md"] = "\n".join(o) + "\n"
    return docs
