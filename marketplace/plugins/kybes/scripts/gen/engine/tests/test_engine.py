"""Test di unità del motore dei job (REQ-KYBES-JOB-*): archiviazione sicura, recupero, conservazione, archivi.

Ogni test porta nel docstring il caso (TC-KYBES-JOB-*) e il requisito; specifica in docs/generated/verification/kybes-jobs.md.
"""
import io
import json
import runpy
import sys
import types
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa

from conftest import NOW, PG, TENANT_A, TENANT_B, create, insert, keys_in, make_cfg, sample
from kybes_jobs import FileStorage, Job, JobError, codec, load_config, open_storage, subtract
from kybes_jobs import __main__ as cli
from kybes_jobs import engine as eng
from kybes_jobs.config import from_dict, partition_end
from kybes_jobs.engine import RUNS, Ops, Unit, coerce_tenant, database_url, job_from_env, tenant_key
from kybes_jobs.storage import BlobStorage, S3Storage


def job(db, cfg, archive, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("log", lambda e: None)
    return Job(cfg, db.engine, storage_factory=lambda url, seg: archive, archive_url="file:///non-usato", **kw)


def runs(db):
    with db.engine.connect() as c:
        return c.execute(sa.select(RUNS.c.run_id)).scalars().all()


def parquet_files(archive, prefix="ordini/"):
    return [p for p in archive.list(prefix) if p.endswith(".parquet") and "/_" not in p]


# ------------------------------------------------------------------------------------------- configurazione

def test_job_config_valid(tmp_path):
    """TC-KYBES-JOB-CONFIG · REQ-KYBES-JOB-CONFIG · classi di equivalenza: configurazioni valide e non valide. Atteso: le valide sono caricate con i default, le altre rifiutate con un errore che dice cosa correggere."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"table": "T", "db_name": "t", "key": "Id", "age_column": "Il",
                             "columns": [{"name": "Id", "db_name": "id", "type": "int"}, {"name": "Il", "db_name": "il", "type": "date"}],
                             "retention": {"delete_after": "30d"}}))
    cfg = load_config(str(p))
    assert cfg.delete_after == "30d" and not cfg.archives and cfg.batch_size == 1000
    base = {"table": "T", "db_name": "t", "key": "Id", "age_column": "Il",
            "columns": [{"name": "Id", "db_name": "id", "type": "int"}, {"name": "Il", "db_name": "il", "type": "date"}]}
    for bad in [{**base, "retention": {"delete_after": "3w"}}, base, {**base, "tenancy": "x", "retention": {"delete_after": "1d"}},
                {**base, "archive": {"after": "1d", "partition_by": ["week"]}}, {**base, "age_column": "No", "retention": {"delete_after": "1d"}},
                {"table": "T"}, {**base, "columns": [{"nome": "Id"}]}]:
        with pytest.raises(JobError):
            from_dict(bad)
    with pytest.raises(JobError):
        load_config(str(tmp_path / "manca.json"))
    p.write_text("{non json")
    with pytest.raises(JobError):
        load_config(str(p))


def test_job_durations():
    """TC-KYBES-JOB-DURATION · REQ-KYBES-JOB-CONFIG · valori limite: giorni esatti, mesi e anni di calendario, fine partizione. Atteso: date esatte, fine mese rispettata, fine partizione corretta; durata non valida rifiutata."""
    now = datetime(2024, 3, 31, 10, tzinfo=timezone.utc)
    assert subtract(now, "1d") == datetime(2024, 3, 30, 10, tzinfo=timezone.utc)
    assert subtract(now, "1m") == datetime(2024, 2, 29, 10, tzinfo=timezone.utc)
    assert subtract(now, "3m") == datetime(2023, 12, 31, 10, tzinfo=timezone.utc)
    assert subtract(now, "1y") == datetime(2023, 3, 31, 10, tzinfo=timezone.utc)
    with pytest.raises(JobError):
        subtract(now, "0d")
    assert partition_end({}) is None
    assert partition_end({"year": 2020}) == date(2021, 1, 1)
    assert partition_end({"year": 2020, "month": 12}) == date(2021, 1, 1)
    assert partition_end({"year": 2020, "month": 2}) == date(2020, 3, 1)
    assert partition_end({"year": 2020, "month": 2, "day": 29}) == date(2020, 3, 1)


# ------------------------------------------------------------------------------------------- formati

def test_job_codec_values():
    """TC-KYBES-JOB-CODEC · REQ-KYBES-JOB-FORMAT · classi di equivalenza: formato degli oggetti per chiave per ogni tipo. Atteso: ogni tipo nel formato documentato, percorsi sicuri e reversibili, date in UTC."""
    assert codec.segment("ab-C_9") == "ab-C_9"
    assert codec.segment("a/b c%è") == "a%2Fb%20c%25%C3%A8"
    assert codec.unsegment(codec.segment("a/b c%è")) == "a/b c%è"
    cfg = make_cfg(columns=[
        {"name": "Id", "db_name": "id", "type": "uuid"}, {"name": "Data", "db_name": "data", "type": "datetime"},
        {"name": "Giorno", "db_name": "giorno", "type": "date"}, {"name": "Prezzo", "db_name": "prezzo", "type": "decimal", "scale": 3},
        {"name": "Flag", "db_name": "flag", "type": "bool"}, {"name": "N", "db_name": "n", "type": "bigint"},
        {"name": "Doc", "db_name": "doc", "type": "json"}, {"name": "Vuoto", "db_name": "vuoto", "type": "text"}])
    row = {"id": "00000000-0000-0000-0000-0000000000AB", "data": datetime(2020, 1, 2, 3, 4, 5, 6),
           "giorno": date(2020, 1, 2), "prezzo": Decimal("1.5"), "flag": 1, "n": 9007199254740993, "doc": {"a": [1]}, "vuoto": None}
    doc = json.loads(codec.key_object(cfg, row))
    assert doc == {"Id": "00000000-0000-0000-0000-0000000000ab", "Data": "2020-01-02T03:04:05.000006+00:00", "Giorno": "2020-01-02",
                   "Prezzo": "1.500", "Flag": True, "N": "9007199254740993", "Doc": {"a": [1]}, "Vuoto": None}
    aware = datetime(2020, 12, 31, 23, 30, tzinfo=timezone.utc).astimezone(timezone(__import__("datetime").timedelta(hours=-2)))
    assert codec.utc(aware).hour == 23
    assert codec.partition_values(cfg, {"data": datetime(2020, 12, 31, 23, 30, tzinfo=timezone(__import__("datetime").timedelta(hours=-2)))}) == \
        {"year": 2021, "month": 1, "day": 1}
    with pytest.raises(JobError):
        codec.partition_values(cfg, {"data": None})
    assert codec.parse_partitions("t/tenant=x/year=2020/month=03/day=xx/f.parquet") == {"year": 2020, "month": 3}


def test_job_parquet_roundtrip():
    """TC-KYBES-JOB-PARQUET · REQ-KYBES-JOB-FORMAT · analisi dei requisiti: Parquet con i tipi della tabella, chiavi rilette. Atteso: tipi Parquet coerenti con lo schema, chiavi rilette uguali; file non Parquet rifiutato."""
    import pyarrow.parquet as pq
    cfg = make_cfg(columns=[
        {"name": "Id", "db_name": "id", "type": "uuid", "nullable": False}, {"name": "Data", "db_name": "data", "type": "datetime"},
        {"name": "N", "db_name": "n", "type": "int"}, {"name": "B", "db_name": "b", "type": "bool"},
        {"name": "Totale", "db_name": "totale", "type": "decimal", "precision": 10, "scale": 2}, {"name": "J", "db_name": "j", "type": "json"},
        {"name": "D", "db_name": "d", "type": "date"}])
    rows = [sample(cfg, i, datetime(2020, 1, i, tzinfo=timezone.utc)) for i in (1, 2)]
    rows[1]["j"] = None
    data = codec.to_parquet(cfg, rows)
    t = pq.read_table(io.BytesIO(data))
    assert t.schema.field("totale").type.scale == 2 and str(t.schema.field("data").type) == "timestamp[us, tz=UTC]"
    assert t.column("j").to_pylist() == ['{"n": 1}', None]
    assert codec.parquet_keys(cfg, data) == (2, [str(uuid.UUID(int=1)), str(uuid.UUID(int=2))])
    with pytest.raises(JobError):
        codec.parquet_keys(cfg, b"non parquet")


# ------------------------------------------------------------------------------------------- archivi

def test_job_file_storage(tmp_path):
    """TC-KYBES-JOB-STORAGE-FILE · REQ-KYBES-JOB-STORAGE · analisi dei requisiti: archivio su cartella locale. Atteso: scrittura atomica, lettura, elenco e cancellazione idempotente; percorsi fuori dall'archivio rifiutati."""
    s = FileStorage(str(tmp_path / "a"))
    assert s.list("") == [] and s.get("x/y") is None
    s.put("x/y.bin", b"1")
    s.put("x/z.bin", b"2")
    (tmp_path / "a" / "x" / "w.tmp").write_bytes(b"in scrittura")
    assert s.list("x/") == ["x/y.bin", "x/z.bin"] and s.list("q") == []
    assert s.get("x/y.bin") == b"1"
    s.delete("x/y.bin")
    s.delete("x/y.bin")
    assert s.get("x/y.bin") is None and (tmp_path / "a" / "x").is_dir()
    (tmp_path / "a" / "x" / "w.tmp").unlink()
    s.delete("x/z.bin")
    assert not (tmp_path / "a" / "x").exists() and (tmp_path / "a").is_dir()  # cartelle vuote rimosse fino alla radice
    with pytest.raises(JobError):
        s.put("../fuori", b"")
    from kybes_jobs.storage import Storage
    base = Storage()
    for call in (lambda: base.put("a", b""), lambda: base.get("a"), lambda: base.list(""), lambda: base.delete("a")):
        with pytest.raises(NotImplementedError):
            call()


class _Err(Exception):
    def __init__(self, code=None, status=None):
        super().__init__(code or status)
        if code:
            self.response = {"Error": {"Code": code}}
        if status:
            self.status_code = status


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        if Key == "boom":
            raise _Err("AccessDenied")
        if (Bucket, Key) not in self.objects:
            raise _Err("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        objs = self.objects

        class P:
            def paginate(self, Bucket, Prefix):
                keys = sorted(k for b, k in objs if b == Bucket and k.startswith(Prefix))
                yield {"Contents": [{"Key": k} for k in keys[:1]]}
                yield {"Contents": [{"Key": k} for k in keys[1:]]}
                yield {}
        return P()


def test_job_s3_storage():
    """TC-KYBES-JOB-STORAGE-S3 · REQ-KYBES-JOB-STORAGE · analisi dei requisiti: archivio S3 (API di boto3). Atteso: oggetti scritti, letti, elencati su più pagine e cancellati; oggetto assente = nessun dato; altri errori propagati."""
    for prefix in ("radice/", ""):
        c = FakeS3()
        s = S3Storage(c, "b", prefix)
        s.put("t/a.parquet", b"a")
        s.put("t/b.parquet", b"b")
        assert s.get("t/a.parquet") == b"a" and s.get("t/x") is None
        assert s.list("t/") == ["t/a.parquet", "t/b.parquet"]
        s.delete("t/a.parquet")
        assert s.list("t/") == ["t/b.parquet"]
        with pytest.raises(_Err):
            S3Storage(c, "b").get("boom")


class FakeContainer:
    def __init__(self):
        self.blobs = {}

    def upload_blob(self, name, data, overwrite):
        assert overwrite
        self.blobs[name] = data

    def download_blob(self, name):
        if name.endswith("boom"):
            raise _Err(status=403)
        if name not in self.blobs:
            raise _Err(status=404)
        return types.SimpleNamespace(readall=lambda: self.blobs[name])

    def list_blobs(self, name_starts_with):
        return [types.SimpleNamespace(name=n) for n in sorted(self.blobs) if n.startswith(name_starts_with)]

    def delete_blob(self, name):
        if name.endswith("boom"):
            raise _Err(status=403)
        if name not in self.blobs:
            raise _Err(status=404)
        del self.blobs[name]


def test_job_blob_storage():
    """TC-KYBES-JOB-STORAGE-BLOB · REQ-KYBES-JOB-STORAGE · analisi dei requisiti: archivio Azure Blob (API di azure-storage-blob). Atteso: blob scritti, letti, elencati e cancellati; blob assente = nessun dato; altri errori propagati."""
    for prefix in ("radice", ""):
        c = FakeContainer()
        s = BlobStorage(c, prefix)
        s.put("t/a.parquet", b"a")
        assert s.get("t/a.parquet") == b"a" and s.get("t/x") is None
        assert s.list("t/") == ["t/a.parquet"]
        s.delete("t/a.parquet")
        s.delete("t/a.parquet")
        assert s.list("") == []
        with pytest.raises(_Err):
            s.get("boom")
        with pytest.raises(_Err):
            s.delete("boom")


def test_job_open_storage(tmp_path, monkeypatch):
    """TC-KYBES-JOB-LOCATION · REQ-KYBES-JOB-STORAGE · classi di equivalenza: location s3, az, https Blob, file, {tenant}, non valide. Atteso: l'archivio giusto per ogni schema di URL, {tenant} sostituito; location non valide rifiutate."""
    made = {}
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda name: made.setdefault("s3", FakeS3())))

    class Service:
        def __init__(self, url=None, credential=None):
            made["account"], made["credential"] = url, credential

        @classmethod
        def from_connection_string(cls, conn):
            made["conn"] = conn
            return cls()

        def get_container_client(self, name):
            made["container"] = name
            return FakeContainer()
    monkeypatch.setitem(sys.modules, "azure", types.ModuleType("azure"))
    monkeypatch.setitem(sys.modules, "azure.storage", types.ModuleType("azure.storage"))
    monkeypatch.setitem(sys.modules, "azure.storage.blob", types.SimpleNamespace(BlobServiceClient=Service))
    monkeypatch.setitem(sys.modules, "azure.identity", types.SimpleNamespace(DefaultAzureCredential=lambda: "cred"))
    s = open_storage("s3://bucket/archivio/{tenant}", "t1")
    assert isinstance(s, S3Storage) and s.bucket == "bucket" and s.prefix == "archivio/t1"
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    s = open_storage("az://archivio/kybes")
    assert isinstance(s, BlobStorage) and s.prefix == "kybes" and made["container"] == "archivio" and made["conn"]
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING")
    s = open_storage("https://conto.blob.core.windows.net/archivio/kybes/x")
    assert made["account"] == "https://conto.blob.core.windows.net" and made["credential"] == "cred" and s.prefix == "kybes/x"
    with pytest.raises(JobError):
        open_storage("az://archivio")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://altro.blob.core.windows.net")
    open_storage("az://archivio")
    assert made["account"] == "https://altro.blob.core.windows.net"
    assert isinstance(open_storage(f"file://{tmp_path}"), FileStorage)
    assert open_storage(str(tmp_path)).root == tmp_path
    for bad in ("ftp://x/y", "https://example.com/x"):
        with pytest.raises(JobError):
            open_storage(bad)
    with pytest.raises(JobError):
        open_storage("s3://b/{tenant}")


