"""Caricamento e validazione degli schemi tabella (schemas/db/<Tabella>.yaml)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from miniyaml import YamlError, load_file

TYPES = {"uuid", "string", "text", "int", "bigint", "decimal", "bool", "date", "datetime", "json"}
KINDS = {"many_to_one", "one_to_many"}
ON_DELETE = {"restrict", "cascade", "set_null"}
GENERATED = {"on_create", "on_update"}
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
class Table:
    name: str
    db_name: str
    description: str
    columns: List[Column]
    relations: List[Relation] = field(default_factory=list)
    indexes: List[Index] = field(default_factory=list)
    source: str = ""

    @property
    def pk(self) -> Column:
        return next(c for c in self.columns if c.primary_key)

    def col(self, name: str) -> Optional[Column]:
        return next((c for c in self.columns if c.name == name), None)

    def fk_columns(self) -> List[str]:
        return [r.foreign_key for r in self.relations if r.kind == "many_to_one"]


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
    allowed = {"table", "db_name", "description", "columns", "relations", "indexes"}
    for k in data:
        if k not in allowed:
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

    t = Table(name=name, db_name=data.get("db_name") or snake(name), description=str(data.get("description") or ""),
              columns=cols, relations=rels, indexes=idx, source=str(path))
    return t, errs


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
    return errs


def load_schemas(schema_dir: Path) -> Dict[str, Table]:
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
    if errs:
        raise SchemaError(errs)
    return dict(sorted(tables.items()))


# ------------------------------------------------------------------ indici (stessi nomi in tutti i linguaggi)

@dataclass
class IndexSpec:
    name: str
    columns: List[str]
    unique: bool


def index_specs(t: Table) -> List[IndexSpec]:
    """Indici dichiarati, vincoli univoci di colonna e indici sulle FK, con nomi deterministici."""
    out: List[IndexSpec] = []

    def nm(prefix: str, cols: List[str]) -> str:
        return f"{prefix}_{t.db_name}_" + "_".join(t.col(c).db_name for c in cols)

    for ix in t.indexes:
        out.append(IndexSpec(nm("ux" if ix.unique else "ix", ix.columns), list(ix.columns), ix.unique))
    for c in t.columns:
        if c.unique and not c.primary_key and not any(s.columns == [c.name] for s in out):
            out.append(IndexSpec(nm("ux", [c.name]), [c.name], True))
    for fk in t.fk_columns():
        if not any(s.columns[0] == fk for s in out):
            out.append(IndexSpec(nm("ix", [fk]), [fk], False))
    return out


# ------------------------------------------------------------------ API generata (nomi neutri)

@dataclass
class Method:
    key: str          # chiave neutra, es. get_by_id, find_by:PartitaIva, get_rel:Cliente
    summary: str


def methods_of(t: Table) -> List[Method]:
    """Elenco ordinato dei metodi generati per una tabella, identico in tutti i linguaggi."""
    ms = [
        Method("get_by_id", f"legge un record di {t.name} per chiave"),
        Method("list", "pagina di record ordinati per chiave"),
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
            ms.append(Method(f"list_by:{r.foreign_key}", f"record con {r.foreign_key} dato"))
            ms.append(Method(f"get_rel:{r.name}", f"{r.target} collegato a un record di {t.name}"))
        else:
            ms.append(Method(f"list_rel:{r.name}", f"{r.target} collegati a un record di {t.name}"))
    seen, out = set(), []
    for m in ms:
        if m.key not in seen:
            seen.add(m.key)
            out.append(m)
    return out
