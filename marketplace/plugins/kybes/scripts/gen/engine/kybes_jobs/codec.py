"""Formati dell'archivio: Parquet per i dati, JSON per gli oggetti per chiave letti dal read-through.

Oggetto per chiave (read_through): {"<Colonna>": valore} con i nomi dello schema e questi formati:
uuid in minuscolo, decimal e bigint come stringa (nessuna perdita di precisione in JavaScript), date "AAAA-MM-GG",
datetime ISO 8601 in UTC con microsecondi ("2024-03-01T10:20:30.123456+00:00"), json come valore JSON,
string, text, int e bool come in JSON.
Il generatore decodifica lo stesso formato in Python, TypeScript, Java e C#.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .config import ColumnSpec, JobConfig, JobError

_SAFE = re.compile(r"[A-Za-z0-9_-]")


def segment(value: Any) -> str:
    """Valore sicuro in un percorso: lettere, cifre, _ e - restano, il resto diventa %XX (UTF-8)."""
    return "".join(ch if _SAFE.fullmatch(ch) else "".join(f"%{b:02X}" for b in ch.encode("utf-8")) for ch in str(value))


def unsegment(text: str) -> str:
    from urllib.parse import unquote
    return unquote(text)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc(value: datetime) -> datetime:
    """Le colonne datetime sono timestamptz: un valore senza fuso (SQLite) è in UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def json_value(col: ColumnSpec, v: Any) -> Any:
    if v is None:
        return None
    t = col.type
    if t == "uuid":
        return str(v if isinstance(v, uuid.UUID) else uuid.UUID(str(v)))
    if t == "decimal":
        return str(Decimal(v).quantize(Decimal(1).scaleb(-col.scale)))
    if t == "date":
        return v.isoformat()
    if t == "datetime":
        return utc(v).isoformat(timespec="microseconds")
    if t == "bool":
        return bool(v)
    if t == "bigint":
        return str(int(v))
    return v


def key_text(cfg: JobConfig, row: Mapping[str, Any]) -> str:
    """La chiave come testo: è il nome dell'oggetto per chiave e il valore confrontato nella verifica dei file."""
    return str(json_value(cfg.col(cfg.key), row[cfg.col(cfg.key).db_name]))


def key_object(cfg: JobConfig, row: Mapping[str, Any]) -> bytes:
    doc = {c.name: json_value(c, row[c.db_name]) for c in cfg.columns}
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def arrow_schema(cfg: JobConfig):
    import pyarrow as pa
    types = {"uuid": pa.string(), "string": pa.string(), "text": pa.string(), "int": pa.int32(), "bigint": pa.int64(),
             "bool": pa.bool_(), "date": pa.date32(), "datetime": pa.timestamp("us", tz="UTC"), "json": pa.string()}

    def typ(c: ColumnSpec):
        return pa.decimal128(c.precision, c.scale) if c.type == "decimal" else types[c.type]
    return pa.schema([pa.field(c.db_name, typ(c), nullable=c.nullable) for c in cfg.columns],
                     metadata={"kybes.table": cfg.table, "kybes.key": cfg.col(cfg.key).db_name})


def _arrow_value(col: ColumnSpec, v: Any) -> Any:
    if v is None:
        return None
    if col.type == "json":
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    if col.type == "decimal":
        return Decimal(v).quantize(Decimal(1).scaleb(-col.scale))
    if col.type == "datetime":
        return utc(v)
    if col.type == "uuid":
        return json_value(col, v)
    return v


def to_parquet(cfg: JobConfig, rows: Iterable[Mapping[str, Any]]) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows = list(rows)
    schema = arrow_schema(cfg)
    data = {c.db_name: [_arrow_value(c, r[c.db_name]) for r in rows] for c in cfg.columns}
    table = pa.Table.from_pydict(data, schema=schema)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


def parquet_keys(cfg: JobConfig, data: bytes) -> Tuple[int, List[str]]:
    """Righe e chiavi (come testo) di un file Parquet dell'archivio."""
    import pyarrow.parquet as pq
    try:
        table = pq.read_table(io.BytesIO(data), columns=[cfg.col(cfg.key).db_name])
    except Exception as exc:  # noqa: BLE001 - pyarrow solleva ArrowInvalid e altri
        raise JobError(f"file Parquet illeggibile: {exc}") from None
    keys = [str(v) for v in table.column(0).to_pylist()]
    return table.num_rows, keys


def partition_values(cfg: JobConfig, row: Mapping[str, Any]) -> Dict[str, int]:
    v = row[cfg.col(cfg.age_column).db_name]
    d = utc(v).date() if isinstance(v, datetime) else v
    if not isinstance(d, date):
        raise JobError(f"{cfg.table}: {cfg.age_column} vuota, il record non è archiviabile")
    return {"year": d.year, "month": d.month, "day": d.day}


def partition_path(cfg: JobConfig, tenant_seg: Any, row: Mapping[str, Any]) -> str:
    vals = partition_values(cfg, row)
    out = []
    for p in cfg.partition_by:
        if p == "tenant":
            out.append(f"tenant={tenant_seg}")
        else:
            out.append(f"{p}={vals[p]:04d}" if p == "year" else f"{p}={vals[p]:02d}")
    return "".join(x + "/" for x in out)


def parse_partitions(path: str) -> Dict[str, int]:
    parts: Dict[str, int] = {}
    for seg in path.split("/")[:-1]:
        name, eq, val = seg.partition("=")
        if eq and name in ("year", "month", "day") and val.isdigit():
            parts[name] = int(val)
    return parts
