"""Catalogo dei requisiti e dei casi di test di unità, derivato dagli schemi (ISO 26262-6, verifica di unità).

Il catalogo è indipendente dal linguaggio: ogni emettitore di test lo rende in pytest, node:test, JUnit o xUnit.
ID stabili: dipendono dai nomi nello schema, non dall'ordine, quindi la tracciabilità non cambia
quando si aggiungono colonne o tabelle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from schema import ASIL, Cond, Query, Table

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

    @property
    def slug(self) -> str:
        return self.id[3:].replace("-", "_").lower()


@dataclass
class Catalog:
    requirements: List[Requirement]
    tests: List[TestCase]

    def for_table(self, name: str) -> List[TestCase]:
        return [t for t in self.tests if t.table == name]


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


def build_catalog(tables: Dict[str, Table], default_asil: str = "B") -> Catalog:
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
        upd = next((c for c in t.columns if not c.primary_key and not c.generated and c.name not in t.fk_columns()
                    and c.type in ("string", "text", "int", "bigint", "decimal") and not c.unique), None)
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
            if c.primary_key or c.generated:
                continue
            if c.required and c.default is None:
                rid = _req(reqs, t, f"{c.name}-REQUIRED", f"{n}.{c.name} è obbligatorio.", f"{src}: columns.{c.name}.required", asil)
                add(TestCase(f"TC-{n}-{c.name}-NULL", n, [rid], "eq", "required_null",
                             f"inserimento con {c.name} assente (classe non valida)", f"errore di validazione su {c.name}: obbligatorio",
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
                add(TestCase(f"TC-{n}-{r.foreign_key}-LISTBY", n, [rid], "req", "list_by",
                             f"pagina dei {n} con {r.foreign_key} dato", "contiene il record e solo record con quel valore",
                             {"relation": r.name}))
            else:
                rid = _req(reqs, t, f"{r.name}-CHILDREN", f"Da {n} si leggono i {r.target} collegati.", f"{src}: relations.{r.name}", asil)
                add(TestCase(f"TC-{n}-{r.name}-CHILDREN", n, [rid], "req", "rel_children",
                             f"pagina dei {r.target} collegati", "contiene il figlio e solo figli di quel record", {"relation": r.name}))
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
    _runtime(reqs, tests, max((table_asil(t, default_asil) for t in tables.values()), key=ASIL.index, default=default_asil))
    return Catalog(reqs, tests)


RUNTIME = "_runtime"


def _runtime(reqs: List[Requirement], tests: List[TestCase], asil: str) -> None:
    """Requisiti dei moduli comuni (paginazione e Unit of Work), con l'ASIL più alto del progetto."""
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
    retry = req("UOW-RETRY", "La Unit of Work ripete il lavoro solo sui conflitti di serializzazione e sui deadlock, entro il numero massimo di tentativi.")
    for tid, r, m, kind, title, exp in [
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
        tests.append(TestCase(tid, RUNTIME, [r], m, kind, title, exp))


# ------------------------------------------------------------------ documenti di verifica

def verification_docs(cat: Catalog, tables: Dict[str, Table], test_files: Dict[str, Dict[str, str]],
                      default_asil: str, thresholds: Dict[str, Dict]) -> Dict[str, str]:
    """test_files: {lingua: {tabella: percorso del file di test generato}}."""
    from naming import MARKER
    head = f"<!-- {MARKER}. NON MODIFICARE: rigenerato dagli schemi. -->\n"
    docs: Dict[str, str] = {}
    langs = list(test_files)
    title = {"python": "Python", "typescript": "TypeScript", "csharp": "C#", "java": "Java"}

    o = [head + "# Requisiti di unità", "",
         "Requisiti derivati dagli schemi in `schemas/db`. L'ID è stabile: dipende dai nomi, non dall'ordine.", "",
         "| ID | ASIL | Requisito | Origine |", "|---|---|---|---|"]
    for r in cat.requirements:
        o.append(f"| `{r.id}` | {r.asil} | {r.text} | `{r.source}` |")
    docs["requirements.md"] = "\n".join(o) + "\n"

    for n, t in list(tables.items()) + [(RUNTIME, None)]:
        tcs = cat.for_table(n)
        if not tcs:
            continue
        if t is None:
            o = [head + "# Specifica dei test di unità: moduli comuni (paginazione, Unit of Work)", "",
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
        files = [f"`{test_files[lg].get(r.table, '—')}`" for lg in langs]
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
