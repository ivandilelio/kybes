"""Parti dei moduli comuni che servono solo alle tabelle SQL, marcate nei modelli dei file generati.

Una riga che contiene SQL_BEGIN apre una parte solo SQL, una che contiene SQL_END la chiude. Le righe dei marcatori
non finiscono mai nei file generati; il contenuto resta se il progetto ha almeno una tabella SQL.
"""
from __future__ import annotations

SQL_BEGIN = "kybes:sql-begin"
SQL_END = "kybes:sql-end"


def strip_sql(text: str, sql: bool) -> str:
    out, skip = [], False
    for line in text.split("\n"):
        if SQL_BEGIN in line:
            skip = not sql
            continue
        if SQL_END in line:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "\n".join(out)


def has_sql(tables) -> bool:
    return any(t.sql_compatible for t in tables.values())