# ------------------------------------------------------------------------------------------- archiviazione

def test_job_archive_moves_old_rows(db, archive):
    """TC-KYBES-JOB-ARCHIVE · REQ-KYBES-JOB-ARCHIVE · analisi dei requisiti: le righe più vecchie del limite passano nell'archivio. Atteso: righe oltre il limite nell'archivio (Parquet per partizione e oggetti per chiave), le altre restano; staging e registro vuoti."""
    cfg = make_cfg()
    create(db, cfg)
    old = [sample(cfg, i, date(2020, 1 + i % 2, 10)) for i in range(1, 6)]
    young = [sample(cfg, 50, date(2026, 1, 1)), sample(cfg, 51, date(2025, 6, 15))]  # 15/6/2025 = limite, non archiviato
    insert(db, cfg, old + young)
    rep = job(db, cfg, archive).run()
    assert rep.archived_rows == 5 and rep.archived_files == 2
    assert keys_in(db, cfg) == sorted(str(uuid.UUID(int=n)) for n in (50, 51))
    files = parquet_files(archive)
    assert [f.rsplit("/", 1)[0] for f in files] == ["ordini/year=2020/month=01", "ordini/year=2020/month=02"]
    got = sorted(k for f in files for k in codec.parquet_keys(cfg, archive.get(f))[1])
    assert got == sorted(str(r["id"]) for r in old)
    key = json.loads(archive.get(f"ordini/_keys/{uuid.UUID(int=1)}.json"))
    assert key["Numero"] == "v1" and key["Totale"] == "1.25" and key["Data"] == "2020-02-10"
    assert archive.list("ordini/_staging/") == [] and runs(db) == []


