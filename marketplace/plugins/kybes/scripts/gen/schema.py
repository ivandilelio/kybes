"""Caricamento e validazione degli schemi tabella (schemas/db/<Tabella>.yaml)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from miniyaml import YamlError, load_file

TYPES = {"uuid", "string", "text", "int", "bigint", "decimal", "bool", "date", "datetime", "json"}
KINDS = {"many_to_one", "one_to_many"}
ON_DELETE = {"restrict", "cascade", "set_null"}
GENERATED = {"on_create", "on_update"}
OPS = {"eq", "ne", "lt", "lte", "gt", "gte", "in", "prefix", "is_null", "not_null"}
RETURNS = {"page", "list", "one"}
ISOLATION = {"read_committed", "repeatable_read", "serializable"}
ISOLATION_RANK = {"read_committed": 0, "repeatable_read": 1, "serializable": 2}
SORTABLE_TYPES = {"uuid", "string", "int", "bigint", "decimal", "date", "datetime"}
RESERVED_KEYS = {"storage": 6}
TENANCY = ("none", "column", "schema", "database")
TENANT_COL = "TenantId"
TENANT_ID_TYPES = ("uuid", "string")
# relazioni ammesse (tabella figlia → tabella padre) per modalità di isolamento
TENANCY_LINKS = {("none", "none"), ("column", "none"), ("column", "column"), ("schema", "none"), ("schema", "schema"),
                 ("database", "database")}
ASIL = ("QM", "A", "B", "C", "D")
# archivio e conservazione (fase 5)
DURATION = re.compile(r"^([1-9][0-9]{0,4})([dmy])$")
ARCHIVE_TARGETS = ("s3", "blob")
PARTITIONS = ("tenant", "year", "month", "day")
JOB_MODES = ("cron", "keda", "engine")
CRON = re.compile(r"^\S+(\s+\S+){4}$")
DEFAULT_LIMIT = 50
DEFAULT_MAX_LIMIT = 100
IDENT = re.compile(r"^[A-Z][A-Za-z0-9]*$")
RESERVED = {"Id"}  # usabile solo come nome colonna, non come relazione


class SchemaError(Exception):
    def __init__(self, errors: List[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


def snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
    s = re.sub(r"(?<=[A-Z])([A-Z][a-z])", r"_\1", s)
    return s.lower()


def camel(name: str) -> str:
    return name[:1].lower() + name[1:]


@dataclass
class Column:
    name: str
    type: str
    db_name: str
    primary_key: bool = False
    required: bool = False
    unique: bool = False
    length: Optional[int] = None
    precision: int = 18
    scale: int = 2
    default: Any = None
    generated: Optional[str] = None      # on_create | on_update (datetime)
    auto: bool = False                   # PK generata dal sistema
    description: str = ""
    tenant: bool = False                 # colonna TenantId aggiunta dal generatore (tenancy: column)

    @property
    def nullable(self) -> bool:
        return not (self.required or self.primary_key)


@dataclass
class Relation:
    name: str
    kind: str
    target: str
    foreign_key: str
    on_delete: str = "restrict"
    inverse: Optional[str] = None        # nome della relazione opposta nella tabella target


@dataclass
class Index:
    columns: List[str]
    unique: bool = False


@dataclass
class Cond:
    column: str
    op: str = "eq"
    param: Optional[str] = None          # None per is_null/not_null e per i valori costanti
    value: Any = None
    has_value: bool = False


@dataclass
class Query:
    name: str
    where: List[Cond]
    order_by: List[tuple]                # [(colonna, desc)]
    returns: str = "page"


@dataclass
class Pagination:
    default_order: List[tuple] = field(default_factory=list)   # [(colonna, desc)], vuoto = chiave
    sortable: List[str] = field(default_factory=list)
    max_limit: int = DEFAULT_MAX_LIMIT
    default_limit: int = DEFAULT_LIMIT


@dataclass
class Job:
    mode: str = "cron"                   # cron (CronJob) | keda (ScaledJob KEDA) | engine (Deployment sempre attivo)
    schedule: str = "17 3 * * *"         # cron: passaggio pianificato; keda: passaggio giornaliero di sicurezza
    interval: int = 300                  # secondi: polling di KEDA o pausa del motore sempre attivo
    batch_size: int = 1000               # righe per transazione


@dataclass
class Archive:
    after: str                           # durata: 90d, 12m, 5y
    on: str                              # archive.column: colonna date/datetime su cui si misura l'età
    target: str = "s3"
    format: str = "parquet"
    partition_by: List[str] = field(default_factory=lambda: ["year", "month"])
    read_through: bool = False


@dataclass
class Retention:
    delete_after: str
    on: Optional[str] = None             # solo senza archivio: cancellazione dalla tabella hot


def duration_days(d: str) -> int:
    n, u = DURATION.match(d).groups()
    return int(n) * {"d": 1, "m": 30, "y": 365}[u]


@dataclass
class Table:
    name: str
    db_name: str
    description: str
    columns: List[Column]
    relations: List[Relation] = field(default_factory=list)
    indexes: List[Index] = field(default_factory=list)
    source: str = ""
    queries: List[Query] = field(default_factory=list)
    pagination: Pagination = field(default_factory=Pagination)
    isolation: str = "read_committed"
    asil: Optional[str] = None           # None = livello predefinito della configurazione
    tenancy: Optional[str] = None        # None = livello predefinito della configurazione
    archive: Optional[Archive] = None
    retention: Optional[Retention] = None
    job: Optional[Job] = None

    @property
    def job_name(self) -> str:
        """Nome Kubernetes del job di archiviazione o conservazione (es. righe-ordine-archive)."""
        return snake(self.name).replace("_", "-") + ("-archive" if self.archive else "-retention")

    @property
    def pk(self) -> Column:
        return next(c for c in self.columns if c.primary_key)

    def col(self, name: str) -> Optional[Column]:
        return next((c for c in self.columns if c.name == name), None)

    def fk_columns(self) -> List[str]:
        return [r.foreign_key for r in self.relations if r.kind == "many_to_one"]

    def order(self, explicit: Optional[List[tuple]] = None) -> List[tuple]:
        """Ordine completo e stabile: quello richiesto (o il default) più la chiave in coda."""
        base = list(explicit) if explicit else list(self.pagination.default_order)
        if not any(c == self.pk.name for c, _ in base):
            base.append((self.pk.name, False))
        return base


def _bool(v, where, errs) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    errs.append(f"{where}: atteso true/false, trovato {v!r}")
    return False


def _parse_table(path: Path, data: Any) -> (Optional[Table], List[str]):
    errs: List[str] = []
    f = path.name
    if not isinstance(data, dict):
        return None, [f"{f}: il file deve contenere una mappa con 'table' e 'columns'"]
    allowed = {"table", "db_name", "description", "columns", "relations", "indexes", "queries", "pagination", "transactions",
               "verification", "tenancy", "archive", "retention"}
    for k in data:
        if k in RESERVED_KEYS:
            errs.append(f"{f}: la chiave '{k}' è prevista nella fase {RESERVED_KEYS[k]} della roadmap e non è ancora supportata")
        elif k not in allowed:
            errs.append(f"{f}: chiave sconosciuta '{k}' (ammesse: {', '.join(sorted(allowed))})")
    name = data.get("table")
    if not isinstance(name, str) or not IDENT.match(name):
        errs.append(f"{f}: 'table' deve essere un nome PascalCase (es. Clienti)")
        return None, errs
    if path.stem != name:
        errs.append(f"{f}: il nome del file deve coincidere con la tabella ({name}.yaml)")

    cols: List[Column] = []
    raw_cols = data.get("columns")
    if not isinstance(raw_cols, list) or not raw_cols:
        errs.append(f"{f}: 'columns' deve essere una lista non vuota")
        raw_cols = []
    col_keys = {"name", "type", "db_name", "primary_key", "required", "unique", "length", "precision",
                "scale", "default", "generated", "auto", "description"}
    for i, c in enumerate(raw_cols):
        w = f"{f}: colonna #{i + 1}"
        if not isinstance(c, dict):
            errs.append(f"{w}: deve essere una mappa")
            continue
        for k in c:
            if k not in col_keys:
                errs.append(f"{w}: chiave sconosciuta '{k}'")
        cn, ct = c.get("name"), c.get("type")
        if not isinstance(cn, str) or not IDENT.match(cn):
            errs.append(f"{w}: 'name' deve essere PascalCase")
            continue
        w = f"{f}: colonna {cn}"
        if ct not in TYPES:
            errs.append(f"{w}: tipo '{ct}' non valido (ammessi: {', '.join(sorted(TYPES))})")
            continue
        col = Column(name=cn, type=ct, db_name=c.get("db_name") or snake(cn),
                     primary_key=_bool(c.get("primary_key"), w, errs),
                     required=_bool(c.get("required"), w, errs),
                     unique=_bool(c.get("unique"), w, errs),
                     description=str(c.get("description") or ""))
        if ct == "string":
            ln = c.get("length")
            if not isinstance(ln, int) or ln <= 0:
                errs.append(f"{w}: le colonne string richiedono 'length' intero positivo (per testi lunghi usa type: text)")
            col.length = ln if isinstance(ln, int) else None
        elif c.get("length") is not None:
            errs.append(f"{w}: 'length' vale solo per type: string")
        if ct == "decimal":
            col.precision = int(c.get("precision", 18))
            col.scale = int(c.get("scale", 2))
        g = c.get("generated")
        if g is not None:
            if g not in GENERATED or ct != "datetime":
                errs.append(f"{w}: 'generated' ammette on_create/on_update solo su colonne datetime")
            else:
                col.generated = g
        if col.primary_key:
            if ct not in ("uuid", "int", "bigint", "string"):
                errs.append(f"{w}: la chiave primaria deve essere uuid, int, bigint o string")
            auto = c.get("auto")
            col.auto = (ct != "string") if auto is None else _bool(auto, w, errs)
            if col.auto and ct == "string":
                errs.append(f"{w}: una chiave primaria string non può essere generata (auto: false)")
        elif c.get("auto") is not None:
            errs.append(f"{w}: 'auto' vale solo per la chiave primaria")
        d = c.get("default")
        if d is not None:
            if isinstance(d, (dict, list)):
                errs.append(f"{w}: 'default' deve essere un valore semplice")
            elif ct in ("uuid", "date", "datetime", "json"):
                errs.append(f"{w}: 'default' non supportato per type {ct} (usa generated per le date)")
            else:
                col.default = d
        cols.append(col)

    names = [c.name for c in cols]
    for n in set(names):
        if names.count(n) > 1:
            errs.append(f"{f}: colonna {n} ripetuta")
    pks = [c for c in cols if c.primary_key]
    if len(pks) != 1:
        errs.append(f"{f}: serve esattamente una colonna con primary_key: true (chiavi composte non supportate)")

    rels: List[Relation] = []
    rel_keys = {"name", "kind", "target", "foreign_key", "on_delete", "inverse"}
    for i, r in enumerate(data.get("relations") or []):
        w = f"{f}: relazione #{i + 1}"
        if not isinstance(r, dict):
            errs.append(f"{w}: deve essere una mappa")
            continue
        for k in r:
            if k not in rel_keys:
                errs.append(f"{w}: chiave sconosciuta '{k}'")
        rn = r.get("name")
        if not isinstance(rn, str) or not IDENT.match(rn) or rn in RESERVED:
            errs.append(f"{w}: 'name' deve essere PascalCase")
            continue
        w = f"{f}: relazione {rn}"
        if rn in names:
            errs.append(f"{w}: il nome coincide con una colonna")
        if r.get("kind") not in KINDS:
            errs.append(f"{w}: 'kind' deve essere many_to_one o one_to_many")
            continue
        if not isinstance(r.get("target"), str) or not isinstance(r.get("foreign_key"), str):
            errs.append(f"{w}: servono 'target' e 'foreign_key'")
            continue
        od = r.get("on_delete", "restrict")
        if od not in ON_DELETE:
            errs.append(f"{w}: on_delete ammette restrict, cascade, set_null")
            od = "restrict"
        if r["kind"] == "one_to_many" and "on_delete" in r:
            errs.append(f"{w}: on_delete va dichiarato sulla relazione many_to_one della tabella {r['target']}")
        rels.append(Relation(rn, r["kind"], r["target"], r["foreign_key"], od, r.get("inverse")))
    rnames = [r.name for r in rels]
    for n in set(rnames):
        if rnames.count(n) > 1:
            errs.append(f"{f}: relazione {n} ripetuta")

    idx: List[Index] = []
    for i, ix in enumerate(data.get("indexes") or []):
        w = f"{f}: indice #{i + 1}"
        if not isinstance(ix, dict) or not isinstance(ix.get("columns"), list) or not ix["columns"]:
            errs.append(f"{w}: serve 'columns' come lista di colonne")
            continue
        for cn in ix["columns"]:
            if cn not in names:
                errs.append(f"{w}: colonna {cn} inesistente")
        idx.append(Index(list(ix["columns"]), _bool(ix.get("unique"), w, errs)))

    queries = _parse_queries(f, data.get("queries"), errs)
    pagination = _parse_pagination(f, data.get("pagination"), errs)
    isolation = "read_committed"
    tx = data.get("transactions")
    if tx is not None:
        if not isinstance(tx, dict) or set(tx) - {"isolation"}:
            errs.append(f"{f}: 'transactions' ammette solo 'isolation'")
        elif tx.get("isolation") not in ISOLATION:
            errs.append(f"{f}: transactions.isolation ammette {', '.join(sorted(ISOLATION))}")
        else:
            isolation = tx["isolation"]

    asil = None
    ver = data.get("verification")
    if ver is not None:
        if not isinstance(ver, dict) or set(ver) - {"asil"}:
            errs.append(f"{f}: 'verification' ammette solo 'asil'")
        elif str(ver.get("asil")) not in ASIL:
            errs.append(f"{f}: verification.asil ammette {', '.join(ASIL)}")
        else:
            asil = str(ver["asil"])

    tenancy = data.get("tenancy")
    if tenancy is not None and tenancy not in TENANCY:
        errs.append(f"{f}: tenancy ammette {', '.join(TENANCY)}")
        tenancy = None
    if any(c.name == TENANT_COL for c in cols):
        errs.append(f"{f}: la colonna {TENANT_COL} è riservata: la aggiunge il generatore alle tabelle con tenancy: column")

    archive, retention, job = _parse_lifecycle(f, data.get("archive"), data.get("retention"), errs)
    t = Table(name=name, db_name=data.get("db_name") or snake(name), description=str(data.get("description") or ""),
              columns=cols, relations=rels, indexes=idx, source=str(path), queries=queries,
              pagination=pagination, isolation=isolation, asil=asil, tenancy=tenancy,
              archive=archive, retention=retention, job=job)
    return t, errs


def _duration(where: str, v: Any, errs: List[str]) -> Optional[str]:
    if not isinstance(v, str) or not DURATION.match(v):
        errs.append(f"{where}: durata non valida {v!r} (es. 90d, 12m, 5y)")
        return None
    return v


def _parse_job(where: str, raw: Any, errs: List[str]) -> Job:
    j = Job()
    if raw is None:
        return j
    if not isinstance(raw, dict):
        errs.append(f"{where}: deve essere una mappa")
        return j
    for k in raw:
        if k not in {"mode", "schedule", "interval", "batch_size"}:
            errs.append(f"{where}: chiave sconosciuta '{k}' (ammesse: batch_size, interval, mode, schedule)")
    mode = raw.get("mode", "cron")
    if mode not in JOB_MODES:
        errs.append(f"{where}.mode ammette {', '.join(JOB_MODES)}")
    else:
        j.mode = mode
    if "schedule" in raw:
        if mode == "engine":
            errs.append(f"{where}.schedule vale con mode: cron (passaggio pianificato) o keda (passaggio giornaliero di sicurezza)")
        elif not isinstance(raw["schedule"], str) or not CRON.match(raw["schedule"].strip()):
            errs.append(f"{where}.schedule deve essere un'espressione cron di 5 campi (es. \"17 3 * * *\")")
        else:
            j.schedule = raw["schedule"].strip()
    for key, lo, hi in (("interval", 30, 86400), ("batch_size", 1, 10000)):
        if key in raw:
            v = raw[key]
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                errs.append(f"{where}.{key} deve essere un intero tra {lo} e {hi}")
            else:
                setattr(j, key, v)
    if "interval" in raw and mode == "cron":
        errs.append(f"{where}.interval vale solo con mode: keda o engine")
    return j


def _parse_lifecycle(f: str, raw_a: Any, raw_r: Any, errs: List[str]):
    """Sezioni archive e retention; i controlli sulle colonne e sul tenant sono in _check_lifecycle."""
    archive = retention = job = None
    if raw_a is not None:
        w = f"{f}: archive"
        if not isinstance(raw_a, dict):
            errs.append(f"{w}: deve essere una mappa")
        else:
            for k in raw_a:
                if k not in {"after", "column", "target", "format", "partition_by", "read_through", "job"}:
                    errs.append(f"{w}: chiave sconosciuta '{k}' (ammesse: after, column, format, job, partition_by, read_through, target)")
            after = _duration(f"{w}.after", raw_a.get("after"), errs)
            on = raw_a.get("column")
            if not isinstance(on, str):
                errs.append(f"{w}.column: serve la colonna date o datetime su cui si misura l'età")
            target = raw_a.get("target", "s3")
            if target not in ARCHIVE_TARGETS:
                errs.append(f"{w}.target ammette {', '.join(ARCHIVE_TARGETS)}")
            if raw_a.get("format", "parquet") != "parquet":
                errs.append(f"{w}.format ammette solo parquet")
            parts = raw_a.get("partition_by", ["year", "month"])
            if not isinstance(parts, list) or not all(isinstance(p, str) for p in parts):
                errs.append(f"{w}.partition_by deve essere un elenco tra {', '.join(PARTITIONS)}")
                parts = ["year", "month"]
            for p in parts:
                if p not in PARTITIONS:
                    errs.append(f"{w}.partition_by: '{p}' non valido (ammessi: {', '.join(PARTITIONS)})")
            if len(set(parts)) != len(parts):
                errs.append(f"{w}.partition_by: partizioni ripetute")
            if "month" in parts and "year" not in parts or "day" in parts and "month" not in parts:
                errs.append(f"{w}.partition_by: le partizioni di data sono gerarchiche (day richiede month, month richiede year)")
            rt = _bool(raw_a.get("read_through"), f"{w}.read_through", errs)
            job = _parse_job(f"{w}.job", raw_a.get("job"), errs)
            if after and isinstance(on, str) and target in ARCHIVE_TARGETS:
                archive = Archive(after=after, on=on, target=target, partition_by=[p for p in PARTITIONS if p in parts], read_through=rt)
    if raw_r is not None:
        w = f"{f}: retention"
        if not isinstance(raw_r, dict):
            errs.append(f"{w}: deve essere una mappa")
        else:
            for k in raw_r:
                if k not in {"delete_after", "column", "job"}:
                    errs.append(f"{w}: chiave sconosciuta '{k}' (ammesse: column, delete_after, job)")
            da = _duration(f"{w}.delete_after", raw_r.get("delete_after"), errs)
            on = raw_r.get("column")
            if raw_a is not None:
                if on is not None:
                    errs.append(f"{w}.column: con un archivio l'età si misura su archive.column (togli retention.column)")
                if "job" in raw_r:
                    errs.append(f"{w}.job: con un archivio la conservazione la esegue il job dell'archivio (archive.job)")
            else:
                if not isinstance(on, str):
                    errs.append(f"{w}.column: senza archivio serve la colonna date o datetime su cui si misura l'età")
                job = _parse_job(f"{w}.job", raw_r.get("job"), errs)
            if da:
                retention = Retention(delete_after=da, on=on if isinstance(on, str) else None)
    return archive, retention, job


def _parse_order(where: str, raw: Any, errs: List[str]) -> List[tuple]:
    out = []
    if raw is None:
        return out
    if not isinstance(raw, list):
        errs.append(f"{where}: atteso un elenco di colonne")
        return out
    for item in raw:
        if isinstance(item, str):
            out.append((item, False))
        elif isinstance(item, dict) and isinstance(item.get("column"), str) and set(item) <= {"column", "dir"}:
            d = item.get("dir", "asc")
            if d not in ("asc", "desc"):
                errs.append(f"{where}: dir ammette asc o desc")
            out.append((item["column"], d == "desc"))
        else:
            errs.append(f"{where}: ogni elemento è una colonna o {{column, dir}}")
    return out


def _parse_queries(f: str, raw: Any, errs: List[str]) -> List[Query]:
    out: List[Query] = []
    if raw is None:
        return out
    if not isinstance(raw, list):
        errs.append(f"{f}: 'queries' deve essere una lista")
        return out
    for i, q in enumerate(raw):
        w = f"{f}: query #{i + 1}"
        if not isinstance(q, dict):
            errs.append(f"{w}: deve essere una mappa")
            continue
        for k in q:
            if k not in {"name", "where", "order_by", "returns"}:
                errs.append(f"{w}: chiave sconosciuta '{k}'")
        qn = q.get("name")
        if not isinstance(qn, str) or not IDENT.match(qn):
            errs.append(f"{w}: 'name' deve essere PascalCase")
            continue
        w = f"{f}: query {qn}"
        conds: List[Cond] = []
        raw_where = q.get("where") or []
        if not isinstance(raw_where, list) or not raw_where:
            errs.append(f"{w}: 'where' deve essere una lista non vuota di condizioni")
            raw_where = []
        for c in raw_where:
            if isinstance(c, str):
                conds.append(Cond(column=c, op="eq", param=c))
                continue
            if not isinstance(c, dict) or not isinstance(c.get("column"), str):
                errs.append(f"{w}: ogni condizione è una colonna o {{column, op, param|value}}")
                continue
            for k in c:
                if k not in {"column", "op", "param", "value"}:
                    errs.append(f"{w}: chiave sconosciuta '{k}' in una condizione")
            op = c.get("op", "eq")
            if op not in OPS:
                errs.append(f"{w}: op '{op}' non valido (ammessi: {', '.join(sorted(OPS))})")
                continue
            if "value" in c and "param" in c:
                errs.append(f"{w}: una condizione ha 'param' oppure 'value', non entrambi")
            if op in ("is_null", "not_null"):
                conds.append(Cond(column=c["column"], op=op))
            elif "value" in c:
                if op == "in" and not isinstance(c["value"], list):
                    errs.append(f"{w}: con op in, 'value' deve essere una lista")
                conds.append(Cond(column=c["column"], op=op, value=c["value"], has_value=True))
            else:
                pn = c.get("param", c["column"])
                if not isinstance(pn, str) or not IDENT.match(pn):
                    errs.append(f"{w}: 'param' deve essere PascalCase")
                    pn = c["column"]
                conds.append(Cond(column=c["column"], op=op, param=pn))
        params = [x.param for x in conds if x.param]
        for p in set(params):
            if params.count(p) > 1:
                errs.append(f"{w}: parametro {p} ripetuto: usa 'param' per distinguerli")
        ret = q.get("returns", "page")
        if ret not in RETURNS:
            errs.append(f"{w}: returns ammette page, list, one")
        out.append(Query(qn, conds, _parse_order(f"{w}.order_by", q.get("order_by"), errs), ret))
    names = [q.name for q in out]
    for n in set(names):
        if names.count(n) > 1:
            errs.append(f"{f}: query {n} ripetuta")
    return out


def _parse_pagination(f: str, raw: Any, errs: List[str]) -> Pagination:
    p = Pagination()
    if raw is None:
        return p
    if not isinstance(raw, dict):
        errs.append(f"{f}: 'pagination' deve essere una mappa")
        return p
    for k in raw:
        if k not in {"default_order", "sortable", "max_limit", "default_limit"}:
            errs.append(f"{f}: pagination: chiave sconosciuta '{k}'")
    p.default_order = _parse_order(f"{f}: pagination.default_order", raw.get("default_order"), errs)
    s = raw.get("sortable") or []
    if not isinstance(s, list) or not all(isinstance(x, str) for x in s):
        errs.append(f"{f}: pagination.sortable deve essere un elenco di colonne")
        s = []
    p.sortable = list(s)
    for key in ("max_limit", "default_limit"):
        if key in raw:
            v = raw[key]
            if not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 10000:
                errs.append(f"{f}: pagination.{key} deve essere un intero tra 1 e 10000")
            else:
                setattr(p, key, v)
    if "default_limit" not in raw:
        p.default_limit = min(DEFAULT_LIMIT, p.max_limit)
    if p.default_limit > p.max_limit:
        errs.append(f"{f}: pagination.default_limit non può superare max_limit")
    return p


def _cross_check(tables: Dict[str, Table]) -> List[str]:
    errs: List[str] = []
    dbn = {}
    for t in tables.values():
        if t.db_name in dbn:
            errs.append(f"{t.name}: db_name '{t.db_name}' già usato da {dbn[t.db_name]}")
        dbn[t.db_name] = t.name
    for t in tables.values():
        for r in t.relations:
            w = f"{t.name}.{r.name}"
            tgt = tables.get(r.target)
            if not tgt:
                errs.append(f"{w}: tabella target {r.target} inesistente (manca schemas/db/{r.target}.yaml)")
                continue
            if r.kind == "many_to_one":
                fk = t.col(r.foreign_key)
                if not fk:
                    errs.append(f"{w}: foreign_key {r.foreign_key} non è una colonna di {t.name}")
                    continue
                if fk.type != tgt.pk.type:
                    errs.append(f"{w}: {r.foreign_key} è {fk.type} ma la chiave di {tgt.name} è {tgt.pk.type}")
                if r.on_delete == "set_null" and fk.required:
                    errs.append(f"{w}: on_delete set_null richiede che {r.foreign_key} non sia required")
                inv = [x for x in tgt.relations if x.kind == "one_to_many" and x.target == t.name and x.foreign_key == r.foreign_key]
                if len(inv) > 1:
                    errs.append(f"{w}: più relazioni one_to_many in {tgt.name} usano {r.foreign_key}")
                r.inverse = inv[0].name if inv else None
            else:
                fk = tgt.col(r.foreign_key)
                if not fk:
                    errs.append(f"{w}: foreign_key {r.foreign_key} non è una colonna di {tgt.name}")
                    continue
                back = [x for x in tgt.relations if x.kind == "many_to_one" and x.target == t.name and x.foreign_key == r.foreign_key]
                if not back:
                    errs.append(f"{w}: dichiara in {tgt.name}.yaml la relazione many_to_one verso {t.name} su {r.foreign_key}")
                    continue
                r.inverse = back[0].name
                r.on_delete = back[0].on_delete
    for t in tables.values():
        errs += _check_access(t)
        errs += _check_lifecycle(t)
    return errs


def _check_age_col(t: Table, cn: str, where: str) -> List[str]:
    c = t.col(cn)
    if not c:
        return [f"{where}: colonna {cn} inesistente"]
    if c.type not in ("date", "datetime"):
        return [f"{where}: {cn} è di tipo {c.type}, serve date o datetime"]
    if c.nullable and c.generated != "on_create":
        return [f"{where}: {cn} deve essere required (o generated: on_create): un record senza data non verrebbe mai archiviato"]
    return []


def _check_lifecycle(t: Table) -> List[str]:
    errs: List[str] = []
    a, r = t.archive, t.retention
    if a:
        errs += _check_age_col(t, a.on, f"{t.name}.archive.column")
        clash = sorted({c.db_name for c in t.columns} & set(PARTITIONS))
        if clash:
            errs.append(f"{t.name}.archive: le colonne {', '.join(clash)} hanno lo stesso nome di una partizione: rinominale con db_name")
    if r:
        if a and "year" not in a.partition_by:
            errs.append(f"{t.name}.retention: la conservazione cancella partizioni di data intere, serve year in archive.partition_by")
        if a and duration_days(r.delete_after) <= duration_days(a.after):
            errs.append(f"{t.name}.retention.delete_after ({r.delete_after}) deve superare archive.after ({a.after})")
        if not a and r.on:
            errs += _check_age_col(t, r.on, f"{t.name}.retention.column")
    return errs


def lifecycle_children(t: Table, tables: Dict[str, "Table"]) -> List[tuple]:
    """[(tabella figlia, relazione many_to_one)] che puntano a t: un record con figli resta nella tabella hot."""
    return [(c, r) for c in tables.values() for r in c.relations if r.kind == "many_to_one" and r.target == t.name]


def age_column(t: Table) -> Optional[str]:
    if t.archive:
        return t.archive.on
    return t.retention.on if t.retention else None


def _check_sort_col(t: Table, cn: str, where: str) -> List[str]:
    c = t.col(cn)
    if not c:
        return [f"{where}: colonna {cn} inesistente"]
    if c.type not in SORTABLE_TYPES:
        return [f"{where}: {cn} è di tipo {c.type}, non ordinabile (ammessi: {', '.join(sorted(SORTABLE_TYPES))})"]
    if c.nullable:
        return [f"{where}: {cn} deve essere required per essere usata nell'ordinamento a cursore"]
    return []


def _check_access(t: Table) -> List[str]:
    errs: List[str] = []
    p = t.pagination
    for cn, _ in p.default_order:
        errs += _check_sort_col(t, cn, f"{t.name}.pagination.default_order")
    for cn in p.sortable:
        errs += _check_sort_col(t, cn, f"{t.name}.pagination.sortable")
    for q in t.queries:
        w = f"{t.name}.queries.{q.name}"
        for c in q.where:
            col = t.col(c.column)
            if not col:
                errs.append(f"{w}: colonna {c.column} inesistente")
                continue
            if c.op == "prefix" and col.type not in ("string", "text"):
                errs.append(f"{w}: prefix vale solo per colonne string/text")
            if c.op in ("is_null", "not_null") and not col.nullable:
                errs.append(f"{w}: {c.column} è obbligatoria, {c.op} non ha senso")
            if c.op in ("lt", "lte", "gt", "gte") and col.type not in SORTABLE_TYPES:
                errs.append(f"{w}: {c.op} non vale per colonne {col.type}")
            if col.type == "json":
                errs.append(f"{w}: le colonne json non si filtrano con le query dichiarate")
        for cn, _ in q.order_by:
            errs += _check_sort_col(t, cn, f"{w}.order_by")
    # nomi dei metodi univoci: query, relazioni e metodi generati condividono lo stesso spazio di nomi
    def neutral(key: str) -> str:
        kind, _, arg = key.partition(":")
        return {"list_rel": "list", "query_page": "list", "query_list": "list", "list_by": "listBy",
                "query_one": "find", "find_by": "findBy", "get_rel": "get"}.get(kind, kind) + arg
    seen: Dict[str, str] = {}
    for m in methods_of(t, dedupe=False):
        n = neutral(m.key)
        if n in seen and seen[n] != m.key:
            errs.append(f"{t.name}: {m.key} e {seen[n]} genererebbero lo stesso metodo ({n}): rinomina la query o la relazione")
        seen.setdefault(n, m.key)
    return errs


def apply_tenancy(tables: Dict[str, Table], default: str = "none", id_type: str = "uuid") -> List[str]:
    """Risolve la modalità di ogni tabella, aggiunge TenantId alle tabelle 'column', controlla le relazioni."""
    errs: List[str] = []
    if default not in TENANCY:
        return [f"configurazione: model.tenancy.default ammette {', '.join(TENANCY)}"]
    if id_type not in TENANT_ID_TYPES:
        return [f"configurazione: model.tenancy.id_type ammette {', '.join(TENANT_ID_TYPES)}"]
    for t in tables.values():
        t.tenancy = t.tenancy or default
        if t.tenancy == "column" and not any(c.tenant for c in t.columns):
            col = Column(name=TENANT_COL, type=id_type, db_name="tenant_id", required=True,
                         length=64 if id_type == "string" else None, tenant=True,
                         description="Organization proprietaria del record (impostata dal contesto del tenant)")
            pos = next(i for i, c in enumerate(t.columns) if c.primary_key) + 1
            t.columns.insert(pos, col)
    why = {"none": "i dati condivisi non possono dipendere da un tenant",
           "column": "la tabella padre non sta nello stesso database e schema",
           "schema": "la tabella padre non sta nello schema del tenant né tra i dati condivisi",
           "database": "una tabella con database per tenant può riferirsi solo ad altre tabelle con database per tenant"}
    for t in tables.values():
        for r in t.relations:
            if r.kind != "many_to_one" or r.target not in tables:
                continue
            pair = (t.tenancy, tables[r.target].tenancy)
            if pair not in TENANCY_LINKS:
                errs.append(f"{t.name}.relations.{r.name}: una tabella '{pair[0]}' non può riferirsi a {r.target} ('{pair[1]}'): {why[pair[0]]}")
    for t in tables.values():
        a = t.archive
        if a and t.tenancy != "none" and "tenant" not in a.partition_by:
            a.partition_by.insert(0, "tenant")   # implicita: l'archivio è separato per Organization
        if a and t.tenancy == "none" and "tenant" in a.partition_by:
            errs.append(f"{t.name}.archive.partition_by: tenant vale solo per le tabelle multi-tenant (tenancy: none)")
        if (t.archive or t.retention) and t.tenancy == "none":
            for c, r in lifecycle_children(t, tables):
                if c.tenancy in ("schema", "database"):
                    errs.append(f"{t.name}: archive/retention non ammessi: {c.name} ({c.tenancy}) si riferisce a {t.name} da schemi o "
                                "database di tenant, che il job non può controllare")
    return errs


def tenant_column(t: Table) -> Optional[Column]:
    return next((c for c in t.columns if c.tenant), None)


def load_schemas(schema_dir: Path, tenancy_default: str = "none", tenant_id_type: str = "uuid") -> Dict[str, Table]:
    errs: List[str] = []
    tables: Dict[str, Table] = {}
    if not schema_dir.is_dir():
        return {}
    for p in sorted(schema_dir.glob("*.yaml")) + sorted(schema_dir.glob("*.yml")):
        try:
            data = load_file(str(p))
        except (YamlError, Exception) as exc:  # PyYAML solleva i propri errori
            errs.append(f"{p.name}: YAML non valido: {exc}")
            continue
        t, e = _parse_table(p, data)
        errs += e
        if t:
            if t.name in tables:
                errs.append(f"{p.name}: tabella {t.name} già definita in {Path(tables[t.name].source).name}")
            tables[t.name] = t
    if not errs:
        errs += _cross_check(tables)
    if not errs:
        errs += apply_tenancy(tables, tenancy_default, tenant_id_type)
    if errs:
        raise SchemaError(errs)
    return dict(sorted(tables.items()))


# ------------------------------------------------------------------ API generata (nomi neutri)

@dataclass
class Method:
    key: str          # chiave neutra, es. get_by_id, find_by:PartitaIva, get_rel:Cliente
    summary: str


def methods_of(t: Table, dedupe: bool = True) -> List[Method]:
    """Elenco ordinato dei metodi generati per una tabella, identico in tutti i linguaggi."""
    ms = [
        Method("get_by_id", f"legge un record di {t.name} per chiave"),
        Method("list_page", "pagina di record con cursore e ordinamento ammesso"),
        Method("count", "numero di record"),
        Method("exists", "verifica l'esistenza per chiave"),
        Method("create", "valida e inserisce"),
        Method("update", "valida e aggiorna"),
        Method("delete", "elimina per chiave"),
    ]
    for c in t.columns:
        if c.unique and not c.primary_key:
            ms.append(Method(f"find_by:{c.name}", f"cerca per {c.name} (univoco)"))
    for ix in t.indexes:
        if ix.unique and len(ix.columns) == 1 and not t.col(ix.columns[0]).unique:
            ms.append(Method(f"find_by:{ix.columns[0]}", f"cerca per {ix.columns[0]} (univoco)"))
    for r in t.relations:
        if r.kind == "many_to_one":
            ms.append(Method(f"list_by:{r.foreign_key}", f"pagina di record con {r.foreign_key} dato"))
            ms.append(Method(f"get_rel:{r.name}", f"{r.target} collegato a un record di {t.name}"))
        else:
            ms.append(Method(f"list_rel:{r.name}", f"pagina di {r.target} collegati a un record di {t.name}"))
    for q in t.queries:
        kind = "query_one" if q.returns == "one" else ("query_list" if q.returns == "list" else "query_page")
        what = {"query_one": "primo record", "query_list": f"elenco (max {t.pagination.max_limit})", "query_page": "pagina"}[kind]
        ms.append(Method(f"{kind}:{q.name}", f"query {q.name}: {what} con {_describe(q)}"))
    if not dedupe:
        return ms
    seen, out = set(), []
    for m in ms:
        if m.key not in seen:
            seen.add(m.key)
            out.append(m)
    return out


def _describe(q: Query) -> str:
    sym = {"eq": "=", "ne": "≠", "lt": "<", "lte": "≤", "gt": ">", "gte": "≥", "in": "in", "prefix": "inizia con",
           "is_null": "è vuota", "not_null": "non è vuota"}
    parts = []
    for c in q.where:
        if c.op in ("is_null", "not_null"):
            parts.append(f"{c.column} {sym[c.op]}")
        elif c.has_value:
            parts.append(f"{c.column} {sym[c.op]} {json.dumps(c.value, ensure_ascii=False)}")
        else:
            parts.append(f"{c.column} {sym[c.op]} {c.param}")
    s = ", ".join(parts)
    if q.order_by:
        s += "; ordine " + ", ".join(f"{c}{' desc' if d else ''}" for c, d in q.order_by)
    return s


# ------------------------------------------------------------------ piano degli indici

@dataclass
class AccessPath:
    kind: str            # find_by | list_by | sort | query
    label: str
    ideal: List[str]
    covered_by: Optional[str] = None
    created: Optional[str] = None


def _covers(index_cols: List[str], eq: List[str], rest: List[str]) -> bool:
    """Un indice copre se inizia con tutte le colonne di uguaglianza (in qualunque ordine)
    e prosegue con le colonne di ordinamento/intervallo nell'ordine richiesto."""
    n = len(eq)
    if sorted(index_cols[:n]) != sorted(eq):
        return False
    return index_cols[n:n + len(rest)] == rest


