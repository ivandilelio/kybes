#!/usr/bin/env python3
"""PreToolUse su Write/Edit/MultiEdit: nega le scritture che violano regole bloccanti."""
from __future__ import annotations

import json
import sys

import hook_common as hc
import model_guard
import rules


def main() -> int:
    event = hc.read_event()
    hc.debug_dump(event, "pre")
    proj, cfg = hc.project_and_config(event)
    if cfg is None:
        return 0  # progetto senza kit: nessun controllo
    path = hc.target_file(event)
    if not path:
        return 0
    rel = rules.rel_to_project(path, proj)
    if rel is None:
        return 0

    frags = hc.written_fragments(event)
    findings = rules.check_protected(rel, cfg)
    findings += model_guard.check_write(rel, frags, cfg, proj)
    for frag in frags:
        findings += rules.check_content(rel, frag, cfg)
    blocking = [f for f in findings if f.severity == "block"]
    if not blocking:
        return 0

    reason = "Scrittura rifiutata dalle regole architetturali del progetto:\n" + "\n".join(
        f.format() for f in blocking) + "\nCorreggi l'approccio invece di aggirare il controllo."
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
