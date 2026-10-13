"""Configurazione di un job (config.json generato dallo schema della tabella) e calcolo delle età."""
from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

DURATION = re.compile(r"^([1-9][0-9]{0,4})([dmy])$")
PARTITIONS = ("tenant", "year", "month", "day")


class JobError(RuntimeError):
    """Errore che ferma il job; il messaggio dice cosa correggere."""


@dataclass
class ColumnSpec:
    name: str
    db_name: str
    type: str
    nullable: bool = True
    length: Optional[int] = None
    precision: int = 18
    scale: int = 2


@dataclass
class Child:
    table: str
    column: str
    on_delete: str = "restrict"


@dataclass
class JobConfig:
    table: str
    db_name: str
    key: str
    columns: List[ColumnSpec]
    age_column: str
    tenancy: str = "none"
    tenant_id_type: str = "uuid"
    tenant_column: Optional[str] = None
    after: Optional[str] = None
    target: Optional[str] = None
    location: Optional[str] = None
    partition_by: List[str] = field(default_factory=list)
    read_through: bool = False
    delete_after: Optional[str] = None
    children: List[Child] = field(default_factory=list)
    mode: str = "cron"
    interval: int = 300
    batch_size: int = 1000

    @property
    def archives(self) -> bool:
        return self.after is not None

    def col(self, name: str) -> ColumnSpec:
        for c in self.columns:
            if c.name == name:
                return c
        raise JobError(f"{self.table}: colonna {name} assente dalla configurazione")


def from_dict(d: Dict[str, Any]) -> JobConfig:
    try:
        arch = d.get("archive") or {}
        ret = d.get("retention") or {}
        job = d.get("job") or {}
        cfg = JobConfig(
            table=d["table"], db_name=d["db_name"], key=d["key"], age_column=d["age_column"],
            columns=[ColumnSpec(**c) for c in d["columns"]],
            tenancy=d.get("tenancy", "none"), tenant_id_type=d.get("tenant_id_type", "uuid"),
            tenant_column=d.get("tenant_column"),
            after=arch.get("after"), target=arch.get("target"), location=arch.get("location"),
            partition_by=list(arch.get("partition_by") or []), read_through=bool(arch.get("read_through")),
            delete_after=ret.get("delete_after"),
            children=[Child(**c) for c in d.get("children") or []],
            mode=job.get("mode", "cron"), interval=int(job.get("interval", 300)), batch_size=int(job.get("batch_size", 1000)))
    except (KeyError, TypeError) as exc:
        raise JobError(f"configurazione del job non valida: {exc}") from None
    for dur in (cfg.after, cfg.delete_after):
        if dur is not None and not DURATION.match(dur):
            raise JobError(f"{cfg.table}: durata non valida {dur!r}")
    if cfg.after is None and cfg.delete_after is None:
        raise JobError(f"{cfg.table}: la configurazione non ha né archive né retention")
    if cfg.tenancy not in ("none", "column", "schema", "database"):
        raise JobError(f"{cfg.table}: tenancy {cfg.tenancy!r} non valida")
    if any(p not in PARTITIONS for p in cfg.partition_by):
        raise JobError(f"{cfg.table}: partition_by ammette {', '.join(PARTITIONS)}")
    for name in (cfg.key, cfg.age_column) + ((cfg.tenant_column,) if cfg.tenant_column else ()):
        cfg.col(name)
    return cfg


def load_config(path: str) -> JobConfig:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JobError(f"configurazione del job illeggibile ({path}): {exc}") from None
    return from_dict(data)


def subtract(now: datetime, duration: str) -> datetime:
    """now meno la durata: i giorni sono esatti, mesi e anni seguono il calendario (31 marzo - 1m = 28/29 febbraio)."""
    m = DURATION.match(duration)
    if not m:
        raise JobError(f"durata non valida {duration!r}")
    n, unit = int(m.group(1)), m.group(2)
    if unit == "d":
        return now - timedelta(days=n)
    months = n * (12 if unit == "y" else 1)
    year, month0 = divmod(now.year * 12 + now.month - 1 - months, 12)
    month = month0 + 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    return now.replace(year=year, month=month, day=day)


def partition_end(parts: Dict[str, int]) -> Optional[date]:
    """Primo giorno dopo la partizione (year, month, day); None se la partizione non ha l'anno."""
    if "year" not in parts:
        return None
    y = parts["year"]
    if "month" not in parts:
        return date(y + 1, 1, 1)
    mth = parts["month"]
    if "day" not in parts:
        return date(y + (mth == 12), mth % 12 + 1, 1)
    return date(y, mth, parts["day"]) + timedelta(days=1)
