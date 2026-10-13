"""Regole sulla struttura del modello dati: file generati intoccabili, un file per tabella, nomi custom univoci."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "gen"))

import rules  # noqa: E402
from rules import Finding  # noqa: E402

import gen as G  # noqa: E402
from naming import GEN_DIR, MARKER  # noqa: E402
from schema import SchemaError, Table, load_schemas  # noqa: E402

_cache: Dict[str, Optional[Dict[str, Table]]] = {}


def tables(proj: Path, cfg: dict) -> Optional[Dict[str, Table]]:
    """Tabelle dagli schemi; None se gli schemi hanno errori (non si blocca il lavoro per questo)."""
    key = str(proj)
    if key not in _cache:
        try:
            _cache[key] = G.load_tables(proj, cfg)
        except SchemaError:
            _cache[key] = None
    return _cache[key]


def _is_generated_on_disk(p: Path) -> bool:
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            return MARKER in f.read(600)
    except OSError:
        return False


def is_generated_zone(rel: str, cfg: dict) -> bool:
    mc = G.model_config(cfg)
    if rel == mc["index_file"] or rel.startswith(mc["json_schema_dir"].rstrip("/") + "/") or \
            rel.startswith(mc["db_dir"].rstrip("/") + "/"):
        return True
    return any(rel.startswith(f"{d}/{GEN_DIR}/") for _, d in rules.model_target_dirs(cfg))


def expected_name(lang: str) -> str:
    return "<Tabella>Repository.java" if lang == "java" else f"<Tabella>{G.EXT[lang]}"


def check_write(rel: str, fragments: List[str], cfg: dict, proj: Path) -> List[Finding]:
    out: List[Finding] = []
    if not (cfg.get("model") or {}).get("targets"):
        return out
    mc = G.model_config(cfg)
    sev = rules._sev(cfg, "generated_files")
    if sev and (is_generated_zone(rel, cfg) or _is_generated_on_disk(proj / rel)):
        out.append(Finding("generated_files", sev, rel, 0,
                           f"file generato: non si modifica a mano. Cambia lo schema in {mc['schema_dir']}/<Tabella>.yaml: "
                           "il generatore riparte da solo dopo il salvataggio. I metodi custom vanno nel file model/<Tabella>."))
        return out
    for lang, d in rules.model_target_dirs(cfg):
        if not rel.startswith(d + "/"):
            continue
        sub = rel[len(d) + 1:]
        sev = rules._sev(cfg, "model_layout")
        if "/" in sub:
            if sev:
                out.append(Finding("model_layout", sev, rel, 0,
                                   f"nella cartella model non si creano sottocartelle: un solo file per tabella ({expected_name(lang)})."))
            return out
        if lang == "python" and sub == "__init__.py":
            return out
        tn = G.custom_table_of(lang, sub)
        tbs = tables(proj, cfg)
        if tn is None or (tbs is not None and tn not in tbs):
            if sev:
                out.append(Finding("model_layout", sev, rel, 0,
                                   f"nella cartella model esiste solo un file per tabella ({expected_name(lang)}). "
                                   f"Per una tabella nuova crea prima {mc['schema_dir']}/<Tabella>.yaml; "
                                   "per logica che non è accesso ai dati usa il service o libs/utils."))
            return out
        sev = rules._sev(cfg, "custom_method_collision")
        if sev and tbs:
            for frag in fragments:
                for name in G.collisions(lang, tbs[tn], frag):
                    out.append(Finding("custom_method_collision", sev, rel, 0,
                                       f"il metodo '{name}' esiste già tra quelli generati per {tn} (vedi MODEL_INDEX.md): "
                                       "usa quello generato o, se fa altro, dagli un nome che descriva cosa fa."))
        return out
    return out


def check_repo(proj: Path, cfg: dict) -> List[Finding]:
    """File fuori posto nelle cartelle model (per arch_check e CI)."""
    out: List[Finding] = []
    for lang, d in rules.model_target_dirs(cfg):
        root = proj / d
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or "__pycache__" in p.parts:
                continue
            rel = p.relative_to(proj).as_posix()
            if rel.startswith(f"{d}/{GEN_DIR}/"):
                continue
            out += [f for f in check_write(rel, [], cfg, proj) if f.rule == "model_layout"]
    return out + check_custom_tests(proj, cfg)


TEST_EXT = {"python": ".py", "typescript": ".ts", "csharp": ".cs", "java": ".java"}


def check_custom_tests(proj: Path, cfg: dict) -> List[Finding]:
    """Ogni metodo custom del model ha un test in <tests>/custom/ che lo chiama e porta un id TC-<Tabella>-...

    I metodi generati hanno i test generati; quelli scritti a mano devono avere test scritti a mano,
    tracciati con lo stesso schema di identificativi (ISO 26262-6: ogni unità è verificata).
    """
    sev = rules._sev(cfg, "custom_tests")
    tbs = tables(proj, cfg) if sev else None
    if not tbs:
        return []
    out: List[Finding] = []
    for tg in G.model_config(cfg)["targets"]:
        lang, d = tg["lang"], tg["dir"].rstrip("/")
        td, mdir = G.tests_dir(tg), proj / d
        if not td or not mdir.is_dir():
            continue
        cdir = proj / td / "custom"
        tests = [p.read_text(encoding="utf-8", errors="replace") for p in sorted(cdir.rglob("*" + TEST_EXT[lang]))] if cdir.is_dir() else []
        for f in sorted(mdir.iterdir()):
            tn = G.custom_table_of(lang, f.name)
            if not f.is_file() or tn not in tbs:
                continue
            for m in G.scan_methods(lang, f.read_text(encoding="utf-8", errors="replace"), f"{tn}Repository"):
                if any(f"TC-{tn}-" in t and re.search(rf"\b{re.escape(m)}\b", t) for t in tests):
                    continue
                out.append(Finding("custom_tests", sev, f"{d}/{f.name}", 0,
                                   f"il metodo custom '{m}' di {tn} non ha un test: scrivilo in {td}/custom/ "
                                   f"con un identificativo TC-{tn}-<CASO> e il requisito REQ-{tn}-<CHIAVE> che verifica "
                                   "(vedi docs/generated/verification/ per i metodi di derivazione)."))
    return out