def access_paths(t: Table, tables: Dict[str, "Table"]) -> List[AccessPath]:
    """Percorsi di accesso; con tenancy: column ogni percorso parte dal filtro sul tenant."""
    paths: List[AccessPath] = []
    pk = t.pk.name
    tp = [TENANT_COL] if t.tenancy == "column" else []

    def order_cols(order):
        return [c for c, _ in order if c != pk]

    for c in t.columns:
        if c.unique and not c.primary_key:
            paths.append(AccessPath("find_by", f"findBy {c.name}", tp + [c.name]))
    default = order_cols(t.order())
    for r in t.relations:
        if r.kind == "many_to_one":
            paths.append(AccessPath("list_by", f"listBy {r.foreign_key}", tp + [r.foreign_key] + default))
    # i figli di una relazione one_to_many sono letti con la FK della tabella figlia: li copre listBy di quella tabella
    if default:
        paths.append(AccessPath("sort", f"ordine predefinito ({', '.join(default)})", tp + default))
    elif tp:
        paths.append(AccessPath("sort", "ordine predefinito (chiave, per tenant)", tp + [pk]))
    for cn in t.pagination.sortable:
        if [cn] != default[:1]:
            paths.append(AccessPath("sort", f"ordinamento per {cn}", tp + [cn]))
    age = age_column(t)
    if age:
        paths.append(AccessPath("archive", f"{'archiviazione' if t.archive else 'conservazione'} per {age}", tp + [age]))
    for q in t.queries:
        eq = [c.column for c in q.where if c.op in ("eq", "is_null")]
        eq = list(dict.fromkeys(eq))
        rng = [c.column for c in q.where if c.op in ("lt", "lte", "gt", "gte", "prefix", "in")]
        ordc = order_cols(q.order_by) if q.order_by else (order_cols(t.order()) if q.returns != "one" else [])
        rest = ordc if ordc else rng[:1]
        rest = [c for c in rest if c not in eq]
        paths.append(AccessPath("query", f"query {q.name}", tp + eq + rest))
    return paths


