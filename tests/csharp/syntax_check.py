"""Controllo sintattico del C# generato con il parser tree-sitter (non sostituisce il compilatore).

Uso: python3 tests/csharp/syntax_check.py <cartella>
Esce con 1 se un file contiene nodi ERROR o MISSING.
"""
import sys
from pathlib import Path

import tree_sitter as ts
import tree_sitter_c_sharp as tscs

parser = ts.Parser(ts.Language(tscs.language()))
bad = 0
files = sorted(Path(sys.argv[1]).rglob("*.cs"))
for f in files:
    src = f.read_bytes()
    tree = parser.parse(src)
    errors = []
    stack = [tree.root_node]
    while stack:
        n = stack.pop()
        if n.type == "ERROR" or n.is_missing:
            line = src[:n.start_byte].count(b"\n") + 1
            errors.append(f"{f}:{line}: {'manca ' + n.type if n.is_missing else 'errore di sintassi'}: "
                          f"{src.splitlines()[line - 1].decode(errors='replace').strip()[:120]}")
        stack.extend(n.children)
    if errors:
        bad += 1
        print("\n".join(errors[:10]))
print(f"syntax_check: {len(files)} file C#, {bad} con errori")
sys.exit(1 if bad else 0)
