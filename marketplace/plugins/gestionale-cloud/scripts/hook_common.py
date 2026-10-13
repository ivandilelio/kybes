"""Utility comuni agli hook: lettura stdin, progetto, estrazione dei contenuti scritti."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules  # noqa: E402


def read_event() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def project_and_config(event: dict) -> Tuple[Path, Optional[dict]]:
    proj = rules.find_project_dir(event.get("cwd"))
    return proj, rules.load_config(proj)


def target_file(event: dict) -> Optional[str]:
    ti = event.get("tool_input") or {}
    tr = event.get("tool_response") or {}
    for src in (ti, tr if isinstance(tr, dict) else {}):
        for key in ("file_path", "filePath", "path", "notebook_path"):
            if isinstance(src.get(key), str):
                return src[key]
    return None


def written_fragments(event: dict) -> List[str]:
    """Testo che lo strumento sta per scrivere (Write: intero file; Edit/MultiEdit: le parti nuove)."""
    ti = event.get("tool_input") or {}
    frags: List[str] = []
    for key in ("content", "new_string", "new_source"):
        if isinstance(ti.get(key), str):
            frags.append(ti[key])
    for e in ti.get("edits") or []:
        if isinstance(e, dict) and isinstance(e.get("new_string"), str):
            frags.append(e["new_string"])
    return frags


def debug_dump(event: dict, name: str) -> None:
    """Con GESTIONALE_HOOK_DEBUG=1 salva il payload ricevuto, utile per verificare i campi."""
    if os.environ.get("GESTIONALE_HOOK_DEBUG") == "1":
        import tempfile
        p = Path(tempfile.gettempdir()) / f"gestionale-hook-{name}.json"
        try:
            p.write_text(json.dumps(event, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
