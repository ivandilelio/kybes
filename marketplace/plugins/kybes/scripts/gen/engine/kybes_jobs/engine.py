"""Esecuzione di un job: per ogni unità (tabella, o tabella di un tenant) recupero, archiviazione, conservazione."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from . import codec
from .config import JobConfig, JobError, partition_end, subtract
from .storage import Storage, open_storage

RUNS_TABLE = "kybes_archive_runs"
_NAME = re.compile(r"^[a-z0-9_]{1,48}$")

_runs_meta = sa.MetaData()
RUNS = sa.Table(
    RUNS_TABLE, _runs_meta,
    sa.Column("run_id", sa.String(64), primary_key=True),
    sa.Column("table_name", sa.String(128), nullable=False),
    sa.Column("tenant", sa.String(256)),
    sa.Column("rows", sa.Integer, nullable=False),
    sa.Column("files", sa.Integer, nullable=False),
    sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
)


def create_support_tables(engine: Engine) -> None:
    """Crea kybes_archive_runs (in produzione è nel DDL generato: db/generated/ddl/postgres/_all.sql)."""
    _runs_meta.create_all(engine)


def _sa_type(c) -> Any:
    return {"uuid": sa.Uuid(), "string": sa.String(c.length), "text": sa.Text(), "int": sa.Integer(), "bigint": sa.BigInteger(),
            "decimal": sa.Numeric(c.precision, c.scale), "bool": sa.Boolean(), "date": sa.Date(),
            "datetime": sa.DateTime(timezone=True), "json": sa.JSON()}[c.type]


def table_for(cfg: JobConfig, schema: Optional[str] = None, metadata: Optional[sa.MetaData] = None) -> sa.Table:
    md = metadata if metadata is not None else sa.MetaData()
    return sa.Table(cfg.db_name, md, *[sa.Column(c.db_name, _sa_type(c), primary_key=c.name == cfg.key, nullable=c.nullable)
                                       for c in cfg.columns], schema=schema)


def tenant_key(cfg: JobConfig, tenant: Any) -> str:
    """Come tenant_key dei modelli generati: nome sicuro per schema e database del tenant."""
    key = str(tenant).lower().replace("-", "_")
    if not _NAME.match(key):
        raise JobError(f"tenant {tenant!r} non utilizzabile come nome di schema o database")
    return key


def coerce_tenant(cfg: JobConfig, value: Any) -> Any:
    if cfg.tenant_id_type == "uuid":
        try:
            return uuid.UUID(str(value))
        except ValueError:
            raise JobError(f"tenant non valido: {value!r} non è un UUID") from None
    text = str(value)
    if not text or len(text) > 64:
        raise JobError(f"tenant non valido: {value!r} (da 1 a 64 caratteri)")
    return text


def lock_id(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big", signed=True)


class Ops:
    """Operazioni che dipendono dal database: PostgreSQL ha lock consultivi, tenant per la RLS e il controllo del ruolo."""

    def __init__(self, conn: Connection) -> None:
        self.pg = conn.dialect.name == "postgresql"

    def try_lock(self, conn: Connection, name: str) -> bool:
        if not self.pg:
            return True
        return bool(conn.execute(sa.text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_id(name)}).scalar())

    def unlock(self, conn: Connection, name: str) -> None:
        if self.pg:
            conn.execute(sa.text("SELECT pg_advisory_unlock(:k)"), {"k": lock_id(name)})

    def set_tenant(self, conn: Connection, tenant: Any) -> None:
        """app.tenant_id per la transazione, come la Unit of Work dei modelli (policy di row-level security)."""
        if self.pg and tenant is not None:
            conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})

    def check_rls(self, conn: Connection, table: str) -> None:
        """Con la RLS attiva il job deve vedere le righe di tutti i tenant: ruolo con BYPASSRLS (o proprietario senza FORCE)."""
        if not self.pg:
            return
        row = conn.execute(sa.text(
            "SELECT c.relrowsecurity, c.relforcerowsecurity, r.rolbypassrls OR r.rolsuper, pg_get_userbyid(c.relowner) = current_user "
            "FROM pg_class c JOIN pg_roles r ON r.rolname = current_user WHERE c.oid = to_regclass(:t)"), {"t": table}).first()
        if row is None:
            raise JobError(f"tabella {table} inesistente")
        rls, force, bypass, owner = row
        if rls and not bypass and (force or not owner):
            raise JobError(f"{table}: la row-level security nasconde al job le righe dei tenant; "
                           "esegui il job con un ruolo dedicato con BYPASSRLS (vedi docs/archivio.md)")


@dataclass
class Unit:
    """Una tabella da elaborare: con tenancy column uno per tenant, con schema e database uno per schema o database."""
    tenant: Any = None
    segment: Optional[str] = None
    schema: Optional[str] = None
    engine: Optional[Engine] = None

    @property
    def label(self) -> str:
        return self.segment or "-"


@dataclass
class Report:
    archived_rows: int = 0
    archived_files: int = 0
    recovered_runs: int = 0
    discarded_runs: int = 0
    deleted_rows: int = 0
    deleted_files: int = 0
    skipped_units: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class Job:
    def __init__(self, cfg: JobConfig, engine: Optional[Engine], *, database_url: Optional[str] = None,
                 archive_url: Optional[str] = None, tenants: Optional[List[str]] = None, now: Optional[datetime] = None,
                 storage_factory: Callable[[str, Optional[str]], Storage] = open_storage,
                 engine_factory: Callable[[str], Engine] = sa.create_engine, log: Callable[[Dict[str, Any]], None] = None) -> None:
        self.cfg = cfg
        self.engine = engine
        self.database_url = database_url
        self.location = archive_url or cfg.location
        self.tenants = tenants
        self.now = now or datetime.now(timezone.utc)
        self.storage_factory = storage_factory
        self.engine_factory = engine_factory
        self.log = log or (lambda event: print(json.dumps(event, default=str), flush=True))
        self._tables: Dict[Optional[str], sa.Table] = {}
        if cfg.archives and not self.location:
            raise JobError(f"{cfg.table}: archivio senza location (config.json o KYBES_ARCHIVE_URL)")
        if cfg.tenancy == "database" and (not database_url or "{tenant}" not in database_url):
            raise JobError(f"{cfg.table}: tenancy database: KYBES_DATABASE_URL deve contenere {{tenant}}")
        if cfg.tenancy != "database" and engine is None:
            raise JobError(f"{cfg.table}: manca il database (KYBES_DATABASE_URL)")

    # ---------------------------------------------------------------- unità

    def table(self, schema: Optional[str]) -> sa.Table:
        if schema not in self._tables:
            self._tables[schema] = table_for(self.cfg, schema)
        return self._tables[schema]

    def _unit(self, tenant: Any) -> Unit:
        cfg = self.cfg
        if tenant is None:
            return Unit(engine=self.engine)
        seg = codec.segment(tenant)
        if cfg.tenancy == "schema":
            return Unit(tenant, seg, "tenant_" + tenant_key(cfg, tenant), self.engine)
        if cfg.tenancy == "database":
            return Unit(tenant, seg, None, self.engine_factory(self.database_url.replace("{tenant}", tenant_key(cfg, tenant))))
        return Unit(tenant, seg, None, self.engine)

    def units(self) -> List[Unit]:
        cfg = self.cfg
        if cfg.tenancy == "none":
            return [self._unit(None)]
        if self.tenants is not None:
            found = {coerce_tenant(cfg, t) for t in self.tenants}
        elif cfg.tenancy == "column":
            found = self._column_tenants()
        elif cfg.tenancy == "schema" and cfg.tenant_id_type == "uuid":
            found = set()
            for name in sa.inspect(self.engine).get_schema_names():
                try:
                    if name.startswith("tenant_"):
                        found.add(coerce_tenant(cfg, name[len("tenant_"):].replace("_", "-")))
                except JobError:
                    continue  # schema tenant_* che non deriva da un tenant uuid: non è di questo progetto
        else:
            raise JobError(f"{cfg.table}: tenancy {cfg.tenancy}: indica i tenant in KYBES_TENANTS (separati da virgola)")
        return [self._unit(t) for t in sorted(found, key=str)]

    def _column_tenants(self) -> set:
        """Tenant con righe nella tabella e, se l'archivio non è separato per tenant, con file nell'archivio."""
        cfg = self.cfg
        t = self.table(None)
        tc = t.c[cfg.col(cfg.tenant_column).db_name]
        with self.engine.connect() as conn:
            Ops(conn).check_rls(conn, cfg.db_name)
            found = set(conn.execute(sa.select(tc).distinct()).scalars())
        if cfg.archives and "{tenant}" not in self.location:
            for path in self.storage_factory(self.location, None).list(cfg.db_name + "/tenant="):
                seg = path.split("/")[1][len("tenant="):]
                found.add(coerce_tenant(cfg, codec.unsegment(seg)))
        return found

    # ---------------------------------------------------------------- esecuzione

    def run(self) -> Report:
        rep = Report()
        for unit in self.units():
            with unit.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock_conn:
                ops = Ops(lock_conn)
                name = f"kybes:{self.cfg.db_name}:{unit.schema or ''}:{unit.label}"
                if not ops.try_lock(lock_conn, name):
                    rep.skipped_units.append(unit.label)
                    self.log({"event": "locked", "table": self.cfg.table, "tenant": unit.label})
                    continue
                try:
                    self._run_unit(unit, rep)
                finally:
                    ops.unlock(lock_conn, name)
        self.log({"event": "done", "table": self.cfg.table, **rep.as_dict()})
        return rep

    def _run_unit(self, unit: Unit, rep: Report) -> None:
        cfg = self.cfg
        if cfg.archives:
            storage = self.storage_factory(self.location, unit.segment)
            self.recover(unit, storage, rep)
            cutoff = subtract(self.now, cfg.after)
            while True:
                n = self._archive_batch(unit, storage, cutoff, rep)
                if n < cfg.batch_size:
                    break
            if cfg.delete_after:
                self._purge_archive(unit, storage, subtract(self.now, cfg.delete_after), rep)
        else:
            cutoff = subtract(self.now, cfg.delete_after)
            while True:
                n = self._delete_batch(unit, cutoff, rep)
                if n < cfg.batch_size:
                    break

    def _cutoff_value(self, cutoff: datetime) -> Any:
        return cutoff.date() if self.cfg.col(self.cfg.age_column).type == "date" else cutoff

    def _eligible(self, t: sa.Table, unit: Unit, cutoff: datetime, children: List) -> List[Any]:
        cfg = self.cfg
        age = t.c[cfg.col(cfg.age_column).db_name]
        key = t.c[cfg.col(cfg.key).db_name]
        cond = [age < self._cutoff_value(cutoff)]
        if cfg.tenancy == "column":
            cond.append(t.c[cfg.col(cfg.tenant_column).db_name] == unit.tenant)
        for ch in children:
            child = sa.table(ch.table, sa.column(ch.column), schema=unit.schema)
            cond.append(~sa.exists().where(child.c[ch.column] == key))
        return cond

    # ---------------------------------------------------------------- archiviazione

    def _paths(self, unit: Unit, run: str) -> str:
        return f"{self.cfg.db_name}/_staging/{unit.segment or '_'}/{run}/"

    def _key_path(self, unit: Unit, key: str) -> str:
        tenant = f"tenant={unit.segment}/" if unit.segment else ""
        return f"{self.cfg.db_name}/_keys/{tenant}{codec.segment(key)}.json"

    def _archive_batch(self, unit: Unit, storage: Storage, cutoff: datetime, rep: Report) -> int:
        cfg = self.cfg
        t = self.table(unit.schema)
        key = t.c[cfg.col(cfg.key).db_name]
        age = t.c[cfg.col(cfg.age_column).db_name]
        run = self.now.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
        with unit.engine.connect() as conn:
            tx = conn.begin()
            try:
                Ops(conn).set_tenant(conn, unit.tenant)
                stmt = (sa.select(t).where(*self._eligible(t, unit, cutoff, cfg.children)).order_by(age, key)
                        .limit(cfg.batch_size).with_for_update(skip_locked=True, of=t))
                rows = [dict(r) for r in conn.execute(stmt).mappings()]
                if not rows:
                    tx.rollback()
                    return 0
                files = self._stage(unit, storage, run, rows)
                keys = [r[key.name] for r in rows]
                deleted = self._delete_rows(conn, t, key, keys)
                if deleted != len(rows):
                    raise JobError(f"{cfg.table}: cancellate {deleted} righe invece di {len(rows)}")
                conn.execute(sa.insert(RUNS).values(run_id=run, table_name=cfg.db_name, tenant=unit.segment, rows=len(rows),
                                                    files=len(files), committed_at=self.now))
                tx.commit()
            except BaseException:
                tx.rollback()
                self._discard(storage, unit, run)
                raise
        self._promote(unit, storage, run)
        rep.archived_rows += len(rows)
        rep.archived_files += sum(1 for f in files if f["path"].endswith(".parquet"))
        self.log({"event": "archived", "table": cfg.table, "tenant": unit.label, "run": run, "rows": len(rows)})
        return len(rows)

    def _delete_rows(self, conn: Connection, t: sa.Table, key: Any, keys: List[Any]) -> int:
        return conn.execute(sa.delete(t).where(key.in_(keys))).rowcount

    def _put_verified(self, storage: Storage, path: str, data: bytes, keys: Optional[List[str]] = None) -> str:
        """Scrive, rilegge e confronta SHA-256; per i Parquet anche righe e chiavi."""
        digest = codec.sha256(data)
        storage.put(path, data)
        back = storage.get(path)
        if back is None or codec.sha256(back) != digest:
            raise JobError(f"verifica fallita per {path}: il contenuto riletto è diverso da quello scritto")
        if keys is not None:
            n, got = codec.parquet_keys(self.cfg, back)
            if n != len(keys) or sorted(got) != sorted(keys):
                raise JobError(f"verifica fallita per {path}: righe o chiavi diverse da quelle archiviate")
        return digest

    def _stage(self, unit: Unit, storage: Storage, run: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cfg = self.cfg
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            groups[codec.partition_path(cfg, unit.segment, r)].append(r)
        staging = self._paths(unit, run)
        files = []
        for part in sorted(groups):
            part_rows = groups[part]
            rel = f"{cfg.db_name}/{part}part-{run}.parquet"
            keys = [codec.key_text(cfg, r) for r in part_rows]
            digest = self._put_verified(storage, staging + rel, codec.to_parquet(cfg, part_rows), keys)
            files.append({"path": rel, "sha256": digest, "rows": len(part_rows)})
        if cfg.read_through:
            for r in rows:
                rel = self._key_path(unit, codec.key_text(cfg, r))
                files.append({"path": rel, "sha256": self._put_verified(storage, staging + rel, codec.key_object(cfg, r))})
        manifest = {"run": run, "table": cfg.table, "tenant": unit.segment, "rows": len(rows), "files": files}
        storage.put(staging + "manifest.json", json.dumps(manifest, indent=1).encode("utf-8"))
        return files

    def _discard(self, storage: Storage, unit: Unit, run: str) -> None:
        for path in storage.list(self._paths(unit, run)):
            storage.delete(path)

    def _promote(self, unit: Unit, storage: Storage, run: str) -> None:
        """Dopo il commit: i file passano dallo staging alla posizione definitiva, verificati con lo SHA-256 del manifest."""
        staging = self._paths(unit, run)
        raw = storage.get(staging + "manifest.json")
        if raw is None:
            raise JobError(f"{self.cfg.table}: passaggio {run} confermato ma senza manifest: verifica lo staging a mano")
        manifest = json.loads(raw)
        for f in manifest["files"]:
            data = storage.get(staging + f["path"])
            if data is None:  # già promosso da un tentativo precedente
                final = storage.get(f["path"])
                if final is None or codec.sha256(final) != f["sha256"]:
                    raise JobError(f"{self.cfg.table}: {f['path']} manca sia nello staging sia nell'archivio")
                continue
            if codec.sha256(data) != f["sha256"]:
                raise JobError(f"{self.cfg.table}: {staging}{f['path']} non corrisponde al manifest")
            self._put_verified(storage, f["path"], data)
            storage.delete(staging + f["path"])
        storage.delete(staging + "manifest.json")
        with unit.engine.begin() as conn:
            conn.execute(sa.delete(RUNS).where(RUNS.c.run_id == run))

    def recover(self, unit: Unit, storage: Storage, rep: Report) -> None:
        """Staging lasciato da un job interrotto: promosso se il passaggio è confermato, altrimenti scartato."""
        root = f"{self.cfg.db_name}/_staging/{unit.segment or '_'}/"
        runs = sorted({p[len(root):].split("/", 1)[0] for p in storage.list(root)})
        for run in runs:
            with unit.engine.connect() as conn:
                committed = conn.execute(sa.select(RUNS.c.run_id).where(RUNS.c.run_id == run)).first() is not None
            if committed:
                self._promote(unit, storage, run)
                rep.recovered_runs += 1
            else:
                self._discard(storage, unit, run)
                rep.discarded_runs += 1
            self.log({"event": "recovered" if committed else "discarded", "table": self.cfg.table, "tenant": unit.label, "run": run})

    # ---------------------------------------------------------------- conservazione

    def _purge_archive(self, unit: Unit, storage: Storage, cutoff: datetime, rep: Report) -> None:
        """Cancella le partizioni dell'archivio finite prima del limite di conservazione (e i loro oggetti per chiave)."""
        cfg = self.cfg
        prefix = f"{cfg.db_name}/" + (f"tenant={unit.segment}/" if "tenant" in cfg.partition_by else "")
        limit = cutoff.date()
        for path in storage.list(prefix):
            if not path.endswith(".parquet") or any(s.startswith("_") for s in path.split("/")[1:]):
                continue
            end = partition_end(codec.parse_partitions(path))
            if end is None or end > limit:
                continue
            if cfg.read_through:
                data = storage.get(path)
                for key in codec.parquet_keys(cfg, data)[1] if data is not None else []:
                    storage.delete(self._key_path(unit, key))
            storage.delete(path)
            rep.deleted_files += 1
            self.log({"event": "purged", "table": cfg.table, "tenant": unit.label, "path": path})

    def _delete_batch(self, unit: Unit, cutoff: datetime, rep: Report) -> int:
        """Conservazione senza archivio: cancella dalla tabella hot. I figli restrict trattengono il record;
        cascade e set_null seguono la regola dichiarata sulla relazione."""
        cfg = self.cfg
        t = self.table(unit.schema)
        key = t.c[cfg.col(cfg.key).db_name]
        age = t.c[cfg.col(cfg.age_column).db_name]
        restrict = [c for c in cfg.children if c.on_delete == "restrict"]
        with unit.engine.begin() as conn:
            Ops(conn).set_tenant(conn, unit.tenant)
            keys = list(conn.execute(sa.select(key).where(*self._eligible(t, unit, cutoff, restrict)).order_by(age, key)
                                     .limit(cfg.batch_size).with_for_update(skip_locked=True, of=t)).scalars())
            if keys:
                conn.execute(sa.delete(t).where(key.in_(keys)))
        rep.deleted_rows += len(keys)
        if keys:
            self.log({"event": "deleted", "table": cfg.table, "tenant": unit.label, "rows": len(keys)})
        return len(keys)


def database_url(url: str) -> str:
    """postgresql://... (formato comune del kit) → driver psycopg di SQLAlchemy."""
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.split("://", 1)[1]
    return url


def job_from_env(cfg: JobConfig, env: Optional[Dict[str, str]] = None, **kw: Any) -> Job:
    env = dict(os.environ if env is None else env)
    url = env.get("KYBES_DATABASE_URL")
    if not url:
        raise JobError("imposta KYBES_DATABASE_URL")
    url = database_url(url)
    tenants = [x.strip() for x in env["KYBES_TENANTS"].split(",") if x.strip()] if env.get("KYBES_TENANTS") else None
    engine = None if cfg.tenancy == "database" else kw.get("engine_factory", sa.create_engine)(url)
    return Job(cfg, engine, database_url=url, archive_url=env.get("KYBES_ARCHIVE_URL") or None, tenants=tenants, **kw)