def test_job_archive_batches_and_children(db, archive):
    """TC-KYBES-JOB-BATCH · REQ-KYBES-JOB-ARCHIVE · valori limite: lotti pieni e incompleti; un record con figli resta nella tabella hot. Atteso: tutti i lotti elaborati; il record con figli resta nella tabella hot."""
    cfg = make_cfg(job={"batch_size": 2}, children=[{"table": "righe", "column": "ordine_id", "on_delete": "cascade"}],
                   archive={"after": "1y", "location": "x", "partition_by": [], "read_through": False})
    create(db, cfg)
    righe = sa.Table("righe", sa.MetaData(), sa.Column("id", sa.Integer, primary_key=True), sa.Column("ordine_id", sa.Uuid))
    righe.create(db.engine)
    insert(db, cfg, [sample(cfg, i, date(2020, 1, i)) for i in range(1, 6)])
    with db.engine.begin() as c:
        c.execute(sa.insert(righe).values(id=1, ordine_id=uuid.UUID(int=3)))
    rep = job(db, cfg, archive).run()
    assert rep.archived_rows == 4 and keys_in(db, cfg) == [str(uuid.UUID(int=3))]
    assert len(parquet_files(archive)) == 2 and not archive.list("ordini/_keys")  # un file per lotto (nessuna partizione)