@dataclass
class IndexSpec:
    name: str
    columns: List[str]
    unique: bool
    origin: str = "dichiarato"      # dichiarato | univoco | fk | query | ordinamento | prefisso
    pattern: List[str] = field(default_factory=list)   # colonne con operator class per LIKE 'x%' (PostgreSQL)
    ddl_only: bool = False          # solo nel DDL: gli ORM non sanno dichiarare l'operator class


@dataclass
class IndexPlan:
    specs: List[IndexSpec]
    paths: List[AccessPath]
    redundant: List[str]


def index_plan(t: Table, tables: Optional[Dict[str, "Table"]] = None) -> IndexPlan:
    """Indici dichiarati, vincoli univoci, indici creati per coprire query e ordinamenti, indici su FK."""
    specs: List[IndexSpec] = []

    def nm(prefix: str, cols: List[str]) -> str:
        return f"{prefix}_{t.db_name}_" + "_".join(t.col(c).db_name for c in cols)

    tp = [TENANT_COL] if t.tenancy == "column" else []   # univocità e indici valgono per tenant
    for ix in t.indexes:
        specs.append(IndexSpec(nm("ux" if ix.unique else "ix", tp + ix.columns), tp + list(ix.columns), ix.unique))
    for c in t.columns:
        if c.unique and not c.primary_key and not any(s.columns == tp + [c.name] for s in specs):
            specs.append(IndexSpec(nm("ux", tp + [c.name]), tp + [c.name], True, "univoco"))
    paths = access_paths(t, tables or {})
    for p in paths:
        if not p.ideal:
            continue
        eq_n = (1 if p.kind == "list_by" else 0) + len(tp)
        if p.kind == "query":
            q = next(q for q in t.queries if f"query {q.name}" == p.label)
            eq_n = len(tp) + len(list(dict.fromkeys(c.column for c in q.where if c.op in ("eq", "is_null"))))
        hit = next((s for s in specs if _covers(s.columns, p.ideal[:eq_n], p.ideal[eq_n:])), None)
        if hit is None and p.ideal == [t.pk.name]:
            continue
        if hit:
            p.covered_by = hit.name
        else:
            if p.kind == "query":
                name = f"qx_{t.db_name}_{snake(p.label.split(' ', 1)[1])}"
                origin = "query"
            elif p.kind == "list_by":
                name, origin = nm("ix", p.ideal), "fk"
            elif p.kind == "archive":
                name, origin = nm("ix", p.ideal), "archivio"
            else:
                name, origin = nm("ix", p.ideal), "ordinamento"
            spec = IndexSpec(name, list(p.ideal), False, origin)
            specs.append(spec)
            p.created = name
    # LIKE 'prefisso%': con collation diversa da C PostgreSQL usa solo un indice con varchar/text_pattern_ops
    for q in t.queries:
        pref = [c.column for c in q.where if c.op == "prefix"]
        if not pref:
            continue
        eq = tp + list(dict.fromkeys(c.column for c in q.where if c.op in ("eq", "is_null")))
        cols = eq + [pref[0]]
        name = f"px_{t.db_name}_{snake(q.name)}"
        specs.append(IndexSpec(name, cols, False, "prefisso", pattern=[pref[0]], ddl_only=True))
        paths.append(AccessPath("query", f"query {q.name} (LIKE prefisso, PostgreSQL)", cols, created=name))
    redundant = []
    for a in specs:
        if a.unique or a.ddl_only:
            continue
        for b in specs:
            if a is not b and len(b.columns) > len(a.columns) and b.columns[:len(a.columns)] == a.columns:
                redundant.append(f"{a.name} è un prefisso di {b.name}: probabilmente superfluo")
                break
    return IndexPlan(specs, paths, redundant)


def index_specs(t: Table) -> List[IndexSpec]:
    """Indici da dichiarare negli ORM (gli indici solo-DDL restano nel DDL generato)."""
    return [s for s in index_plan(t).specs if not s.ddl_only]
