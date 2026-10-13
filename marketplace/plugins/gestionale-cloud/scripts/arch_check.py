#!/usr/bin/env python3
"""Controllo architetturale dell'intero repository (usato dallo stop gate e dalla CI).

Uso:
  python3 arch_check.py [cartella_progetto] [--strict] [--json]

Esce con 1 se trova violazioni bloccanti (con --strict anche per gli avvisi).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_guard  # noqa: E402
import rules  # noqa: E402


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    strict = "--strict" in argv
    as_json = "--json" in argv
    proj = Path(args[0]).resolve() if args else rules.find_project_dir()
    cfg = rules.load_config(proj)
    if cfg is None:
        print(f"arch_check: nessun {rules.CONFIG_REL} in {proj}, niente da controllare.")
        return 0

    findings = []
    texts = {}
    for rel in rules.iter_project_files(proj, cfg):
        try:
            text = (proj / rel).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        texts[rel] = text
        if rules.GENERATED_MARKER in text[:600]:
            continue  # i file generati li verifica gen --check
        findings += rules.check_content(rel, text, cfg)
    findings += rules.find_duplicates(texts, cfg)
    findings += model_guard.check_repo(proj, cfg)

    blocks = [f for f in findings if f.severity == "block"]
    warns = [f for f in findings if f.severity == "warn"]
    if as_json:
        print(json.dumps([f.__dict__ for f in findings], ensure_ascii=False, indent=2))
    else:
        for f in blocks + warns:
            print(f.format())
        print(f"arch_check: {len(blocks)} bloccanti, {len(warns)} avvisi")
    return 1 if blocks or (strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