def test_job_archive_failure_keeps_rows(db, archive):
    """TC-KYBES-JOB-FAILSAFE · REQ-KYBES-JOB-SAFE · error guessing: archivio che fallisce in scrittura o in verifica. Atteso: le righe restano nella tabella hot, lo staging è scartato, nessun passaggio registrato."""
    cfg = make_cfg()
    create(db, cfg)
    insert(db, cfg, [sample(cfg, i, date(2020, 1, i)) for i in (1, 2)])

    class Broken(FileStorage):
        def __init__(self, root, mode):
            super().__init__(root)
            self.mode = mode

        def put(self, path, data):
            if self.mode == "put" and path.endswith(".json") and "_keys" in path:
                raise OSError("disco pieno")
            super().put(path, data)

        def get(self, path):
            data = super().get(path)
            return data + b"x" if self.mode == "corrupt" and data is not None else data
    for mode, err in (("put", OSError), ("corrupt", JobError)):
        broken = Broken(archive.root, mode)
        with pytest.raises(err):
            job(db, cfg, broken).run()
        assert len(keys_in(db, cfg)) == 2 and archive.list("") == [] and runs(db) == []


def test_job_archive_verification(db, archive, monkeypatch):
    """TC-KYBES-JOB-VERIFY · REQ-KYBES-JOB-SAFE · error guessing: file con righe diverse o cancellazione incompleta. Atteso: errore, righe intatte, archivio vuoto."""
    cfg = make_cfg()
    create(db, cfg)
    insert(db, cfg, [sample(cfg, i, date(2020, 1, i)) for i in (1, 2)])
    real = codec.to_parquet
    monkeypatch.setattr(codec, "to_parquet", lambda c, rows: real(c, list(rows)[:1]))
    with pytest.raises(JobError, match="righe o chiavi"):
        job(db, cfg, archive).run()
    monkeypatch.setattr(codec, "to_parquet", real)
    assert len(keys_in(db, cfg)) == 2 and archive.list("") == []

    class Short(Job):
        def _delete_rows(self, conn, t, key, keys):
            return super()._delete_rows(conn, t, key, keys[:1])
    j = Short(cfg, db.engine, storage_factory=lambda u, s: archive, archive_url="x", now=NOW, log=lambda e: None)
    with pytest.raises(JobError, match="cancellate 1 righe invece di 2"):
        j.run()
    assert len(keys_in(db, cfg)) == 2 and archive.list("") == [] and runs(db) == []


