#!/usr/bin/env python3
"""Esegue un comando in CI e, se fallisce, ne pubblica l'output come annotazioni GitHub (leggibili via API).

  annotate.py "titolo" [--reports DIR ...] -- comando arg...

Prima annotazione: le righe significative (errori, test falliti, soglie); poi la coda dell'output a blocchi.
Con --reports, i test falliti nei report JUnit XML (surefire) o TRX (dotnet) vanno in annotazioni proprie.
"""
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SUMMARY = re.compile(r"Passed!|Failed!|Tests run:|^# (pass|fail)|verify:|AVVISO|BLOCCANTE|passed|failed")
KEY = re.compile(r"\[ERROR\]|BLOCCANTE|FAIL|Failed|failed|error|Error|Exception|expected|Tests run", re.I)


def esc(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def emit(title: str, msg: str) -> None:
    print(f"::error title={esc(title)}::{esc(msg[:6000])}", flush=True)


def failed_tests(dirs):
    out = []
    for d in dirs:
        for p in sorted(Path(d).rglob("*.xml")) + sorted(Path(d).rglob("*.trx")):
            try:
                root = ET.parse(p).getroot()
            except ET.ParseError:
                continue
            for tc in root.iter("testcase"):  # JUnit
                for f in list(tc.findall("failure")) + list(tc.findall("error")):
                    out.append(f"{tc.get('classname')}.{tc.get('name')}: {f.get('message') or ''}\n{(f.text or '')[:1500]}")
            for r in root.iter():  # TRX
                if r.tag.endswith("UnitTestResult") and r.get("outcome") == "Failed":
                    msg = "".join(e.text or "" for e in r.iter() if e.tag.endswith("Message") or e.tag.endswith("StackTrace"))
                    out.append(f"{r.get('testName')}: {msg[:1500]}")
    return out


def main(argv):
    title, rest = argv[0], argv[1:]
    sep = rest.index("--")
    opts, cmd = rest[:sep], rest[sep + 1:]
    reports = [opts[i + 1] for i, o in enumerate(opts) if o == "--reports"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode == 0:
        # anche quando riesce: una sintesi leggibile via API (numero di test, avvisi, esito della verifica)
        summary = [l for l in r.stdout.splitlines() if SUMMARY.search(l)]
        if summary:
            print(f"::notice title={esc(title + ': esito')}::{esc(chr(10).join(summary)[-3000:])}", flush=True)
        return 0
    lines = r.stdout.splitlines()
    emit(f"{title}: sintesi", "\n".join(l for l in lines if KEY.search(l))[-6000:] or "(nessuna riga significativa)")
    fails = failed_tests(reports)
    for i, f in enumerate(fails[:5]):
        emit(f"{title}: test fallito {i + 1}/{len(fails)}", f)
    tail = r.stdout[-12000:]
    for i in range(0, len(tail), 6000):
        emit(f"{title}: output {i // 6000 + 1}", tail[i:i + 6000])
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
