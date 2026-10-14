"""Lettore YAML minimale per gli schemi delle tabelle e il contratto OpenAPI (usato solo se PyYAML non è installato).

Supporta il sottoinsieme usato in schemas/: mappe, liste con "- ", liste inline [a, b], mappe inline
{ chiave: valore } (anche annidate), stringhe (anche tra virgolette), interi, decimali, booleani, null, commenti "#",
chiavi con / { } $ o tra virgolette (percorsi OpenAPI, $ref, '200') e blocchi di testo | e >.
"""
from __future__ import annotations

import re
from typing import Any, List, Tuple


class YamlError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for i, c in enumerate(line):
        if quote:
            if c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(c)
    return "".join(out).rstrip()


def _scalar(tok: str) -> Any:
    t = tok.strip()
    if t == "":
        return None
    if (t[0] == t[-1]) and t[0] in ("'", '"') and len(t) >= 2:
        return t[1:-1]
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        return [] if not inner else [_scalar(x) for x in _split_inline(inner)]
    if t.startswith("{") and t.endswith("}"):
        inner = t[1:-1].strip()
        out = {}
        for part in (_split_inline(inner) if inner else []):
            kv = _split_inline(part, ":", 1)
            if len(kv) != 2:
                raise YamlError(f"mappa inline non valida: '{t}'")
            out[_scalar(kv[0])] = _scalar(kv[1])
        return out
    low = t.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?\d+\.\d+", t):
        return float(t)
    return t


def _split_inline(s: str, sep: str = ",", maxsplit: int = -1) -> List[str]:
    """Divide su sep fuori da virgolette, [ ] e { }."""
    parts, cur, quote, depth = [], [], None, 0
    for c in s:
        if quote:
            cur.append(c)
            if c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c
            cur.append(c)
        elif c in "[{":
            depth += 1
            cur.append(c)
        elif c in "]}":
            depth -= 1
            cur.append(c)
        elif c == sep and depth == 0 and maxsplit != 0:
            parts.append("".join(cur))
            cur = []
            maxsplit -= 1
        else:
            cur.append(c)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


def _key_colon(text: str) -> int:
    """Posizione del ':' che separa chiave e valore (seguito da spazio o fine riga, fuori da virgolette e parentesi); -1 se manca."""
    quote, depth = None, 0
    for i, c in enumerate(text):
        if quote:
            if c == quote:
                quote = None
        elif c in ("'", '"') and i == 0:
            quote = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif c == ":" and depth == 0 and (i + 1 == len(text) or text[i + 1] in " \t"):
            return i
    return -1


def _is_key_line(text: str) -> bool:
    return not text.startswith(("[", "{", "- ")) and _key_colon(text) > 0


def _split_key(text: str, lineno: int) -> Tuple[str, str]:
    i = _key_colon(text) if not text.startswith(("[", "{")) else -1
    if i <= 0:
        raise YamlError(f"riga {lineno}: atteso 'chiave: valore', trovato '{text}'")
    key = text[:i].strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
        key = key[1:-1]
    return key, text[i + 1:].strip()


def loads(text: str) -> Any:
    lines: List[Tuple[int, str, int]] = []
    raw_lines = text.splitlines()
    block_indent = None  # dentro un blocco di testo | o >: le righe restano com'erano
    for n, raw in enumerate(raw_lines, 1):
        ind = len(raw) - len(raw.lstrip(" "))
        if block_indent is not None:
            if raw.strip() == "" or ind > block_indent:
                lines.append((ind, "\0" + raw, n))
                continue
            block_indent = None
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError(f"riga {n}: usa spazi, non tabulazioni, per l'indentazione")
        s = _strip_comment(raw)
        if s.strip() in ("", "---"):
            continue
        lines.append((ind, s.strip(), n))
        if re.search(r":\s+[|>][+-]?$", s) or re.match(r"^-\s+[|>][+-]?$", s.strip()):
            block_indent = ind
    if not lines:
        return {}
    value, pos = _block(lines, 0, lines[0][0])
    if pos != len(lines):
        raise YamlError(f"riga {lines[pos][2]}: indentazione non valida")
    return value


def _block(lines, pos, indent):
    if lines[pos][1].startswith("- ") or lines[pos][1] == "-":
        return _seq(lines, pos, indent)
    return _map(lines, pos, indent)


def _map(lines, pos, indent):
    out = {}
    while pos < len(lines):
        ind, text, n = lines[pos]
        if ind < indent:
            break
        if ind > indent:
            raise YamlError(f"riga {n}: indentazione inattesa")
        if text.startswith("- "):
            break
        key, rest = _split_key(text, n)
        if key in out:
            raise YamlError(f"riga {n}: chiave '{key}' ripetuta")
        pos += 1
        if re.fullmatch(r"[|>][+-]?", rest):
            out[key], pos = _text_block(lines, pos, indent, rest)
        elif rest:
            out[key] = _scalar(rest)
        elif pos < len(lines) and lines[pos][0] > indent:
            out[key], pos = _block(lines, pos, lines[pos][0])
        elif pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
            out[key], pos = _seq(lines, pos, indent)
        else:
            out[key] = None
    return out, pos


def _seq(lines, pos, indent):
    out = []
    while pos < len(lines):
        ind, text, n = lines[pos]
        if ind != indent or not (text.startswith("- ") or text == "-"):
            if ind > indent:
                raise YamlError(f"riga {n}: indentazione inattesa")
            break
        item = text[1:].strip()
        if not item:
            pos += 1
            val, pos = _block(lines, pos, lines[pos][0]) if pos < len(lines) and lines[pos][0] > indent else (None, pos)
            out.append(val)
            continue
        if _is_key_line(item):
            # elemento mappa: la prima chiave sta sulla riga del trattino
            child_indent = ind + (len(text) - len(item))
            lines[pos] = (child_indent, item, n)
            val, pos = _map(lines, pos, child_indent)
            out.append(val)
        else:
            out.append(_scalar(item))
            pos += 1
    return out, pos


def _text_block(lines, pos, indent, style):
    """Blocco di testo | (righe a capo) o > (righe unite da spazi); - toglie, + tiene gli a capo finali."""
    body = []
    while pos < len(lines) and lines[pos][1].startswith("\0"):
        body.append(lines[pos][1][1:])
        pos += 1
    while body and body[-1].strip() == "":
        body.pop()
    base = min((len(b) - len(b.lstrip(" ")) for b in body if b.strip()), default=0)
    rows = [b[base:] if b.strip() else "" for b in body]
    if style[0] == "|":
        text = "\n".join(rows)
    else:
        text, para = "", []
        for r in rows + [""]:
            if r == "":
                if para:
                    text += (("\n" if text else "") + " ".join(para))
                    para = []
            else:
                para.append(r)
    if style.endswith("-") or not text:
        return text, pos
    return text + "\n", pos


def load_file(path: str) -> Any:
    try:
        import yaml  # type: ignore
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        with open(path, encoding="utf-8") as f:
            return loads(f.read())