def test_job_recovery(db, archive):
    """TC-KYBES-JOB-RECOVERY · REQ-KYBES-JOB-SAFE · error guessing: interruzione dopo il commit (promosso) e prima (scartato). Atteso: il passaggio confermato è completato, quello non confermato scartato."""
    cfg = make_cfg()
    create(db, cfg)
    insert(db, cfg, [sample(cfg, i, date(2020, 1, i)) for i in (1, 2)])

    class Crash(Job):
        def _promote(self, unit, storage, run):
            raise RuntimeError("processo terminato")
    j = Crash(cfg, db.engine, storage_factory=lambda u, s: archive, archive_url="x", now=NOW, log=lambda e: None)
    with pytest.raises(RuntimeError):
        j.run()
    assert keys_in(db, cfg) == [] and len(runs(db)) == 1 and parquet_files(archive) == []
    archive.put("ordini/_staging/_/20200101T000000Z-dead/ordini/year=2020/month=01/part-x.parquet", b"incompleto")
    rep = job(db, cfg, archive).run()
    assert rep.recovered_runs == 1 and rep.discarded_runs == 1
    assert len(parquet_files(archive)) == 1 and archive.list("ordini/_staging") == [] and runs(db) == []
    assert archive.get(f"ordini/_keys/{uuid.UUID(int=2)}.json") is not None


def test_job_promote_checks(db, archive):
    """TC-KYBES-JOB-PROMOTE · REQ-KYBES-JOB-SAFE · error guessing: manifest assente, file già promosso, file alterato o perso. Atteso: errore se manca il manifest o un file non corrisponde; un file già promosso non è riscritto."""
    cfg = make_cfg()
    create(db, cfg)
    j = job(db, cfg, archive)
    unit = Unit(engine=db.engine)
    stage = "ordini/_staging/_/r1/"
    with pytest.raises(JobError, match="senza manifest"):
        j._promote(unit, archive, "r1")
    archive.put("ordini/a.json", b"gia")
    manifest = {"files": [{"path": "ordini/a.json", "sha256": codec.sha256(b"gia")}, {"path": "ordini/b.json", "sha256": codec.sha256(b"b")}]}
    archive.put(stage + "manifest.json", json.dumps(manifest).encode())
    archive.put(stage + "ordini/b.json", b"b")
    j._promote(unit, archive, "r1")
    assert archive.get("ordini/b.json") == b"b" and archive.list(stage) == []
    archive.put(stage + "manifest.json", json.dumps({"files": [{"path": "ordini/c.json", "sha256": "0"}]}).encode())
    with pytest.raises(JobError, match="manca sia"):
        j._promote(unit, archive, "r1")
    archive.put(stage + "ordini/c.json", b"alterato")
    with pytest.raises(JobError, match="non corrisponde"):
        j._promote(unit, archive, "r1")


# ------------------------------------------------------------------------------------------- conservazione

def test_job_archive_retention(db, archive):
    """TC-KYBES-JOB-PURGE · REQ-KYBES-JOB-RETENTION · valori limite: partizioni finite prima del limite cancellate, le altre restano. Atteso: cancellate solo le partizioni finite prima del limite, con i loro oggetti per chiave."""
    cfg = make_cfg(retention={"delete_after": "5y"})
    create(db, cfg)
    insert(db, cfg, [sample(cfg, 1, date(2021, 5, 31)), sample(cfg, 2, date(2021, 6, 1)), sample(cfg, 3, date(2021, 6, 30))])
    job(db, cfg, archive).run()
    # limite 15/6/2021: maggio finisce l'1/6 (cancellata), giugno finisce l'1/7 (resta)
    assert [f.rsplit("/", 1)[0] for f in parquet_files(archive)] == ["ordini/year=2021/month=06"]
    assert archive.get(f"ordini/_keys/{uuid.UUID(int=1)}.json") is None
    assert archive.get(f"ordini/_keys/{uuid.UUID(int=2)}.json") is not None
    rep = job(db, cfg, archive, now=datetime(2026, 7, 2, tzinfo=timezone.utc)).run()
    assert rep.deleted_files == 1 and parquet_files(archive) == [] and archive.list("ordini/_keys") == []


def test_job_purge_edge_cases(db, archive):
    """TC-KYBES-JOB-PURGE-EDGE · REQ-KYBES-JOB-RETENTION · error guessing: partizioni senza anno, file sparito durante la lettura. Atteso: file non Parquet e partizioni senza anno restano; un file sparito non ferma il job."""
    cfg = make_cfg(retention={"delete_after": "1y"})
    j = job(db, cfg, archive)

    class Vanishing(FileStorage):
        def get(self, path):
            return None if path.endswith("sparito.parquet") else super().get(path)
    s = Vanishing(archive.root)
    s.put("ordini/year=2000/sparito.parquet", b"x")
    s.put("ordini/senza-anno.parquet", b"x")
    s.put("ordini/year=2000/note.txt", b"x")
    rep = eng.Report()
    j._purge_archive(Unit(engine=db.engine), s, NOW, rep)
    assert rep.deleted_files == 1 and s.list("ordini/") == ["ordini/senza-anno.parquet", "ordini/year=2000/note.txt"]
    s.put("ordini/year=2001/vecchio.parquet", b"x")
    job(db, make_cfg(archive={"after": "1y", "location": "x", "partition_by": ["year"]}, retention={"delete_after": "2y"}), s)._purge_archive(
        Unit(engine=db.engine), s, NOW, rep)
    assert rep.deleted_files == 2 and s.get("ordini/year=2001/vecchio.parquet") is None


