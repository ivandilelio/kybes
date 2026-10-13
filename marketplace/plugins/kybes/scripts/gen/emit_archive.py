"""Archivio hot → cold e conservazione (fase 5): configurazione dei job, manifest Kubernetes, motore dei job,
tabelle esterne Athena (S3) e viste Synapse serverless (Blob), test del motore e dei job di ogni tabella."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from naming import MARKER, header
from schema import ASIL, Table, duration_days, lifecycle_children, snake, tenant_column

ENGINE_SRC = Path(__file__).resolve().parent / "engine"

DEFAULT_ARCHIVE = {
    "s3": "s3://kybes-archive/archive",
    "blob": "https://kybesarchive.blob.core.windows.net/archive",
    "image": "kybes-jobs:latest",
    "namespace": "default",
    "service_account": "kybes-jobs",
    "db_secret": "kybes-jobs-db",
}
PG_INTERVAL = {"d": "days", "m": "months", "y": "years"}


def archive_config(mc: dict) -> dict:
    out = dict(DEFAULT_ARCHIVE)
    out.update(mc.get("archive") or {})
    return out


def lifecycle_tables(tables: Dict[str, Table]) -> Dict[str, Table]:
    return {n: t for n, t in tables.items() if t.archive or t.retention}


def location_errors(tables: Dict[str, Table], ac: dict) -> List[str]:
    """{tenant} è ammesso solo nel prefisso: bucket e container restano gli stessi per tutte le Organization."""
    errs = []
    for target in sorted({t.archive.target for t in tables.values() if t.archive}):
        loc = ac.get(target) or ""
        u = urlparse(loc)
        if target == "s3" and (u.scheme != "s3" or not u.netloc):
            errs.append(f"configurazione: model.archive.s3 deve essere s3://bucket/prefisso (trovato {loc!r})")
        elif target == "blob" and not (u.scheme == "az" and u.netloc or u.scheme == "https" and u.netloc.endswith(".blob.core.windows.net")
                                       and u.path.strip("/")):
            errs.append(f"configurazione: model.archive.blob deve essere https://<account>.blob.core.windows.net/<container>/prefisso "
                        f"o az://<container>/prefisso (trovato {loc!r})")
        elif "{tenant}" in u.netloc or (target == "blob" and u.scheme == "https" and "{tenant}" in u.path.strip("/").split("/")[0]):
            errs.append(f"configurazione: model.archive.{target}: {{tenant}} va nel prefisso, non nel nome del bucket o del container")
    for t in tables.values():
        if t.archive and t.tenancy == "none" and "{tenant}" in (ac.get(t.archive.target) or ""):
            errs.append(f"{t.name}: la location dell'archivio contiene {{tenant}} ma la tabella non è multi-tenant")
    for t in tables.values():
        if t.job and t.job.mode == "keda" and t.tenancy in ("schema", "database"):
            errs.append(f"{t.name}: job.mode keda conta le righe da un solo database e schema: con tenancy {t.tenancy} usa cron o engine")
    return errs


# ------------------------------------------------------------------------------------------- formato per chiave

TENANT_SAMPLE = {"uuid": "00000000-0000-4000-8000-00000000000a", "string": "tenant-a"}


def segment(value) -> str:
    """Come codec.segment del motore: lettere, cifre, _ e - restano, il resto diventa %XX (UTF-8)."""
    out = []
    for ch in str(value):
        if ch.isascii() and (ch.isalnum() or ch in "_-"):
            out.append(ch)
        else:
            out.append("".join(f"%{b:02X}" for b in ch.encode("utf-8")))
    return "".join(out)


def sample_value(c, key: bool = False):
    """Valore JSON deterministico per ogni tipo, nel formato degli oggetti per chiave scritti dal job."""
    from decimal import Decimal
    if c.type == "uuid":
        return "00000000-0000-4000-8000-0000000000a1" if key else "00000000-0000-4000-8000-0000000000b2"
    if c.type == "string":
        return ("arc/hiv è" if key else "archiviato")[: c.length]
    if c.type == "text":
        return "testo archiviato è"
    if c.type == "int":
        return 42
    if c.type == "bigint":
        return "9007199254740993"
    if c.type == "decimal":
        return str(Decimal("12.34").quantize(Decimal(1).scaleb(-c.scale)))
    if c.type == "bool":
        return True
    if c.type == "date":
        return "2020-01-31"
    if c.type == "datetime":
        return "2020-01-31T10:20:30.123000+00:00"
    return {"a": 1, "b": ["x"]}


def archive_sample(t: Table, id_type: str):
    """(documento, percorso) di un record archiviato di prova: lo stesso in tutti i linguaggi."""
    doc = {}
    for c in t.columns:
        doc[c.name] = TENANT_SAMPLE[id_type] if c.tenant else sample_value(c, c.primary_key)
    tenant = f"tenant={segment(TENANT_SAMPLE[id_type])}/" if t.tenancy != "none" else ""
    return doc, f"{t.db_name}/_keys/{tenant}{segment(doc[t.pk.name])}.json"


# ------------------------------------------------------------------------------------------- configurazione del job

def job_config(t: Table, tables: Dict[str, Table], ac: dict, id_type: str) -> dict:
    tc = tenant_column(t)
    cols = [{"name": c.name, "db_name": c.db_name, "type": c.type, "nullable": c.nullable, "length": c.length,
             "precision": c.precision, "scale": c.scale} for c in t.columns]
    children = [{"table": c.db_name, "column": c.col(r.foreign_key).db_name, "on_delete": r.on_delete}
                for c, r in lifecycle_children(t, tables)]
    doc = {"$comment": f"{MARKER}. NON MODIFICARE: rigenerato da schemas/db/{t.name}.yaml.",
           "table": t.name, "db_name": t.db_name, "key": t.pk.name,
           "tenancy": t.tenancy, "tenant_id_type": id_type, "tenant_column": tc.name if tc else None,
           "age_column": t.archive.on if t.archive else t.retention.on, "columns": cols, "children": children,
           "archive": None, "retention": None,
           "job": {"mode": t.job.mode, "schedule": t.job.schedule, "interval": t.job.interval, "batch_size": t.job.batch_size}}
    if t.archive:
        a = t.archive
        doc["archive"] = {"after": a.after, "target": a.target, "location": ac[a.target], "format": a.format,
                          "partition_by": a.partition_by, "read_through": a.read_through}
    if t.retention:
        doc["retention"] = {"delete_after": t.retention.delete_after}
    return doc


# ------------------------------------------------------------------------------------------- Kubernetes

def _pg_interval(d: str) -> str:
    return f"{d[:-1]} {PG_INTERVAL[d[-1]]}"


def keda_query(t: Table, tables: Dict[str, Table]) -> str:
    """Righe da elaborare, contate dal trigger postgresql di KEDA (stesse condizioni del job)."""
    age = t.col(t.archive.on if t.archive else t.retention.on)
    dur = t.archive.after if t.archive else t.retention.delete_after
    now = "current_date" if age.type == "date" else "now()"
    cond = [f'h."{age.db_name}" < {now} - interval \'{_pg_interval(dur)}\'']
    for c, r in lifecycle_children(t, tables):
        if t.archive or r.on_delete == "restrict":
            cond.append(f'NOT EXISTS (SELECT 1 FROM "{c.db_name}" x WHERE x."{c.col(r.foreign_key).db_name}" = h."{t.pk.db_name}")')
    return f'SELECT count(*) FROM "{t.db_name}" h WHERE ' + " AND ".join(cond)


def _pod(t: Table, ac: dict, loop: bool) -> List[str]:
    loop_arg = ', "--loop"' if loop else ""
    args = f'["run", "/app/jobs/{t.job_name}/config.json"{loop_arg}]'
    o = [f"      serviceAccountName: {ac['service_account']}   # IRSA (S3) o workload identity (Blob)",
         "      securityContext:", "        runAsNonRoot: true", "        runAsUser: 10001",
         "      containers:", "        - name: job", f"          image: {ac['image']}", f"          args: {args}",
         "          env:", "            - name: KYBES_DATABASE_URL",
         f"              valueFrom: {{secretKeyRef: {{name: {ac['db_secret']}, key: url}}}}",
         "            - name: KYBES_TENANTS",
         "              valueFrom: {configMapKeyRef: {name: kybes-jobs, key: tenants, optional: true}}"]
    if t.archive and t.archive.target == "blob":
        o += ["            - name: AZURE_STORAGE_CONNECTION_STRING",
              f"              valueFrom: {{secretKeyRef: {{name: {ac['db_secret']}, key: azure-storage, optional: true}}}}"]
    o += ["          resources:", "            requests: {cpu: 100m, memory: 256Mi}", "            limits: {memory: 1Gi}",
          "          securityContext:", "            allowPrivilegeEscalation: false", "            readOnlyRootFilesystem: true",
          "            capabilities: {drop: [ALL]}"]
    return o


def kubernetes(t: Table, tables: Dict[str, Table], ac: dict) -> str:
    j = t.job
    what = "archiviazione" if t.archive else "conservazione"
    meta = [f"  name: {t.job_name}", f"  namespace: {ac['namespace']}",
            "  labels: {app.kubernetes.io/part-of: kybes, app.kubernetes.io/component: " + f"{what}, kybes.dev/table: {t.name}" + "}"]
    o = [f"# {MARKER}. NON MODIFICARE: rigenerato da schemas/db/{t.name}.yaml.",
         f"# Job di {what} della tabella {t.name}: modalità {j.mode}. Immagine: jobs/generated/_engine/Dockerfile.",
         f"# Segreto {ac['db_secret']}: url (KYBES_DATABASE_URL)" + (", keda (stringa di connessione per KEDA)" if j.mode == "keda" else "")
         + (", azure-storage (facoltativo)" if t.archive and t.archive.target == "blob" else "") + "."]
    cron = ["apiVersion: batch/v1", "kind: CronJob", "metadata:"] + meta[:] + [
        "spec:", f'  schedule: "{j.schedule}"', "  timeZone: Etc/UTC", "  concurrencyPolicy: Forbid", "  startingDeadlineSeconds: 3600",
        "  successfulJobsHistoryLimit: 3", "  failedJobsHistoryLimit: 5", "  jobTemplate:", "    spec:", "      backoffLimit: 2",
        "      activeDeadlineSeconds: 21600", "      template:", "        spec:", "          restartPolicy: Never"]
    cron += ["    " + x for x in _pod(t, ac, False)]
    if j.mode == "cron":
        o += ["---"] + cron
    elif j.mode == "keda":
        query = keda_query(t, tables).replace('"', '\\"')
        o += ["---", "apiVersion: keda.sh/v1alpha1", "kind: TriggerAuthentication", "metadata:", f"  name: {t.job_name}-db",
              f"  namespace: {ac['namespace']}", "spec:", "  secretTargetRef:", "    - parameter: connection", f"      name: {ac['db_secret']}",
              "      key: keda", "---", "apiVersion: keda.sh/v1alpha1", "kind: ScaledJob", "metadata:"] + meta + [
              "spec:", f"  pollingInterval: {j.interval}", "  maxReplicaCount: 1", "  successfulJobsHistoryLimit: 3",
              "  failedJobsHistoryLimit: 5", "  jobTargetRef:", "    backoffLimit: 2", "    activeDeadlineSeconds: 21600", "    template:",
              "      spec:", "        restartPolicy: Never"]
        o += ["  " + x for x in _pod(t, ac, False)]
        o += ["  triggers:", "    - type: postgresql", "      metadata:", f'        query: "{query}"', '        targetQueryValue: "1"',
              f"      authenticationRef: {{name: {t.job_name}-db}}"]
        # passaggio giornaliero di sicurezza: recupero dopo un'interruzione e conservazione dell'archivio anche senza arretrato
        cron[cron.index("  name: " + t.job_name)] = f"  name: {t.job_name}-daily"
        o += ["---", "# Passaggio giornaliero: completa i passaggi interrotti e applica la conservazione anche senza righe in arrivo."] + cron
    else:
        o += ["---", "apiVersion: apps/v1", "kind: Deployment", "metadata:"] + meta + [
              "spec:", "  replicas: 1", "  strategy: {type: Recreate}", "  selector:", f"    matchLabels: {{kybes.dev/job: {t.job_name}}}",
              "  template:", "    metadata:", f"      labels: {{kybes.dev/job: {t.job_name}}}", "    spec:", "      terminationGracePeriodSeconds: 60"]
        o += _pod(t, ac, True)[:]
    return "\n".join(o) + "\n"


# ------------------------------------------------------------------------------------------- query sull'archivio

ATHENA_TYPE = {"uuid": "string", "string": "string", "text": "string", "int": "int", "bigint": "bigint", "bool": "boolean",
               "date": "date", "datetime": "timestamp", "json": "string"}
SYNAPSE_TYPE = {"uuid": "varchar(36)", "text": "varchar(max)", "int": "int", "bigint": "bigint", "bool": "bit", "date": "date",
                "datetime": "datetime2(6)", "json": "varchar(max)"}


def athena(t: Table, ac: dict) -> str:
    a = t.archive
    loc = ac["s3"].rstrip("/")
    base = f"{loc}/{t.db_name}/"
    location = base.split("{tenant}")[0] if "{tenant}" in base else base
    cols = ",\n".join(f"  `{c.db_name}` " + (f"decimal({c.precision},{c.scale})" if c.type == "decimal" else ATHENA_TYPE[c.type])
                      for c in t.columns)
    parts = ", ".join(f"`{p}` {'string' if p == 'tenant' else 'int'}" for p in a.partition_by)
    props = ["'projection.enabled' = 'true'"]
    path = []
    for p in a.partition_by:
        if p == "tenant":
            props.append("'projection.tenant.type' = 'injected'")
        else:
            rng = {"year": "2000,2099", "month": "1,12", "day": "1,31"}[p]
            props += [f"'projection.{p}.type' = 'integer'", f"'projection.{p}.range' = '{rng}'",
                      f"'projection.{p}.digits' = '{4 if p == 'year' else 2}'"]
        path.append(f"{p}=${{{p}}}")
    template = base.replace("{tenant}", "${tenant}") + "".join(x + "/" for x in path)
    props.append(f"'storage.location.template' = '{template}'")
    o = [f"-- {MARKER}. NON MODIFICARE: rigenerato da schemas/db/{t.name}.yaml.",
         f"-- Tabella esterna Athena sui file Parquet dell'archivio di {t.name} (job {t.job_name}).",
         "-- Partition projection: nessun MSCK REPAIR, le partizioni si calcolano dal percorso."]
    if "tenant" in a.partition_by:
        o.append("-- Ogni query deve filtrare per tenant (WHERE tenant = '<id>'): la partizione tenant è 'injected'.")
    o += [f"CREATE EXTERNAL TABLE IF NOT EXISTS `{t.db_name}_archive` (", cols, ")"]
    if parts:
        o.append(f"PARTITIONED BY ({parts})")
    o += ["STORED AS PARQUET", f"LOCATION '{location}'", "TBLPROPERTIES ("] + [",\n".join("  " + p for p in props), ");"]
    return "\n".join(o) + "\n"


def synapse(t: Table, ac: dict) -> str:
    a = t.archive
    loc = ac["blob"].rstrip("/")
    u = urlparse(loc)
    if u.scheme == "az":
        loc = f"https://<account>.blob.core.windows.net/{u.netloc}{u.path}"
    wild = loc.replace("{tenant}", "*") + f"/{t.db_name}/" + "".join(f"{p}=*/" for p in a.partition_by) + "*.parquet"
    stars = (1 if "{tenant}" in loc else 0)
    cols = []
    for c in t.columns:
        typ = f"decimal({c.precision},{c.scale})" if c.type == "decimal" else (f"varchar({c.length})" if c.type == "string" else SYNAPSE_TYPE[c.type])
        cols.append(f"    [{c.db_name}] {typ}")
    sel = ["r.*"]
    for i, p in enumerate(a.partition_by):
        expr = f"r.filepath({stars + i + 1})"
        sel.append(f"{expr} AS [{p}]" if p == "tenant" else f"CAST({expr} AS int) AS [{p}]")
    o = [f"-- {MARKER}. NON MODIFICARE: rigenerato da schemas/db/{t.name}.yaml.",
         f"-- Vista Azure Synapse serverless sui file Parquet dell'archivio di {t.name} (job {t.job_name})."]
    if u.scheme == "az":
        o.append("-- Sostituisci <account> con lo storage account (model.archive.blob con https:// lo indica già).")
    o += [f"CREATE OR ALTER VIEW [dbo].[{t.db_name}_archive] AS", "SELECT " + ", ".join(sel), "FROM OPENROWSET(",
          f"    BULK '{wild}',", "    FORMAT = 'PARQUET'", ") WITH (", ",\n".join(cols), ") AS r;"]
    return "\n".join(o) + "\n"


# ------------------------------------------------------------------------------------------- motore e test

def engine_files() -> Dict[str, str]:
    """Sorgenti del motore (copiati dal kit con l'intestazione dei file generati) e file del pacchetto."""
    out = {}
    for src in sorted((ENGINE_SRC / "kybes_jobs").glob("*.py")) + sorted((ENGINE_SRC / "tests").glob("*.py")):
        rel = src.relative_to(ENGINE_SRC).as_posix()
        out[rel] = header("python", "kit (motore dei job)") + src.read_text(encoding="utf-8")
    out["pyproject.toml"] = f"""# {MARKER}. NON MODIFICARE: rigenerato dal kit.
[project]
name = "kybes-jobs"
version = "1.0.0"
description = "Motore dei job di kybes: archiviazione Parquet su S3 o Blob e conservazione (TTL)"
requires-python = ">=3.10"
dependencies = ["sqlalchemy>=2.0", "pyarrow>=14", "psycopg[binary]>=3.1"]

[project.optional-dependencies]
s3 = ["boto3>=1.28"]
blob = ["azure-storage-blob>=12.19", "azure-identity>=1.15"]
test = ["pytest>=7", "pytest-cov>=4"]

[tool.setuptools]
packages = ["kybes_jobs"]

[tool.pytest.ini_options]
testpaths = ["tests"]
filterwarnings = ["ignore::ResourceWarning"]
"""
    out["Dockerfile"] = f"""# {MARKER}. NON MODIFICARE: rigenerato dal kit.
# Immagine dei job di archiviazione e conservazione. Da costruire nella cartella jobs/generated:
#   docker build -f _engine/Dockerfile -t kybes-jobs:latest jobs/generated
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/jobs/_engine
WORKDIR /app/jobs
COPY _engine/pyproject.toml _engine/pyproject.toml
COPY _engine/kybes_jobs _engine/kybes_jobs
RUN pip install --no-cache-dir "./_engine[s3,blob]"
COPY . .
USER 10001
ENTRYPOINT ["python", "-m", "kybes_jobs"]
"""
    return out


def _child_tests(t: Table, tables: Dict[str, Table]):
    out = []
    for c, r in lifecycle_children(t, tables):
        if c.name == t.name or (not t.archive and r.on_delete != "restrict"):
            continue
        out.append((c, r))
    return out


def table_test(t: Table, tables: Dict[str, Table], asil: str, catalog) -> str:
    name = snake(t.name)
    tcs = {tc.kind if tc.kind != "job_children" else (tc.kind, tc.args["relation"], tc.args["child"]): tc
           for tc in catalog.for_table(t.name, scope="jobs")}

    def doc(tc) -> str:
        from verification import METHODS
        return f'    r"""{tc.id} · {", ".join(tc.reqs)} · {METHODS[tc.method]}: {tc.title}. Atteso: {tc.expected}."""'
    o = [header("python", f"schemas/db/{t.name}.yaml") + "# ruff: noqa",
         f'"""Test del job {t.job_name} (tabella {t.name}, ASIL {asil}) sulla configurazione generata.',
         "", f"Specifica: docs/generated/verification/{t.name}.md. Il motore ha i propri test in test_engine.py.", '"""',
         "import json", "from datetime import timedelta", "from pathlib import Path", "", "import pytest", "",
         "from conftest import NOW, TableEnv", "from kybes_jobs import FileStorage, codec, load_config", "",
         f'CFG = load_config(str(Path(__file__).resolve().parents[2] / "{t.job_name}" / "config.json"))']
    if t.archive:
        tc = tcs["job_archive"]
        o += ["", "", f"def test_{name}_job_archive(db, archive, tmp_path):", doc(tc),
              "    env = TableEnv(CFG, db, archive, tmp_path)", "    old, young = env.row(1, -1), env.row(2, 1)",
              "    env.insert([old, young])", "    rep = env.job().run()",
              "    assert rep.archived_rows == 1 and env.keys() == [env.key(young)]", "    files = env.parquet_files()",
              "    assert len(files) == 1 and files[0].startswith(env.partition_prefix(old))",
              "    assert codec.parquet_keys(CFG, archive.get(files[0])) == (1, [env.key(old)])"]
        if t.archive.read_through:
            o += ["    assert json.loads(archive.get(env.key_path(old))) == json.loads(codec.key_object(CFG, old))"]
        else:
            o += [f"    assert archive.list(\"{t.db_name}/_keys\") == []"]
        tc = tcs["job_safe"]
        o += ["", "", f"def test_{name}_job_safe(db, archive, tmp_path):", doc(tc),
              "    class Broken(FileStorage):", "        def put(self, path, data):", "            if path.endswith('.parquet'):",
              "                raise OSError('archivio non scrivibile')", "            super().put(path, data)", "",
              "    env = TableEnv(CFG, db, archive, tmp_path)", "    old = env.row(1, -1)", "    env.insert([old])",
              "    with pytest.raises(OSError):", "        env.job(storage=Broken(str(archive.root))).run()",
              "    assert env.keys() == [env.key(old)] and archive.list('') == []"]
        if t.retention:
            tc = tcs["job_purge"]
            later = duration_days(t.retention.delete_after) + 400
            o += ["", "", f"def test_{name}_job_retention(db, archive, tmp_path):", doc(tc),
                  "    env = TableEnv(CFG, db, archive, tmp_path)", "    old = env.row(1, -1)", "    env.insert([old])",
                  "    env.job().run()", "    assert len(env.parquet_files()) == 1",
                  f"    rep = env.job(now=NOW + timedelta(days={later})).run()",
                  "    assert rep.deleted_files == 1 and env.parquet_files() == []",
                  "    assert archive.get(env.key_path(old)) is None"]
    else:
        tc = tcs["job_ttl"]
        o += ["", "", f"def test_{name}_job_ttl(db, archive, tmp_path):", doc(tc),
              "    env = TableEnv(CFG, db, archive, tmp_path)", "    old, young = env.row(1, -1), env.row(2, 1)",
              "    env.insert([old, young])", "    rep = env.job().run()",
              "    assert rep.deleted_rows == 1 and env.keys() == [env.key(young)] and archive.list('') == []"]
    for c, r in _child_tests(t, tables):
        tc = tcs[("job_children", r.name, c.name)]
        o += ["", "", f"def test_{name}_job_children_{snake(c.name)}_{snake(r.name)}(db, archive, tmp_path):", doc(tc),
              "    env = TableEnv(CFG, db, archive, tmp_path)", "    parent = env.row(1, -1)", "    env.insert([parent])",
              f"    env.add_child(\"{c.db_name}\", \"{c.col(r.foreign_key).db_name}\", parent)", "    rep = env.job().run()",
              "    assert rep.archived_rows == rep.deleted_rows == 0 and env.keys() == [env.key(parent)]"]
    return "\n".join(o) + "\n"


def emit(tables: Dict[str, Table], mc: dict, catalog, default_asil: str, id_type: str) -> Dict[str, str]:
    """File relativi al progetto. Vuoto se nessuna tabella ha archive o retention."""
    from verification import table_asil
    life = lifecycle_tables(tables)
    if not life:
        return {}
    ac = archive_config(mc)
    jobs = mc.get("jobs_dir", "jobs/generated").rstrip("/")
    db_dir = mc["db_dir"].rstrip("/")
    files = {f"{jobs}/_engine/{rel}": text for rel, text in engine_files().items()}
    for n, t in life.items():
        files[f"{jobs}/{t.job_name}/config.json"] = json.dumps(job_config(t, tables, ac, id_type), indent=2, ensure_ascii=False) + "\n"
        files[f"{jobs}/{t.job_name}/kubernetes.yaml"] = kubernetes(t, tables, ac)
        files[f"{jobs}/_engine/tests/test_{snake(n)}_job.py"] = table_test(t, tables, table_asil(t, default_asil), catalog)
        if t.archive and t.archive.target == "s3":
            files[f"{db_dir}/athena/{n}.sql"] = athena(t, ac)
        elif t.archive:
            files[f"{db_dir}/synapse/{n}.sql"] = synapse(t, ac)
    return files


def max_asil(tables: Dict[str, Table], default: str) -> str:
    return max((t.asil or default for t in tables.values()), key=ASIL.index, default=default)
