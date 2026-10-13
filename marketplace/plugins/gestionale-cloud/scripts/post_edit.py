#!/usr/bin/env python3
"""PostToolUse su Write/Edit/MultiEdit: avvisi architetturali sul file intero + linter configurati.

Se trova problemi esce con codice 2: lo stderr torna all'agente, che deve correggere.
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys

import hook_common as hc
import model_guard
import rules
from schema import SchemaError

TIMEOUT_S = 90


def run_commands(rel: str, abs_path: str, cfg: dict, proj) -> list:
    problems = []
    for pattern, cmds in (cfg.get("post_edit_commands") or {}).items():
        if not rules.matches(rel, [pattern]):
            continue
        for tmpl in cmds if isinstance(cmds, list) else [cmds]:
            cmd = tmpl.replace("{file}", shlex.quote(abs_path)).replace("{rel}", shlex.quote(rel))
            exe = shlex.split(cmd)[0] if cmd.strip() else ""
            available = (proj / exe).exists() if "/" in exe else shutil.which(exe) is not None
            if not exe or not available:
                continue  # strumento non installato: si salta, ci pensa la CI
            try:
                r = subprocess.run(cmd, shell=True, cwd=str(proj), capture_output=True, text=True, timeout=TIMEOUT_S)
            except subprocess.TimeoutExpired:
                problems.append(f"[AVVISO] comando '{cmd}' oltre {TIMEOUT_S}s")
                continue
            if r.returncode != 0:
                out = (r.stdout + r.stderr).strip()
                problems.append(f"[LINT] {cmd}\n{out[-3000:]}")
    return problems


def main() -> int:
    event = hc.read_event()
    hc.debug_dump(event, "post")
    proj, cfg = hc.project_and_config(event)
    if cfg is None:
        return 0
    path = hc.target_file(event)
    if not path:
        return 0
    rel = rules.rel_to_project(path, proj)
    if rel is None or rules.matches(rel, cfg["paths"].get("ignore", [])):
        return 0
    abs_path = str((proj / rel))

    problems = []
    context = None
    if (cfg.get("model") or {}).get("targets"):
        mc = model_guard.G.model_config(cfg)
        is_schema = rules.matches(rel, [mc["schema_dir"].rstrip("/") + "/*.yaml", mc["schema_dir"].rstrip("/") + "/*.yml"])
        is_custom = any(rel.startswith(d + "/") and "/" not in rel[len(d) + 1:] for _, d in rules.model_target_dirs(cfg))
        if is_schema or is_custom:
            try:
                res = model_guard.G.run(proj, cfg, index_only=not is_schema)
            except SchemaError as exc:
                problems.append("[SCHEMA] lo schema non è valido, nessun file rigenerato:\n  - " + "\n  - ".join(exc.errors))
            else:
                problems += [f"[BLOCCANTE] {p}" for p in res.problems]
                changed = res.written + res.created + res.removed
                if is_schema and changed:
                    context = ("Generatore eseguito automaticamente. File aggiornati: " + ", ".join(changed[:40]) +
                               (" ..." if len(changed) > 40 else "") +
                               ". Non scrivere CRUD o relazioni a mano: sono già nei file generated/. "
                               "Consulta MODEL_INDEX.md per i nomi dei metodi; i metodi custom vanno nel file model/<Tabella>.")
    try:
        content = (proj / rel).read_text(encoding="utf-8", errors="replace")
        problems += [f.format() for f in rules.check_content(rel, content, cfg)]
    except FileNotFoundError:
        return 0
    problems += run_commands(rel, abs_path, cfg, proj)

    if not problems:
        if context:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}}, ensure_ascii=False))
        return 0
    sys.stderr.write(f"Controlli su {rel}:\n" + "\n".join(problems) +
                     "\nCorreggi ora questi punti prima di proseguire.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
