#!/usr/bin/env python3
"""Stop / SubagentStop: impedisce di chiudere il lavoro finché i controlli non passano.

Esegue arch_check sull'intero progetto e i comandi in stop_gate.commands.
Protezione anti-loop: dopo max_blocks rifiuti consecutivi nella stessa sessione lascia chiudere
con un avviso, così l'agente non resta bloccato all'infinito.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import hook_common as hc
import model_guard
import rules
from schema import SchemaError

TIMEOUT_S = 600
HERE = Path(__file__).resolve().parent


def has_changes(proj: Path) -> bool:
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=str(proj), capture_output=True, text=True, timeout=30)
    except Exception:
        return True
    if r.returncode != 0:
        return True  # non è un repo git: controlliamo comunque
    return bool(r.stdout.strip())


def counter_path(event: dict) -> Path:
    sid = "".join(c for c in str(event.get("session_id", "nosession")) if c.isalnum() or c in "-_")[:80]
    kind = "sub" if event.get("hook_event_name") == "SubagentStop" else "main"
    return Path(tempfile.gettempdir()) / f"kybes-stop-{sid}-{kind}.count"


def main() -> int:
    event = hc.read_event()
    hc.debug_dump(event, "stop")
    proj, cfg = hc.project_and_config(event)
    if cfg is None:
        return 0
    gate = cfg.get("stop_gate") or {}
    if not gate.get("enabled", True):
        return 0
    if event.get("stop_hook_active") is True:
        return 0  # se il campo esiste, Claude Code segnala che stiamo già continuando per colpa di un hook
    if gate.get("only_if_changes", True) and not has_changes(proj):
        return 0

    cnt_file = counter_path(event)
    try:
        count = int(cnt_file.read_text())
    except Exception:
        count = 0
    max_blocks = int(gate.get("max_blocks", 3))

    failures = []
    arch = subprocess.run([sys.executable, "-B", str(HERE / "arch_check.py"), str(proj)],
                          capture_output=True, text=True, timeout=TIMEOUT_S)
    if arch.returncode != 0:
        failures.append("arch_check:\n" + (arch.stdout + arch.stderr).strip()[-4000:])
    if (cfg.get("model") or {}).get("targets"):
        try:
            res = model_guard.G.run(proj, cfg, check=True)
            issues = res.stale + res.problems
            if issues:
                failures.append("generatore (gen --check): esegui python3 <kit>/scripts/gen/gen.py .\n" + "\n".join(issues[:40]))
        except SchemaError as exc:
            failures.append("schemi non validi:\n" + "\n".join(exc.errors))
    for cmd in gate.get("commands") or []:
        try:
            r = subprocess.run(cmd, shell=True, cwd=str(proj), capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            failures.append(f"{cmd}: oltre {TIMEOUT_S}s")
            continue
        if r.returncode != 0:
            failures.append(f"{cmd}:\n" + (r.stdout + r.stderr).strip()[-4000:])

    if not failures:
        try:
            cnt_file.unlink()
        except FileNotFoundError:
            pass
        return 0

    if count >= max_blocks:
        try:
            cnt_file.unlink()
        except FileNotFoundError:
            pass
        sys.stderr.write(f"kybes: controlli ancora falliti dopo {max_blocks} tentativi, chiusura consentita. "
                         "Rivedi a mano:\n" + "\n\n".join(failures) + "\n")
        return 0

    cnt_file.write_text(str(count + 1))
    reason = ("Il lavoro non può essere chiuso: i controlli del progetto falliscono "
              f"(tentativo {count + 1}/{max_blocks}). Correggi e riprova.\n\n" + "\n\n".join(failures))
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
