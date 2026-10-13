"""Piano MongoDB di una tabella con storage: mongo, comune ai quattro linguaggi.

Convenzioni dei documenti:
- collection = db_name della tabella; la chiave primaria è _id, le altre colonne usano il loro db_name;
- uuid come stringa in minuscolo, decimal come Decimal128, bigint come int64, date come Date a mezzanotte UTC,
  datetime come Date (millisecondi), json come valore BSON; una colonna vuota non compare nel documento;
- le chiavi intere generate vengono dalla collection kybes_counters ({_id: collection, seq});
- gli indici hanno gli stessi nomi del DDL SQL; un indice univoco su colonne facoltative vale solo per i documenti
  che le hanno (partialFilterExpression); retention diventa un indice TTL sulla colonna dell'età.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from schema import Column, Table, duration_days, index_plan, lifecycle_children

COUNTERS = "kybes_counters"


def field_name(t: Table, c: Column) -> str:
    return "_id" if c.primary_key else c.db_name


@dataclass
class MongoIndex:
    name: str
    fields: List[str]
    unique: bool = False
    partial: List[str] = field(default_factory=list)   # campi facoltativi: indice solo dove esistono
    ttl: Optional[int] = None                           # secondi (retention)


def indexes(t: Table) -> List[MongoIndex]:
    out: List[MongoIndex] = []
    seen = set()
    for s in index_plan(t).specs:
        cols = [t.col(c) for c in s.columns]
        key = tuple(field_name(t, c) for c in cols)
        if key in seen:
            continue  # il prefisso per LIKE (solo DDL) usa lo stesso indice in MongoDB
        seen.add(key)
        out.append(MongoIndex(s.name, list(key), s.unique, [field_name(t, c) for c in cols if c.nullable] if s.unique else []))
    if t.retention:
        age = t.col(t.retention.on)
        secs = duration_days(t.retention.delete_after) * 86400
        single = next((ix for ix in out if ix.fields == [field_name(t, age)] and not ix.unique), None)
        if single:
            single.ttl = secs
        else:
            out.append(MongoIndex(f"ttl_{t.db_name}_{age.db_name}", [field_name(t, age)], ttl=secs))
    return out


def children(t: Table, tables: Dict[str, Table]) -> List[Tuple[Table, object]]:
    """Relazioni many_to_one di altre collection (o della stessa) che puntano a t."""
    return [(c, r) for c, r in lifecycle_children(t, tables) if c.mongo]


def child_label(t: Table, child: Table, rel) -> str:
    """Nome usato nell'errore di cancellazione: la relazione one_to_many di t, se dichiarata, altrimenti la tabella figlia."""
    inv = next((x.name for x in t.relations if x.kind == "one_to_many" and x.target == child.name and x.foreign_key == rel.foreign_key), None)
    return inv or child.name