def test_job_retention_hot(db, archive):
    """TC-KYBES-JOB-TTL · REQ-KYBES-JOB-RETENTION · analisi dei requisiti: senza archivio le righe scadute sono cancellate a lotti;
    un figlio restrict trattiene il record, cascade no. Atteso: cancellate solo le righe scadute, a lotti; il record trattenuto da un figlio restrict resta."""
    cfg = make_cfg(archive=None, age_column="Data", retention={"delete_after": "90d"}, job={"batch_size": 2},
                   children=[{"table": "vincoli", "column": "ordine_id", "on_delete": "restrict"},
                             {"table": "allegati", "column": "ordine_id", "on_delete": "cascade"}],
                   columns=[{"name": "Id", "db_name": "id", "type": "bigint", "nullable": False},
                            {"name": "Data", "db_name": "data", "type": "datetime", "nullable": False}])
    create(db, cfg)
    with db.engine.begin() as c:
        c.execute(sa.text("CREATE TABLE vincoli (id integer primary key, ordine_id bigint)"))
        c.execute(sa.text("CREATE TABLE allegati (id integer primary key, ordine_id bigint)"))
        c.execute(sa.text("INSERT INTO vincoli VALUES (1, 3)"))
        c.execute(sa.text("INSERT INTO allegati VALUES (1, 4)"))
    insert(db, cfg, [{"id": i, "data": datetime(2026, 1, i, tzinfo=timezone.utc)} for i in range(1, 6)] +
           [{"id": 9, "data": datetime(2026, 6, 1, tzinfo=timezone.utc)}])
    rep = job(db, cfg, archive).run()
    assert rep.deleted_rows == 4 and keys_in(db, cfg) == ["3", "9"]


# ------------------------------------------------------------------------------------------- multi-tenant

def _tenant_cfg(tenancy, **over):
    cols = make_cfg().columns
    columns = [c.__dict__ for c in cols]
    if tenancy == "column":
        columns.insert(1, {"name": "TenantId", "db_name": "tenant_id", "type": "uuid", "nullable": False})
    return make_cfg(tenancy=tenancy, tenant_column="TenantId" if tenancy == "column" else None, columns=columns,
                    archive={"after": "1y", "location": "x", "partition_by": ["tenant", "year"], "read_through": True}, **over)


def test_job_tenant_column(db, archive):
    """TC-KYBES-JOB-TENANT-COLUMN · REQ-KYBES-JOB-TENANT · analisi dei requisiti: un'unità per tenant, archivio separato per tenant;
    i tenant rimasti solo nell'archivio sono ancora soggetti alla conservazione. Atteso: un'unità per tenant, percorsi tenant=<id>; tenant presenti solo nell'archivio inclusi."""
    cfg = _tenant_cfg("column", retention={"delete_after": "3y"})
    create(db, cfg)
    insert(db, cfg, [sample(cfg, 1, date(2020, 1, 1), tenant_id=uuid.UUID(TENANT_A)),
                     sample(cfg, 2, date(2024, 1, 1), tenant_id=uuid.UUID(TENANT_B)),
                     sample(cfg, 3, date(2026, 1, 1), tenant_id=uuid.UUID(TENANT_B))])
    j = job(db, cfg, archive)
    assert [u.segment for u in j.units()] == [TENANT_A, TENANT_B]
    rep = j.run()
    assert rep.archived_rows == 2 and rep.deleted_files == 1      # A (2020): archiviato e subito oltre la conservazione
    assert [f.rsplit("/", 1)[0] for f in parquet_files(archive)] == [f"ordini/tenant={TENANT_B}/year=2024"]
    assert archive.get(f"ordini/_keys/tenant={TENANT_B}/{uuid.UUID(int=2)}.json") is not None
    # B non ha più righe vecchie nella tabella hot: il tenant si trova dall'archivio
    with db.engine.begin() as c:
        c.execute(sa.delete(eng.table_for(cfg, None, sa.MetaData())))
    assert [u.segment for u in job(db, cfg, archive).units()] == [TENANT_B]
    rep = job(db, cfg, archive, now=datetime(2028, 1, 2, tzinfo=timezone.utc)).run()
    assert rep.deleted_files == 1 and parquet_files(archive) == []
    explicit = job(db, cfg, archive, tenants=[TENANT_B.upper()])
    assert [u.tenant for u in explicit.units()] == [uuid.UUID(TENANT_B)]
    templated = Job(cfg, db.engine, storage_factory=lambda u, s: archive, archive_url="s3://b/{tenant}", now=NOW, log=lambda e: None)
    assert templated.units() == []


