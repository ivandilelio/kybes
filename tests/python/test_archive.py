"""Archivio e conservazione end-to-end sul progetto di prova (fase 5).

  python3 tests/python/test_archive.py <progetto> <kit>

1. Validazione degli schemi: archive e retention non validi sono rifiutati con un messaggio chiaro.
2. Formato: il segmento del generatore e il documento di prova dei test generati coincidono con quelli del motore.
3. Job reale (CLI) su SQLite: archiviazione, record con figli trattenuto, conservazione, read-through dal modello Python.
4. Layout Hive leggibile da DuckDB (come Athena e Synapse), se duckdb è installato.
5. Archivio S3 con moto, se installato.
6. Manifest Kubernetes: YAML valido con i tipi attesi per cron, keda ed engine, se PyYAML è installato.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

PROJ, KIT = Path(sys.argv[1]), Path(sys.argv[2])
GEN = KIT / "marketplace/plugins/kybes/scripts/gen"
ENGINE = PROJ / "jobs/generated/_engine"
sys.path[:0] = [str(GEN), str(PROJ / "libs/db-models/python/src"), str(ENGINE)]

import emit_archive  # noqa: E402
import schema as S  # noqa: E402
from kybes_jobs import codec, load_config  # noqa: E402
from kybes_jobs.engine import create_support_tables  # noqa: E402

TENANT = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
TMP = Path(tempfile.mkdtemp(prefix="kybes-archive-"))


def check(cond, msg):
    if not cond:
        raise SystemExit("FALLITO: " + msg)


# ------------------------------------------------------------------------------------- 1. validazione

BASE = """table: T
tenancy: {tenancy}
columns:
  - {{ name: Id, type: int, primary_key: true }}
  - {{ name: Il, type: date, required: true }}
  - {{ name: Facoltativa, type: datetime }}
{extra}"""


def errors(extra, tenancy="none", others=()):
    d = TMP / f"schemi-{uuid.uuid4().hex[:6]}"
    d.mkdir()
    (d / "T.yaml").write_text(BASE.format(extra=extra, tenancy=tenancy))
    for name, text in others:
        (d / f"{name}.yaml").write_text(text)
    try:
        S.load_schemas(d)
    except S.SchemaError as exc:
        return "\n".join(exc.errors)
    return ""


CASES = [
    ("archive: { after: 3w, column: Il }", "durata non valida"),
    ("archive: { after: 1y }", "serve la colonna date o datetime"),
    ("archive: { after: 1y, column: Facoltativa }", "deve essere required"),
    ("archive: { after: 1y, column: Id }", "serve date o datetime"),
    ("archive: { after: 1y, column: Il, target: gcs }", "target ammette s3, blob"),
    ("archive: { after: 1y, column: Il, format: csv }", "format ammette solo parquet"),
    ("archive: { after: 1y, column: Il, partition_by: [day] }", "gerarchiche"),
    ("archive: { after: 1y, column: Il, partition_by: [tenant] }", "tenant vale solo per le tabelle multi-tenant"),
    ("archive: { after: 1y, column: Il, partition_by: [year, year] }", "ripetute"),
    ("archive: { after: 1y, column: Il, job: { mode: keda, schedule: x } }", "espressione cron"),
    ("archive: { after: 1y, column: Il, job: { mode: cron, interval: 60 } }", "interval vale solo"),
    ("archive: { after: 1y, column: Il, job: { batch_size: 0 } }", "batch_size deve essere"),
    ("archive: { after: 1y, column: Il, job: { mode: sempre } }", "mode ammette"),
    ("archive: { after: 1y, column: Il, colonna: x }", "chiave sconosciuta 'colonna'"),
    ("archive: { after: 2y, column: Il }\nretention: { delete_after: 1y }", "deve superare archive.after"),
    ("archive: { after: 1y, column: Il, partition_by: [] }\nretention: { delete_after: 5y }", "serve year"),
    ("archive: { after: 1y, column: Il }\nretention: { delete_after: 5y, column: Il }", "togli retention.column"),
    ("retention: { delete_after: 5y }", "senza archivio serve la colonna"),
]
for extra, expected in CASES:
    got = errors(extra)
    check(expected in got, f"{extra!r}: atteso «{expected}», trovato «{got}»")
check("rinominale con db_name" in errors("  - { name: Year, type: int }\narchive: { after: 1y, column: Il }"), "colonna con il nome di una partizione")
child = "table: C\ntenancy: schema\ncolumns:\n  - { name: Id, type: int, primary_key: true }\n  - { name: TId, type: int, required: true }\n" \
        "relations:\n  - { name: T, kind: many_to_one, target: T, foreign_key: TId }\n"
ok = "columns:\n  - { name: Id, type: int, primary_key: true }\n  - { name: Il, type: date, required: true }\n"
d = TMP / "figli"
d.mkdir()
(d / "T.yaml").write_text("table: T\ntenancy: none\n" + ok + "retention: { delete_after: 1y, column: Il }\n")
(d / "C.yaml").write_text(child)
try:
    S.load_schemas(d)
    raise SystemExit("FALLITO: figli in schemi di tenant non rifiutati")
except S.SchemaError as exc:
    check(any("che il job non può controllare" in e for e in exc.errors), str(exc.errors))
d = TMP / "valido"
d.mkdir()
(d / "T.yaml").write_text("table: T\ntenancy: column\n" + ok + "archive: { after: 1y, column: Il, partition_by: [year] }\n")
t = S.load_schemas(d)["T"]
check(t.archive.partition_by == ["tenant", "year"], "tenant implicita con tenancy column")
check(t.job_name == "t-archive" and t.job.mode == "cron", "nome e modalità predefinita del job")
tables = {"T": t}
ac = emit_archive.archive_config({"archive": {"s3": "s3://{tenant}/x"}})
check(any("{tenant} va nel prefisso" in e for e in emit_archive.location_errors(tables, ac)), "{tenant} nel bucket")
check(any("s3://bucket" in e for e in emit_archive.location_errors(tables, emit_archive.archive_config({"archive": {"s3": "x"}}))),
      "location S3 non valida")
t.job.mode, t.tenancy = "keda", "schema"
check(any("keda" in e for e in emit_archive.location_errors(tables, emit_archive.archive_config({}))), "keda con tenancy schema")
print("ok validazione degli schemi")

# ------------------------------------------------------------------------------------- 2. formato

for v in ["ab-C_9", "a/b c%è", "😀", uuid.uuid4(), 42, "tenant-a"]:
    check(emit_archive.segment(v) == codec.segment(v), f"segmento diverso per {v!r}")
cfg = load_config(str(PROJ / "jobs/generated/ordini-archive/config.json"))
tables = S.load_schemas(PROJ / "schemas/db", "none", "uuid")
doc, path = emit_archive.archive_sample(tables["Ordini"], "uuid")
row = {}
for c in cfg.columns:
    v = doc[c.name]
    row[c.db_name] = {"date": lambda x: dt.date.fromisoformat(x), "datetime": lambda x: dt.datetime.fromisoformat(x),
                      "decimal": Decimal, "bigint": int}.get(c.type, lambda x: x)(v)
check(json.loads(codec.key_object(cfg, row)) == doc, "il documento di prova dei test generati non è nel formato del motore")
print("ok formato degli oggetti per chiave identico tra generatore, test generati e motore")

# ------------------------------------------------------------------------------------- 3. job reale

from sqlalchemy import create_engine, event, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from model.generated import Base, FileArchiveReader, bind_archive, bind_tenant  # noqa: E402
from model.Clienti import Clienti, ClientiRepository  # noqa: E402
from model.Eventi import Eventi, EventiRepository  # noqa: E402
from model.Ordini import Ordini, OrdiniRepository  # noqa: E402
from model.Prodotti import Prodotti, ProdottiRepository  # noqa: E402
from model.RigheOrdine import RigheOrdine, RigheOrdineRepository  # noqa: E402

db_url = f"sqlite:///{TMP / 'hot.db'}"
eng = create_engine(db_url)


@event.listens_for(eng, "connect")
def _fk(c, _):
    c.execute("PRAGMA foreign_keys=ON")


Base.metadata.create_all(eng)
create_support_tables(eng)
today = dt.date.today()
with Session(eng) as s:
    bind_tenant(s, TENANT)
    cli = ClientiRepository(s).create(Clienti(ragione_sociale="ACME"))
    orr = OrdiniRepository(s)
    vecchio = orr.create(Ordini(numero="A-2019", cliente_id=cli.id, data=dt.date(2019, 3, 9), totale=Decimal("12.50"), note="archiviami"))
    antico = orr.create(Ordini(numero="A-2010", cliente_id=cli.id, data=dt.date(2010, 5, 1)))
    con_righe = orr.create(Ordini(numero="A-RIGHE", cliente_id=cli.id, data=dt.date(2019, 3, 10)))
    recente = orr.create(Ordini(numero="A-OGGI", cliente_id=cli.id, data=today))
    p = ProdottiRepository(s).create(Prodotti(codice="P1", descrizione="Bullone"))
    RigheOrdineRepository(s).create(RigheOrdine(ordine_id=con_righe.id, prodotto_id=p.id, quantita=1, prezzo_unitario=Decimal("1")))
    ev = EventiRepository(s)
    ev.create(Eventi(id=1, tipo="vecchio", avvenuto_il=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)))
    ev.create(Eventi(id=2, tipo="nuovo", avvenuto_il=dt.datetime.now(dt.timezone.utc)))
    s.commit()
    ids = {k: v.id for k, v in {"vecchio": vecchio, "antico": antico, "con_righe": con_righe, "recente": recente}.items()}
    snapshot = {c: getattr(vecchio, c) for c in ("numero", "cliente_id", "stato", "data", "totale", "note", "creato_il", "tenant_id")}

archive = TMP / "archivio"
env = {**os.environ, "PYTHONPATH": str(ENGINE), "KYBES_DATABASE_URL": db_url, "KYBES_ARCHIVE_URL": f"file://{archive}"}
for job in ("ordini-archive", "eventi-retention"):
    r = subprocess.run([sys.executable, "-m", "kybes_jobs", "run", str(PROJ / f"jobs/generated/{job}/config.json")], env=env,
                       capture_output=True, text=True)
    check(r.returncode == 0, f"{job}: {r.stderr}{r.stdout}")
    check('"event": "done"' in r.stdout, f"{job}: nessun evento done: {r.stdout}")
with Session(eng) as s:
    rest = sorted(s.scalars(select(Ordini.numero)))
    check(rest == ["A-OGGI", "A-RIGHE"], f"ordini rimasti nella tabella hot: {rest}")
    check(sorted(s.scalars(select(Eventi.tipo))) == ["nuovo"], "evento scaduto non cancellato")
files = sorted(p.relative_to(archive).as_posix() for p in archive.rglob("*.parquet"))
check(len(files) == 1 and files[0].startswith(f"ordini/tenant={TENANT}/year=2019/month=03/"), f"file archiviati: {files}")
check(not list(archive.rglob("_staging/*")), "staging non vuoto")
with Session(eng) as s:
    bind_tenant(s, TENANT)
    repo = OrdiniRepository(s)
    check(repo.get_by_id(ids["vecchio"]) is None, "senza lettore l'archivio non è letto")
    bind_archive(s, FileArchiveReader(archive))
    got = repo.get_by_id(ids["vecchio"])
    check(got is not None and got not in s, "record archiviato non trovato dal read-through")
    for c, v in snapshot.items():
        if isinstance(v, dt.datetime) and v.tzinfo is None:
            v = v.replace(tzinfo=dt.timezone.utc)  # SQLite non conserva il fuso: timestamptz in UTC
        check(getattr(got, c) == v, f"read-through: {c} = {getattr(got, c)!r}, atteso {v!r}")
    check(repo.get_by_id(ids["antico"]) is None, "record oltre la conservazione ancora leggibile")
    check(repo.get_by_id(ids["recente"]).numero == "A-OGGI", "record hot")
    bind_tenant(s, uuid.uuid4())
    check(OrdiniRepository(s).get_by_id(ids["vecchio"]) is None, "read-through di un altro tenant")
print("ok job reale: archiviazione, figli, conservazione, cancellazione TTL, read-through Python con tenant")

# ------------------------------------------------------------------------------------- 4. DuckDB

try:
    import duckdb
except ImportError:
    duckdb = None
if duckdb:
    rel = duckdb.sql(f"SELECT tenant, CAST(year AS INTEGER), CAST(month AS INTEGER), numero, totale FROM read_parquet('{archive}/ordini/*/*/*/*.parquet', hive_partitioning = true)")
    rows = rel.fetchall()
    check(rows == [(str(TENANT), 2019, 3, "A-2019", Decimal("12.50"))], f"DuckDB: {rows}")
    print("ok layout Hive dei Parquet letto da DuckDB (partizioni tenant/year/month e tipi)")
else:
    print("skip DuckDB non installato")

# ------------------------------------------------------------------------------------- 5. S3 con moto

try:
    import boto3
    from moto import mock_aws
except ImportError:
    mock_aws = None
if mock_aws:
    os.environ.setdefault("AWS_DEFAULT_REGION", "eu-south-1")
    os.environ.update({"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"})
    from kybes_jobs import Job, open_storage
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket="kybes-test", CreateBucketConfiguration={"LocationConstraint": os.environ["AWS_DEFAULT_REGION"]})
        st = open_storage("s3://kybes-test/archivio/{tenant}", "t1")
        st.put("a/b.bin", b"x")
        check(st.get("a/b.bin") == b"x" and st.get("a/c.bin") is None and st.list("a/") == ["a/b.bin"], "S3: put/get/list")
        st.delete("a/b.bin")
        check(st.list("") == [], "S3: delete")
        with Session(eng) as s:
            bind_tenant(s, TENANT)
            OrdiniRepository(s).create(Ordini(numero="S3", cliente_id=s.scalar(select(Clienti.id)), data=dt.date(2020, 1, 1)))
            s.commit()
        rep = Job(cfg, eng, archive_url="s3://kybes-test/archivio", log=lambda e: None).run()
        keys = [o["Key"] for o in boto3.client("s3").list_objects_v2(Bucket="kybes-test").get("Contents", [])]
        check(rep.archived_rows == 1 and any(k.startswith(f"archivio/ordini/tenant={TENANT}/year=2020/") for k in keys), f"S3: {keys}")
    print("ok archivio S3 (moto): oggetti, job completo")
else:
    print("skip moto non installato")

# ------------------------------------------------------------------------------------- 5b. Azure Blob con Azurite

AZURITE = os.environ.get("KYBES_TEST_AZURITE")  # stringa di connessione di Azurite (la CI lo avvia)
if AZURITE:
    from azure.storage.blob import BlobServiceClient
    from kybes_jobs import Job, open_storage
    os.environ["AZURE_STORAGE_CONNECTION_STRING"] = AZURITE
    container = f"kybes-{uuid.uuid4().hex[:8]}"
    BlobServiceClient.from_connection_string(AZURITE).create_container(container)
    st = open_storage(f"az://{container}/archivio/{{tenant}}", "t1")
    st.put("a/b.bin", b"x")
    check(st.get("a/b.bin") == b"x" and st.get("a/c.bin") is None and st.list("a/") == ["a/b.bin"], "Blob: put/get/list")
    st.delete("a/b.bin")
    st.delete("a/b.bin")
    check(st.list("") == [], "Blob: delete")
    with Session(eng) as s:
        bind_tenant(s, TENANT)
        OrdiniRepository(s).create(Ordini(numero="BLOB", cliente_id=s.scalar(select(Clienti.id)), data=dt.date(2020, 2, 1)))
        s.commit()
    rep = Job(cfg, eng, archive_url=f"az://{container}/archivio", log=lambda e: None).run()
    names = [b.name for b in BlobServiceClient.from_connection_string(AZURITE).get_container_client(container).list_blobs()]
    check(rep.archived_rows == 1 and any(n.startswith(f"archivio/ordini/tenant={TENANT}/year=2020/month=02/") for n in names), f"Blob: {names}")
    print("ok archivio Azure Blob (Azurite): oggetti, job completo")
else:
    print("skip Azurite non configurato (KYBES_TEST_AZURITE)")

# ------------------------------------------------------------------------------------- 6. manifest Kubernetes

try:
    import yaml
except ImportError:
    yaml = None
if yaml:
    kinds = {}
    for f in sorted((PROJ / "jobs/generated").glob("*/kubernetes.yaml")):
        docs = [d for d in yaml.safe_load_all(f.read_text()) if d]
        kinds[f.parent.name] = [d["kind"] for d in docs]
        for d in docs:
            if d["kind"] in ("CronJob", "Deployment", "ScaledJob"):
                spec = d["spec"]
                pod = {"CronJob": lambda: spec["jobTemplate"]["spec"]["template"]["spec"], "Deployment": lambda: spec["template"]["spec"],
                       "ScaledJob": lambda: spec["jobTargetRef"]["template"]["spec"]}[d["kind"]]()
                args = pod["containers"][0]["args"]
                check(args[1] == f"/app/jobs/{f.parent.name}/config.json", f"{f}: args {args}")
                check(("--loop" in args) == (d["kind"] == "Deployment"), f"{f}: --loop solo per engine")
    check(kinds == {"eventi-retention": ["TriggerAuthentication", "ScaledJob", "CronJob"], "ordini-archive": ["CronJob"]}, str(kinds))
    query = next(d for d in yaml.safe_load_all((PROJ / "jobs/generated/eventi-retention/kubernetes.yaml").read_text())
                 if d and d["kind"] == "ScaledJob")["spec"]["triggers"][0]["metadata"]["query"]
    check(query == "SELECT count(*) FROM \"eventi\" h WHERE h.\"avvenuto_il\" < now() - interval '400 days'", query)
    try:
        import pglast
        pglast.parse_sql(query)
        print("ok manifest Kubernetes (CronJob, ScaledJob KEDA con query PostgreSQL valida, CronJob giornaliero)")
    except ImportError:
        print("ok manifest Kubernetes (CronJob, ScaledJob KEDA, CronJob giornaliero)")
else:
    print("skip PyYAML non installato")
print("ARCHIVE OK")
