#!/usr/bin/env python3
"""Verifica di unità del modello dati (ISO 26262-6, 9.4): esegue i test generati e custom, misura la copertura
strutturale e la confronta con le soglie dell'ASIL di ogni tabella.

  verify.py [progetto] [--lang=python,typescript] [--gate-only] [--quiet]

Per ogni linguaggio del modello con test generati:
  python      pytest + pytest-cov nella cartella del pacchetto (es. libs/db-models/python)
  typescript  tsc + c8 + node --test nella cartella del pacchetto (es. libs/db-models/typescript)
  java        mvn test con JaCoCo (es. libs/db-models/java), su PostgreSQL (KYBES_TEST_DATABASE_URL)
  csharp      dotnet test con coverlet (es. libs/db-models/csharp/tests), su PostgreSQL (KYBES_TEST_DATABASE_URL)
  jobs        pytest + pytest-cov sul motore dei job (jobs/generated/_engine), se una tabella ha archive o retention
I report vanno in coverage/: <lingua>.cobertura.xml, java.jacoco.xml. Con --gate-only si controllano solo i report
già presenti (verification.coverage_reports), per esempio prodotti da una CI con i propri strumenti.

Uscita: 0 se test e soglie sono rispettati; 1 se un test fallisce o una soglia non è raggiunta.
Un linguaggio senza strumenti installati viene segnalato e saltato, non fa fallire.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "gen"))

import rules  # noqa: E402
import gen as G  # noqa: E402
from schema import ASIL, SchemaError, load_schemas  # noqa: E402
from verification import table_asil  # noqa: E402

RUNTIME_STEMS = {"_paging", "_uow", "_base", "__init__", "index", "Paging", "UnitOfWork", "ModelBase", "package-info"}


@dataclass
class FileCov:
    path: str
    lines: int = 0
    lines_hit: int = 0
    branches: int = 0
    branches_hit: int = 0
    missed: List[int] = field(default_factory=list)
    partial: List[int] = field(default_factory=list)

    def pct(self, kind: str) -> Optional[float]:
        tot, hit = (self.lines, self.lines_hit) if kind == "statement" else (self.branches, self.branches_hit)
        return None if tot == 0 else 100.0 * hit / tot


@dataclass
class Outcome:
    failures: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------------- Cobertura

_COND = re.compile(r"\((\d+)/(\d+)\)")


def parse_cobertura(xml_path: Path, proj: Path) -> Dict[str, FileCov]:
    """{percorso relativo al progetto: copertura}, sommando le classi dello stesso file."""
    root = ET.parse(xml_path).getroot()
    sources = [Path(s.text.strip()) for s in root.iter("source") if s.text and s.text.strip()] or [xml_path.parent]
    out: Dict[str, FileCov] = {}
    for cls in root.iter("class"):
        fn = cls.get("filename") or ""
        rel = _resolve(fn, sources, xml_path, proj)
        fc = out.setdefault(rel, FileCov(rel))
        seen = set()
        for ln in cls.iter("line"):
            num = ln.get("number")
            if num in seen:
                continue
            seen.add(num)
            fc.lines += 1
            if int(ln.get("hits", "0")) > 0:
                fc.lines_hit += 1
            else:
                fc.missed.append(int(num))
            if (ln.get("branch") or "").lower() == "true":
                m = _COND.search(ln.get("condition-coverage", ""))
                if m:
                    fc.branches_hit += int(m.group(1))
                    fc.branches += int(m.group(2))
                    if m.group(1) != m.group(2):
                        fc.partial.append(int(num))
    return out


def parse_jacoco(xml_path: Path, proj: Path, targets: List[dict]) -> Dict[str, FileCov]:
    """Report XML di JaCoCo: percorsi package/File.java risolti sotto le cartelle src/main/java dei target Java."""
    roots = sorted({proj / tg["dir"].split("/src/main/java/")[0] / "src" / "main" / "java"
                    for tg in targets if tg["lang"] == "java" and "/src/main/java/" in tg["dir"]})
    out: Dict[str, FileCov] = {}
    for pkg in ET.parse(xml_path).getroot().iter("package"):
        for sf in pkg.iter("sourcefile"):
            name = f"{pkg.get('name')}/{sf.get('name')}"
            hit = next((r / name for r in roots if (r / name).exists()), None)
            rel = hit.relative_to(proj).as_posix() if hit else name
            fc = out.setdefault(rel, FileCov(rel))
            for ln in sf.iter("line"):
                fc.lines += 1
                if int(ln.get("ci", "0")) > 0:
                    fc.lines_hit += 1
                else:
                    fc.missed.append(int(ln.get("nr", "0")))
                mb, cb = int(ln.get("mb", "0")), int(ln.get("cb", "0"))
                fc.branches += mb + cb
                fc.branches_hit += cb
                if mb:
                    fc.partial.append(int(ln.get("nr", "0")))
    return out


def parse_report(xml_path: Path, proj: Path, targets: List[dict]) -> Dict[str, FileCov]:
    root = ET.parse(xml_path).getroot()
    return parse_jacoco(xml_path, proj, targets) if root.tag == "report" else parse_cobertura(xml_path, proj)


def _resolve(fn: str, sources: List[Path], xml_path: Path, proj: Path) -> str:
    cands = [Path(fn)] if Path(fn).is_absolute() else [s / fn for s in sources] + [xml_path.parent / fn, proj / fn]
    for c in cands:
        try:
            if c.exists():
                return c.resolve().relative_to(proj.resolve()).as_posix()
        except ValueError:
            continue
    return fn.replace("\\", "/")


# ------------------------------------------------------------------------------------------- soglie

def file_asil(rel: str, targets: List[dict], tables: dict, default: str) -> Optional[Tuple[str, str]]:
    """(ASIL, soggetto) per un file del modello; None se il file non è nel modello."""
    for tg in targets:
        d = tg["dir"].rstrip("/") + "/"
        if not rel.startswith(d):
            continue
        name = rel.rsplit("/", 1)[-1]
        stem = name.split(".", 1)[0]
        top = max((table_asil(t, default) for t in tables.values()), key=ASIL.index, default=default)
        if tg["lang"] == "jobs":
            return top, "motore dei job"
        tn = stem
        for suffix in ("RepositoryBase", "Repository"):
            if stem.endswith(suffix) and stem[: -len(suffix)] in tables:
                tn = stem[: -len(suffix)]
        if tn in tables:
            return table_asil(tables[tn], default), tn
        return top, "moduli comuni"
    return None


def _ranges(nums: List[int]) -> str:
    out, ns = [], sorted(set(nums))
    i = 0
    while i < len(ns):
        j = i
        while j + 1 < len(ns) and ns[j + 1] == ns[j] + 1:
            j += 1
        out.append(str(ns[i]) if i == j else f"{ns[i]}-{ns[j]}")
        i = j + 1
    return ", ".join(out) or "-"


def gate(covs: Dict[str, FileCov], targets: List[dict], tables: dict, vc: dict) -> Tuple[List[str], List[str]]:
    fails, rows = [], []
    for rel in sorted(covs):
        a = file_asil(rel, targets, tables, vc["asil"])
        if a is None:
            continue
        asil, subj = a
        th = vc["thresholds"].get(asil) or {}
        fc = covs[rel]
        parts = []
        for kind in ("statement", "branch"):
            p = fc.pct(kind)
            want = th.get(kind)
            parts.append(f"{kind} {'-' if p is None else f'{p:.1f}%'}")
            if want is not None and p is not None and p + 1e-9 < want:
                where = _ranges(fc.missed) if kind == "statement" else _ranges(fc.partial)
                label = "righe non eseguite" if kind == "statement" else "righe con rami non percorsi"
                fails.append(f"{rel}: copertura {kind} {p:.1f}% sotto la soglia {want}% (ASIL {asil}, {subj}); {label}: {where}")
        rows.append(f"  {rel} [ASIL {asil}] " + ", ".join(parts))
    return fails, rows


# ------------------------------------------------------------------------------------------- esecuzione

def _run(cmd: List[str], cwd: Path, quiet: bool) -> int:
    if not quiet:
        print("$ " + " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE if quiet else None, stderr=subprocess.STDOUT if quiet else None, text=True)
    if quiet and r.returncode != 0:
        print(r.stdout[-6000:])
    return r.returncode


def run_python(proj: Path, tg: dict, report: Path, quiet: bool, out: Outcome) -> None:
    td = G.tests_dir(tg)
    pkg = proj / Path(td).parent
    try:
        import pytest  # noqa: F401
        import pytest_cov  # noqa: F401
    except ImportError:
        out.notes.append("python: pytest e pytest-cov non installati (pip install pytest pytest-cov): test non eseguiti")
        return
    model_rel = Path(tg["dir"]).relative_to(Path(td).parent).as_posix()
    rc = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--cov={model_rel}", "--cov-branch",
               f"--cov-report=xml:{report}", Path(td).name], pkg, quiet)
    if rc != 0:
        out.failures.append(f"python: test falliti in {td} (pytest esce con {rc})")


def jobs_target(proj: Path, mc: dict, tables: dict) -> Optional[dict]:
    """Il motore dei job come obiettivo di verifica, se il progetto ha tabelle con archive o retention."""
    if not any(t.archive or t.retention for t in tables.values()):
        return None
    d = mc.get("jobs_dir", "jobs/generated").rstrip("/") + "/_engine"
    return {"lang": "jobs", "dir": d + "/kybes_jobs"} if (proj / d).is_dir() else None


def run_jobs(proj: Path, tg: dict, report: Path, quiet: bool, out: Outcome) -> None:
    pkg = proj / Path(tg["dir"]).parent
    try:
        import pyarrow  # noqa: F401
        import pytest  # noqa: F401
        import pytest_cov  # noqa: F401
        import sqlalchemy  # noqa: F401
    except ImportError:
        rel = pkg.relative_to(proj).as_posix()
        out.notes.append(f"jobs: dipendenze del motore non installate (pip install -e \"{rel}[test]\"): test non eseguiti")
        return
    rc = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--cov=kybes_jobs", "--cov-branch",
               f"--cov-report=xml:{report}", "tests"], pkg, quiet)
    if rc != 0:
        out.failures.append(f"jobs: test falliti in {pkg.relative_to(proj).as_posix()}/tests (pytest esce con {rc})")


def run_typescript(proj: Path, tg: dict, report: Path, quiet: bool, out: Outcome) -> None:
    td = G.tests_dir(tg)
    pkg = proj / Path(td).parent
    bins = pkg / "node_modules" / ".bin"
    if not shutil.which("node") or not (bins / "tsc").exists() or not (bins / "c8").exists():
        out.notes.append(f"typescript: servono node e, in {pkg.relative_to(proj)}, typescript e c8 (npm install): test non eseguiti")
        return
    if not (pkg / "tsconfig.json").exists():
        out.notes.append(f"typescript: manca {pkg.relative_to(proj)}/tsconfig.json: test non eseguiti")
        return
    outdir = _ts_outdir(pkg / "tsconfig.json")
    if _run([str(bins / "tsc"), "-p", "."], pkg, quiet) != 0:
        out.failures.append(f"typescript: compilazione fallita in {pkg.relative_to(proj)}")
        return
    files = sorted(glob.glob(str(pkg / outdir / "**" / "tests" / "**" / "*.test.js"), recursive=True)) or \
        sorted(glob.glob(str(pkg / outdir / "**" / "*.test.js"), recursive=True))
    if not files:
        out.failures.append(f"typescript: nessun test compilato in {pkg.relative_to(proj)}/{outdir}")
        return
    tmp = report.parent / ".c8-typescript"
    rc = _run([str(bins / "c8"), "--reporter=cobertura", "--report-dir", str(tmp), "--exclude", "**/tests/**",
               "node", "--enable-source-maps", "--test", "--test-concurrency=1", *[str(Path(f).relative_to(pkg)) for f in files]], pkg, quiet)
    if (tmp / "cobertura-coverage.xml").exists():
        shutil.move(str(tmp / "cobertura-coverage.xml"), report)
    shutil.rmtree(tmp, ignore_errors=True)
    if rc != 0:
        out.failures.append(f"typescript: test falliti in {td} (node --test esce con {rc})")


def _ts_outdir(path: Path) -> str:
    try:
        text = re.sub(r"//[^\n]*|/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        return (json.loads(text).get("compilerOptions") or {}).get("outDir", "dist").strip("./") or "dist"
    except (OSError, ValueError):
        return "dist"


def _db_url(lang: str, out: Outcome) -> bool:
    if os.environ.get("KYBES_TEST_DATABASE_URL"):
        return True
    out.notes.append(f"{lang}: imposta KYBES_TEST_DATABASE_URL (PostgreSQL di test, es. postgresql://kybes:kybes@localhost:5432/kybes): test non eseguiti")
    return False


def run_java(proj: Path, tg: dict, report: Path, quiet: bool, out: Outcome) -> None:
    pkg = proj / tg["dir"].split("/src/main/java/")[0]
    mvn = shutil.which("mvn")
    if not mvn or not (pkg / "pom.xml").exists():
        out.notes.append(f"java: servono Maven e {pkg.relative_to(proj)}/pom.xml (creato da install.sh --scaffold): test non eseguiti")
        return
    if not _db_url("java", out):
        return
    rc = _run([mvn, "-q", "-B", "-ntp", "test"], pkg, quiet)
    jacoco = pkg / "target" / "site" / "jacoco" / "jacoco.xml"
    if jacoco.exists():
        shutil.copy(jacoco, report)
    if rc != 0:
        out.failures.append(f"java: test falliti in {pkg.relative_to(proj)} (mvn test esce con {rc})")


def run_csharp(proj: Path, tg: dict, report: Path, quiet: bool, out: Outcome) -> None:
    td = proj / G.tests_dir(tg)
    dotnet = shutil.which("dotnet")
    projs = sorted(td.glob("*.csproj"))
    if not dotnet or not projs:
        out.notes.append(f"csharp: servono il .NET SDK e un progetto di test in {td.relative_to(proj)} (creato da install.sh --scaffold): test non eseguiti")
        return
    if not _db_url("csharp", out):
        return
    tmp = report.parent / ".coverlet-csharp"
    shutil.rmtree(tmp, ignore_errors=True)
    rc = _run([dotnet, "test", str(projs[0]), "--nologo", "--collect:XPlat Code Coverage", "--results-directory", str(tmp)], td, quiet)
    found = sorted(tmp.rglob("coverage.cobertura.xml"))
    if found:
        shutil.move(str(found[0]), report)
    shutil.rmtree(tmp, ignore_errors=True)
    if rc != 0:
        out.failures.append(f"csharp: test falliti in {td.relative_to(proj)} (dotnet test esce con {rc})")


RUNNERS = {"python": run_python, "typescript": run_typescript, "java": run_java, "csharp": run_csharp}
REPORT = {"java": "java.jacoco.xml"}
DEFAULT_REPORTS = ["coverage/*.cobertura.xml", "coverage/*.jacoco.xml"]


def main(argv: List[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    quiet, gate_only = "--quiet" in argv, "--gate-only" in argv
    only = None
    for a in argv:
        if a.startswith("--lang="):
            only = set(a.split("=", 1)[1].split(","))
    proj = Path(args[0]).resolve() if args else rules.find_project_dir()
    cfg = rules.load_config(proj)
    if cfg is None:
        print(f"verify: nessun {rules.CONFIG_REL} in {proj}")
        return 0
    mc, vc = G.model_config(cfg), G.verification_config(cfg)
    try:
        tables = G.load_tables(proj, cfg)
    except SchemaError as exc:
        print("verify: schemi non validi: " + "; ".join(exc.errors), file=sys.stderr)
        return 1
    if not tables:
        return 0
    out = Outcome()
    cov_dir = proj / "coverage"
    ran: List[Tuple[str, str, Path]] = []
    if not gate_only and vc.get("generate_tests", True):
        for tg in mc["targets"]:
            lang = tg["lang"]
            if (only and lang not in only) or lang not in RUNNERS or not G.tests_dir(tg):
                continue
            cov_dir.mkdir(exist_ok=True)
            report = cov_dir / REPORT.get(lang, f"{lang}.cobertura.xml")
            if report.exists():
                report.unlink()
            RUNNERS[lang](proj, tg, report, quiet, out)
            if report.exists():
                ran.append((lang, tg["dir"].rstrip("/") + "/", report))
    jt = jobs_target(proj, mc, tables)
    targets = mc["targets"] + ([jt] if jt else [])
    if jt and not gate_only and (not only or "jobs" in only):
        cov_dir.mkdir(exist_ok=True)
        report = cov_dir / "jobs.cobertura.xml"
        if report.exists():
            report.unlink()
        run_jobs(proj, jt, report, quiet, out)
        if report.exists():
            ran.append(("jobs", jt["dir"] + "/", report))
    covs: Dict[str, FileCov] = {}
    reports = sorted({Path(p) for pat in vc.get("coverage_reports") or DEFAULT_REPORTS
                      for p in glob.glob(str(proj / pat))})
    for rp in reports:
        try:
            covs.update(parse_report(rp, proj, targets))
        except (ET.ParseError, OSError) as exc:
            out.failures.append(f"report di copertura illeggibile {rp.relative_to(proj)}: {exc}")
    for lang, d, rp in ran:
        if not any(k.startswith(d) for k in covs):
            out.failures.append(f"{lang}: {rp.relative_to(proj)} non contiene file di {d} "
                                "(per TypeScript serve sourceMap: true nel tsconfig): copertura non verificabile")
    fails, rows = gate(covs, targets, tables, vc)
    out.failures += fails
    if not quiet and rows:
        print("Copertura strutturale per file del modello:")
        print("\n".join(rows))
    for n in out.notes:
        print(f"[AVVISO] {n}")
    for f in out.failures:
        print(f"[BLOCCANTE] {f}", file=sys.stderr)
    if not out.failures and not quiet:
        print(f"verify: {len(rows)} file del modello entro le soglie ASIL" if rows else "verify: nessun report di copertura")
    return 1 if out.failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