def test_job_tenant_schema(db, archive):
    """TC-KYBES-JOB-TENANT-SCHEMA · REQ-KYBES-JOB-TENANT · analisi dei requisiti: una tabella per schema di tenant, trovati da soli (uuid). Atteso: ogni schema elaborato, archivio separato per tenant; tenant string senza KYBES_TENANTS rifiutati."""
    cfg = _tenant_cfg("schema")
    for t, n in ((TENANT_A, 1), (TENANT_B, 2)):
        schema = db.schema("tenant_" + t.replace("-", "_"))
        create(db, cfg, schema)
        insert(db, cfg, [sample(cfg, n, date(2020, 1, 1)), sample(cfg, n + 10, date(2026, 1, 1))], schema)
    db.schema("tenant_non_uuid")
    j = job(db, cfg, archive)
    assert {TENANT_A, TENANT_B} <= {u.segment for u in j.units()}
    rep = job(db, cfg, archive, tenants=[TENANT_A, TENANT_B]).run()
    assert rep.archived_rows == 2
    assert [f.rsplit("/", 1)[0] for f in parquet_files(archive)] == [f"ordini/tenant={TENANT_A}/year=2020", f"ordini/tenant={TENANT_B}/year=2020"]
    string_cfg = _tenant_cfg("schema", tenant_id_type="string")
    with pytest.raises(JobError, match="KYBES_TENANTS"):
        job(db, string_cfg, archive).units()


def test_job_tenant_database(db, archive, tmp_path):
    """TC-KYBES-JOB-TENANT-DATABASE · REQ-KYBES-JOB-TENANT · analisi dei requisiti: un database per tenant da KYBES_TENANTS. Atteso: ogni database elaborato; modello di URL senza {tenant} o tenant mancanti rifiutati."""
    cfg = _tenant_cfg("database", tenant_id_type="string")
    engines = {}

    def factory(url):
        if url not in engines:
            engines[url] = sa.create_engine(url)
            eng.create_support_tables(engines[url])
            eng.table_for(cfg, None, sa.MetaData()).create(engines[url])
        return engines[url]
    tpl = f"sqlite:///{tmp_path}/db_{{tenant}}.db"
    for t, n in (("org-uno", 1), ("org-due", 2)):
        e = factory(tpl.replace("{tenant}", t.replace("-", "_")))
        with e.begin() as c:
            c.execute(sa.insert(eng.table_for(cfg, None, sa.MetaData())), [sample(cfg, n, date(2020, 1, 1))])
    j = Job(cfg, None, database_url=tpl, tenants=["org-uno", "org-due"], engine_factory=factory, storage_factory=lambda u, s: archive,
            archive_url="x", now=NOW, log=lambda e: None)
    assert j.run().archived_rows == 2
    assert [f.split("/")[1] for f in parquet_files(archive)] == ["tenant=org-due", "tenant=org-uno"]
    with pytest.raises(JobError, match="tenancy database"):
        Job(cfg, None, database_url="sqlite://", archive_url="x")
    with pytest.raises(JobError, match="KYBES_TENANTS"):
        Job(cfg, None, database_url=tpl, archive_url="x").units()


def test_job_tenant_names():
    """TC-KYBES-JOB-TENANT-NAMES · REQ-KYBES-JOB-TENANT · classi di equivalenza: tenant validi e non validi. Atteso: nomi sicuri per schema e database; valori non validi rifiutati."""
    cfg = _tenant_cfg("schema", tenant_id_type="string")
    assert tenant_key(cfg, "Org-1") == "org_1"
    for bad in ("con spazio", "x" * 49):
        with pytest.raises(JobError):
            tenant_key(cfg, bad)
    with pytest.raises(JobError):
        coerce_tenant(cfg, "")
    with pytest.raises(JobError):
        coerce_tenant(_tenant_cfg("column"), "non-uuid")


# ------------------------------------------------------------------------------------------- PostgreSQL e concorrenza

class FakePgConn:
    def __init__(self, results=()):
        self.dialect = types.SimpleNamespace(name="postgresql")
        self.calls, self.results = [], list(results)

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))
        value = self.results.pop(0) if self.results else None
        return types.SimpleNamespace(scalar=lambda: value, first=lambda: value)


def test_job_postgres_ops():
    """TC-KYBES-JOB-PG · REQ-KYBES-JOB-LOCK · analisi dei requisiti: lock consultivo, tenant della transazione, controllo della RLS. Atteso: istruzioni PostgreSQL corrette; ruolo che non vede tutte le righe con la RLS rifiutato; altri database senza istruzioni."""
    c = FakePgConn([True])
    ops = Ops(c)
    assert ops.try_lock(c, "kybes:ordini") is True
    ops.unlock(c, "kybes:ordini")
    ops.set_tenant(c, None)
    ops.set_tenant(c, TENANT_A)
    assert "pg_try_advisory_lock" in c.calls[0][0] and "pg_advisory_unlock" in c.calls[1][0]
    assert c.calls[0][1]["k"] == c.calls[1][1]["k"] == eng.lock_id("kybes:ordini") and c.calls[2][1] == {"t": TENANT_A}
    generic = FakePgConn()
    generic.dialect.name = "sqlite"
    g = Ops(generic)
    assert g.try_lock(generic, "x") is True
    g.unlock(generic, "x")
    g.set_tenant(generic, TENANT_A)
    g.check_rls(generic, "ordini")
    assert generic.calls == []
    for row, ok in ((None, False), ((True, True, False, True), False), ((True, False, False, False), False),
                    ((True, False, False, True), True), ((True, True, True, False), True), ((False, False, False, False), True)):
        c = FakePgConn([row])
        if ok:
            Ops(c).check_rls(c, "ordini")
        else:
            with pytest.raises(JobError):
                Ops(c).check_rls(c, "ordini")


