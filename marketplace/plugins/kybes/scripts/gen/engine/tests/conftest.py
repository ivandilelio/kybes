"""Fixture dei test del motore dei job: database (PostgreSQL con KYBES_TEST_DATABASE_URL, altrimenti SQLite) e archivio su file."""
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kybes_jobs import codec  # noqa: E402
from kybes_jobs.config import from_dict, subtract  # noqa: E402
from kybes_jobs.engine import Job, _sa_type, create_support_tables, database_url, table_for, tenant_key  # noqa: E402
from kybes_jobs.storage import FileStorage  # noqa: E402

PG = os.environ.get("KYBES_TEST_DATABASE_URL")
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
TENANT_A = "00000000-0000-4000-8000-00000000000a"
TENANT_B = "00000000-0000-4000-8000-00000000000b"
TENANTS = {"uuid": TENANT_A, "string": "tenant-a"}


class Db:
    """Database isolato per un test. Con PostgreSQL ogni test lavora in uno schema proprio (search_path),
    con SQLite in un file; schema(nome) aggiunge uno schema (SQLite: database collegato con ATTACH)."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.schemas = []
        if PG:
            self.base = f"kybes_jobs_{uuid.uuid4().hex[:10]}"
            self._admin = sa.create_engine(database_url(PG))
            with self._admin.begin() as c:
                c.execute(sa.text(f'CREATE SCHEMA "{self.base}"'))
            self.engine = sa.create_engine(database_url(PG), connect_args={"options": f"-csearch_path={self.base}"})
        else:
            self.engine = self._sqlite(tmp / "hot.db")
        create_support_tables(self.engine)

    def _sqlite(self, path: Path) -> sa.Engine:
        eng = sa.create_engine(f"sqlite:///{path}")

        @sa.event.listens_for(eng, "connect")
        def _attach(dbapi_conn, _record):
            for name in self.schemas:
                dbapi_conn.execute(f"ATTACH DATABASE '{self.tmp / (name + '.db')}' AS \"{name}\"")
        return eng

    def schema(self, name: str) -> str:
        self.schemas.append(name)
        if PG:
            with self._admin.begin() as c:
                c.execute(sa.text(f'CREATE SCHEMA "{name}"'))
        else:
            self.engine.dispose()  # le nuove connessioni collegano anche il nuovo schema
        return name

    def close(self) -> None:
        self.engine.dispose()
        if PG:
            with self._admin.begin() as c:
                for name in self.schemas + [self.base]:
                    c.execute(sa.text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
            self._admin.dispose()


@pytest.fixture
def db(tmp_path):
    d = Db(tmp_path)
    yield d
    d.close()


@pytest.fixture
def archive(tmp_path):
    return FileStorage(str(tmp_path / "archive"))


def make_cfg(**over):
    """Configurazione di prova: tabella Ordini con chiave uuid, data, importo, json; override per chiave."""
    d = {
        "table": "Ordini", "db_name": "ordini", "key": "Id", "age_column": "Data", "tenancy": "none",
        "columns": [
            {"name": "Id", "db_name": "id", "type": "uuid", "nullable": False},
            {"name": "Numero", "db_name": "numero", "type": "string", "length": 20, "nullable": False},
            {"name": "Data", "db_name": "data", "type": "date", "nullable": False},
            {"name": "Totale", "db_name": "totale", "type": "decimal", "precision": 14, "scale": 2, "nullable": True},
            {"name": "Note", "db_name": "note", "type": "json", "nullable": True},
        ],
        "archive": {"after": "1y", "target": "s3", "location": "s3://non-usato", "partition_by": ["year", "month"], "read_through": True},
        "children": [], "job": {"mode": "cron", "batch_size": 1000},
    }
    for k, v in over.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    return from_dict(d)


def create(db, cfg, schema=None):
    table_for(cfg, schema, sa.MetaData()).create(db.engine)


def sample(cfg, n, age, **over):
    """Riga valida con valori deterministici per ogni tipo di colonna."""
    row = {}
    for c in cfg.columns:
        if c.name == cfg.age_column:
            v = age
        elif c.type == "uuid":
            v = uuid.UUID(int=n)
        elif c.type in ("string", "text"):
            v = f"v{n}"[: c.length or 64]
        elif c.type in ("int", "bigint"):
            v = n
        elif c.type == "decimal":
            v = Decimal(n) + Decimal("0.25")
        elif c.type == "bool":
            v = n % 2 == 0
        elif c.type == "date":
            v = date(2020, 1, 1) + timedelta(days=n)
        elif c.type == "datetime":
            v = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(hours=n)
        else:
            v = {"n": n}
        row[c.db_name] = v
    row.update(over)
    return row


def insert(db, cfg, rows, schema=None):
    t = table_for(cfg, schema, sa.MetaData())
    with db.engine.begin() as c:
        c.execute(sa.insert(t), rows)


def keys_in(db, cfg, schema=None):
    t = table_for(cfg, schema, sa.MetaData())
    with db.engine.connect() as c:
        return sorted(str(k) for k in c.execute(sa.select(t.c[cfg.col(cfg.key).db_name])).scalars())


class TableEnv:
    """La tabella di un job generato pronta per un test: creata dove la mette la sua tenancy (schema del tenant,
    database del tenant su SQLite), con le tabelle figlie ridotte a chiave e chiave esterna."""

    def __init__(self, cfg, db, archive, tmp):
        self.cfg, self.db, self.archive = cfg, db, archive
        self.tenant = TENANTS[cfg.tenant_id_type] if cfg.tenancy != "none" else None
        self.schema = None
        self.url = None
        self._engines = {}
        if cfg.tenancy == "schema":
            self.schema = db.schema("tenant_" + tenant_key(cfg, self.tenant))
        if cfg.tenancy == "database":
            self.url = f"sqlite:///{tmp}/db_{{tenant}}.db"
            self.engine = self._engine_for(self.url.replace("{tenant}", tenant_key(cfg, self.tenant)))
        else:
            self.engine = db.engine
        md = sa.MetaData()
        self.table = table_for(cfg, self.schema, md)
        cols = {}
        for ch in cfg.children:
            if ch.table != cfg.db_name:
                cols.setdefault(ch.table, []).append(ch.column)
        key_type = _sa_type(cfg.col(cfg.key))
        for name, fks in cols.items():
            sa.Table(name, md, sa.Column("kybes_id", sa.Integer, primary_key=True), *[sa.Column(c, key_type) for c in fks], schema=self.schema)
        md.create_all(self.engine)
        self.md = md

    def _engine_for(self, url):
        if url not in self._engines:
            self._engines[url] = sa.create_engine(url)
            create_support_tables(self._engines[url])
        return self._engines[url]

    def age(self, days):
        """Valore della colonna dell'età a days giorni dal limite (negativo = più vecchio del limite)."""
        cut = subtract(NOW, self.cfg.after or self.cfg.delete_after) + timedelta(days=days)
        return cut.date() if self.cfg.col(self.cfg.age_column).type == "date" else cut

    def row(self, n, days):
        over = {}
        if self.cfg.tenant_column:
            tc = self.cfg.col(self.cfg.tenant_column)
            over[tc.db_name] = uuid.UUID(self.tenant) if tc.type == "uuid" else self.tenant
        return sample(self.cfg, n, self.age(days), **over)

    def insert(self, rows):
        with self.engine.begin() as c:
            c.execute(sa.insert(self.table), rows)

    def add_child(self, table, column, parent):
        t = self.md.tables[f"{self.schema}.{table}" if self.schema else table]
        with self.engine.begin() as c:
            c.execute(sa.insert(t).values(kybes_id=1, **{column: parent[self.cfg.col(self.cfg.key).db_name]}))

    def keys(self):
        with self.engine.connect() as c:
            return sorted(str(k) for k in c.execute(sa.select(self.table.c[self.cfg.col(self.cfg.key).db_name])).scalars())

    def key(self, row):
        return codec.key_text(self.cfg, row)

    def segment(self):
        return codec.segment(self.tenant) if self.tenant is not None else None

    def partition_prefix(self, row):
        return f"{self.cfg.db_name}/" + codec.partition_path(self.cfg, self.segment(), row)

    def key_path(self, row):
        tenant = f"tenant={self.segment()}/" if self.tenant is not None else ""
        return f"{self.cfg.db_name}/_keys/{tenant}{codec.segment(self.key(row))}.json"

    def parquet_files(self, storage=None):
        s = storage or self.archive
        return [p for p in s.list(self.cfg.db_name + "/") if p.endswith(".parquet") and "/_" not in p]

    def job(self, now=NOW, storage=None):
        return Job(self.cfg, None if self.cfg.tenancy == "database" else self.engine, database_url=self.url,
                   tenants=[self.tenant] if self.tenant is not None else None, engine_factory=self._engine_for,
                   storage_factory=lambda url, seg: storage or self.archive, archive_url="file:///kybes-test", now=now,
                   log=lambda event: None)
