"""Riga di comando del motore dei job.

  python -m kybes_jobs run <config.json>           un passaggio completo (CronJob, ScaledJob KEDA)
  python -m kybes_jobs run <config.json> --loop    sempre attivo: un passaggio ogni job.interval secondi (Deployment)

Variabili d'ambiente:
  KYBES_DATABASE_URL   database (postgresql://utente:password@host:5432/db); con tenancy database contiene {tenant}
  KYBES_ARCHIVE_URL    location dell'archivio, se diversa da quella della configurazione (es. file:///tmp/archivio)
  KYBES_TENANTS        tenant da elaborare, separati da virgola (obbligatorio con tenancy database)

Codici di uscita: 0 riuscito, 1 errore durante il lavoro, 2 configurazione non valida.
"""
from __future__ import annotations

import json
import signal
import sys
import time
from typing import Callable, List, Optional

from .config import JobError, load_config
from .engine import job_from_env


class _Stop:
    def __init__(self) -> None:
        self.requested = False

    def __call__(self, *_: object) -> None:
        self.requested = True


def main(argv: List[str], sleep: Callable[[float], None] = time.sleep, stop: Optional[_Stop] = None) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2 or args[0] != "run":
        print(__doc__, file=sys.stderr)
        return 2
    try:
        cfg = load_config(args[1])
    except JobError as exc:
        print(json.dumps({"event": "error", "error": str(exc)}), file=sys.stderr)
        return 2
    stop = stop or _Stop()
    if "--loop" in argv:
        signal.signal(signal.SIGTERM, stop)
    while True:
        try:
            job_from_env(cfg).run()
        except Exception as exc:  # noqa: BLE001 - il job registra l'errore ed esce (CronJob/KEDA ritentano)
            print(json.dumps({"event": "error", "table": cfg.table, "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
            if "--loop" not in argv:
                return 1
        if "--loop" not in argv:
            return 0
        for _ in range(cfg.interval):
            if stop.requested:
                return 0
            sleep(1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
