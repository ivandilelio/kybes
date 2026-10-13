#!/usr/bin/env python3
"""Verifica di unità del modello dati (ISO 26262-6, 9.4): esegue i test generati e custom, misura la copertura
strutturale e la confronta con le soglie dell'ASIL di ogni tabella.

  verify.py [progetto] [--lang=python,typescript] [--gate-only] [--quiet]

Per ogni linguaggio del modello con test generati:
  python      pytest + pytest-cov nella cartella del pacchetto (es. libs/db-models/python)
  typescript  tsc + c8 + node --test nella cartella del pacchetto (es. libs/db-models/typescript)
I report Cobertura vanno in coverage/<lingua>.cobertura.xml. Con --gate-only si controllano solo i report
già presenti (verification.coverage_reports), utile per i linguaggi che la CI misura con i propri strumenti
(coverlet per C#, JaCoCo convertito in Cobertura per Java).

Uscita: 0 se test e soglie sono rispettati; 1 se un test fallisce o una soglia non è raggiunta.
Un linguaggio senza strumenti installati viene segnalato e saltato, non fa fallire.
"""
from __future__ import annotations

import glob
import json
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
            fc.lines_hit += int(ln.get("hits", "0")) > 0
            if ln.get("branch") == "true":
                m = _COND.search(ln.get("condition-coverage", ""))
                if m:
                    fc.branches_hit += int(m.group(1))
                    fc.branches += int(m.group(2))
    return out


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
        tn = stem[: -len("Repository")] if stem.endswith("Repository") and stem[: -len("Repository")] in tables else stem
        if tn in tables:
            return table_asil(tables[tn], default), tn
        top = max((table_asil(t, default) for t in tables.values()), key=ASIL.index, default=default)
        return top, "moduli comuni"
    return None


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
                fails.append(f"{rel}: copertura {kind} {p:.1f}% sotto la soglia {want}% (ASIL {asil}, {subj})")
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
               "node", "--enable-source-maps", "--test", *[str(Path(f).relative_to(pkg)) for f in files]], pkg, quiet)
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


RUNNERS = {"python": run_python, "typescript": run_typescript}


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
        tables = load_schemas(proj / mc["schema_dir"])
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
            report = cov_dir / f"{lang}.cobertura.xml"
            if report.exists():
                report.unlink()
            RUNNERS[lang](proj, tg, report, quiet, out)
            if report.exists():
                ran.append((lang, tg["dir"].rstrip("/") + "/", report))
    covs: Dict[str, FileCov] = {}
    reports = sorted({Path(p) for pat in vc.get("coverage_reports") or ["coverage/*.cobertura.xml"]
                      for p in glob.glob(str(proj / pat))})
    for rp in reports:
        try:
            covs.update(parse_cobertura(rp, proj))
        except (ET.ParseError, OSError) as exc:
            out.failures.append(f"report di copertura illeggibile {rp.relative_to(proj)}: {exc}")
    for lang, d, rp in ran:
        if not any(k.startswith(d) for k in covs):
            out.failures.append(f"{lang}: {rp.relative_to(proj)} non contiene file di {d} "
                                "(per TypeScript serve sourceMap: true nel tsconfig): copertura non verificabile")
    fails, rows = gate(covs, mc["targets"], tables, vc)
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