def test_job_locked_unit(db, archive, monkeypatch, capsys):
    """TC-KYBES-JOB-LOCKED · REQ-KYBES-JOB-LOCK · error guessing: un altro job sta già elaborando la tabella. Atteso: l'unità è saltata e registrata, nessuna riga toccata."""
    cfg = make_cfg()
    create(db, cfg)
    insert(db, cfg, [sample(cfg, 1, date(2020, 1, 1))])
    monkeypatch.setattr(Ops, "try_lock", lambda self, conn, name: False)
    rep = Job(cfg, db.engine, storage_factory=lambda u, s: archive, archive_url="x", now=NOW).run()
    assert rep.skipped_units == ["-"] and len(keys_in(db, cfg)) == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [e["event"] for e in events] == ["locked", "done"]


@pytest.mark.skipif(not PG, reason="lock consultivi reali solo su PostgreSQL")
def test_job_postgres_lock_real(db, archive):
    """TC-KYBES-JOB-PG-LOCK · REQ-KYBES-JOB-LOCK · analisi dei requisiti: due job sulla stessa tabella, uno solo lavora. Atteso: il secondo job salta la tabella."""
    cfg = make_cfg()
    create(db, cfg)
    with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        assert Ops(c).try_lock(c, "kybes:ordini::-")
        rep = job(db, cfg, archive).run()
        Ops(c).unlock(c, "kybes:ordini::-")
    assert rep.skipped_units == ["-"]


# ------------------------------------------------------------------------------------------- avvio

def test_job_from_env(db, monkeypatch, tmp_path):
    """TC-KYBES-JOB-ENV · REQ-KYBES-JOB-CONFIG · classi di equivalenza: variabili d'ambiente del job. Atteso: URL normalizzato, tenant e location letti; configurazioni incomplete rifiutate."""
    cfg = make_cfg()
    assert database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert database_url("postgres://u@h/db") == "postgresql+psycopg://u@h/db"
    assert database_url("sqlite://") == "sqlite://"
    with pytest.raises(JobError):
        job_from_env(cfg, {})
    j = job_from_env(cfg, {"KYBES_DATABASE_URL": "sqlite://", "KYBES_TENANTS": " a, ,b", "KYBES_ARCHIVE_URL": "file:///x"})
    assert j.tenants == ["a", "b"] and j.location == "file:///x" and j.engine is not None
    j = job_from_env(_tenant_cfg("database"), {"KYBES_DATABASE_URL": "sqlite:///{tenant}.db"})
    assert j.engine is None and j.tenants is None
    monkeypatch.setenv("KYBES_DATABASE_URL", "sqlite://")
    assert job_from_env(make_cfg(archive=None, retention={"delete_after": "1d"})).location is None
    with pytest.raises(JobError, match="location"):
        Job(make_cfg(archive={"after": "1y"}), db.engine)
    with pytest.raises(JobError, match="KYBES_DATABASE_URL"):
        Job(cfg, None)
    assert Unit().label == "-" and eng.Report().as_dict()["archived_rows"] == 0
    j = job(db, cfg, None)
    assert j.table(None) is j.table(None)


def test_job_cli(db, tmp_path, monkeypatch, capsys):
    """TC-KYBES-JOB-CLI · REQ-KYBES-JOB-CLI · classi di equivalenza: un passaggio, sempre attivo, errori e uso sbagliato. Atteso: codici di uscita 0, 1, 2; il ciclo continua dopo un errore e si ferma su richiesta."""
    p = tmp_path / "config.json"
    cfg_doc = {"table": "Ordini", "db_name": "ordini", "key": "Id", "age_column": "Data",
               "columns": [{"name": "Id", "db_name": "id", "type": "int"}, {"name": "Data", "db_name": "data", "type": "date"}],
               "retention": {"delete_after": "1d"}, "job": {"mode": "engine", "interval": 2}}
    p.write_text(json.dumps(cfg_doc))
    assert cli.main([]) == 2
    assert cli.main(["run", str(tmp_path / "manca.json")]) == 2
    monkeypatch.setenv("KYBES_DATABASE_URL", f"sqlite:///{tmp_path}/cli.db")
    assert cli.main(["run", str(p)]) == 1          # tabella inesistente
    with sa.create_engine(f"sqlite:///{tmp_path}/cli.db").begin() as c:
        c.execute(sa.text("CREATE TABLE ordini (id integer primary key, data date)"))
    assert cli.main(["run", str(p)]) == 0
    stop = cli._Stop()
    slept = []

    def sleep(s):
        slept.append(s)
        if len(slept) == 3:
            stop()
    monkeypatch.setattr(cli.signal, "signal", lambda sig, handler: None)
    assert cli.main(["run", str(p), "--loop"], sleep=sleep, stop=stop) == 0
    assert len(slept) == 3
    monkeypatch.setenv("KYBES_DATABASE_URL", "")
    stop = cli._Stop()
    assert cli.main(["run", str(p), "--loop"], sleep=lambda s: stop(), stop=stop) == 0
    assert '"event": "error"' in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["kybes_jobs"])
    with pytest.raises(SystemExit) as exit_:
        runpy.run_module("kybes_jobs", run_name="__main__")
    assert exit_.value.code == 2
