#!/usr/bin/env python3
"""Generatore di gestionale-kit: schemas/db/*.yaml -> model generati, JSON Schema, MODEL_INDEX.md.

Uso:
  python3 gen.py [cartella_progetto]           genera / aggiorna
  python3 gen.py [cartella_progetto] --check   verifica senza scrivere (CI, stop gate)
  python3 gen.py [cartella_progetto] --index   aggiorna solo MODEL_INDEX.md

Codici di uscita: 0 ok, 1 file non aggiornati o metodi custom in conflitto, 2 schemi non validi.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import emit_csharp  # noqa: E402
import emit_java  # noqa: E402
import emit_python  # noqa: E402
import emit_typescript  # noqa: E402
import rules  # noqa: E402
from naming import EXT, GEN_DIR, LANGS, MARKER, custom_file, gen_options, method_name, member  # noqa: E402
from schema import SchemaError, Table, load_schemas, methods_of  # noqa: E402

EMITTERS = {"python": emit_python, "typescript": emit_typescript, "csharp": emit_csharp, "java": emit_java}

DEFAULT_MODEL = {
    "schema_dir": "schemas/db",
    "json_schema_dir": "schemas/json",
    "index_file": "MODEL_INDEX.md",
    "targets": [],
}

# --------------------------------------------------------------------------- metodi nei file custom

_KW = {"if", "for", "while", "switch", "catch", "function", "return", "new", "else", "using", "lock", "foreach", "nameof", "typeof", "base", "super", "this"}
METHOD_RX = {
    "python": re.compile(r"^[ \t]+def\s+([A-Za-z_]\w*)\s*\(", re.M),
    "typescript": re.compile(r"^[ \t]*(?:(?:public|protected|private|static|async|override|readonly)\s+)*([A-Za-z_$][\w$]*)\s*(?:<[^>(]*>)?\s*\([^;]*?\)\s*(?::\s*[^=;{]+?)?\s*\{", re.M),
    "csharp": re.compile(r"^[ \t]*(?:(?:public|protected|private|internal|static|async|virtual|override|sealed|new|partial)\s+)+[\w<>\[\],.?() ]+?\s+([A-Za-z_]\w*)\s*(?:<[^>(]*>)?\s*\(", re.M),
    "java": re.compile(r"^[ \t]*(?:(?:public|protected|private|static|final|synchronized|abstract|default)\s+)+(?:<[^>]+>\s+)?[\w<>\[\],.? ]+?\s+([A-Za-z_]\w*)\s*\(", re.M),
}


def scan_methods(lang: str, text: str, class_name: str = "") -> List[str]:
    names = []
    for mt in METHOD_RX[lang].finditer(text):
        n = mt.group(1)
        if n in _KW or n == "constructor" or n == class_name or n.startswith("__"):
            continue
        if n not in names:
            names.append(n)
    return names


def generated_names(lang: str, t: Table) -> List[str]:
    return [method_name(lang, m.key) for m in methods_of(t)]


def custom_table_of(lang: str, filename: str) -> Optional[str]:
    """Da un nome di file nella cartella model restituisce la tabella a cui appartiene."""
    if lang == "java":
        mt = re.fullmatch(r"([A-Z][A-Za-z0-9]*)Repository\.java", filename)
    else:
        mt = re.fullmatch(r"([A-Z][A-Za-z0-9]*)" + re.escape(EXT[lang]), filename)
    return mt.group(1) if mt else None


def collisions(lang: str, t: Table, text: str) -> List[str]:
    gen = set(generated_names(lang, t))
    return [n for n in scan_methods(lang, text, f"{t.name}Repository") if n in gen]


# --------------------------------------------------------------------------- config

def model_config(cfg: dict) -> dict:
    out = dict(DEFAULT_MODEL)
    out.update(cfg.get("model") or {})
    for t in out["targets"]:
        if t.get("lang") not in LANGS:
            raise SystemExit(f"gen: target con lang non valido {t.get('lang')!r} (ammessi: {', '.join(LANGS)})")
        if not t.get("dir"):
            raise SystemExit(f"gen: il target {t['lang']} non ha 'dir'")
    return out


def model_dirs(cfg: dict) -> List[Tuple[str, str]]:
    """[(lang, cartella model relativa)] dai target configurati."""
    mc = model_config(cfg)
    return [(t["lang"], t["dir"].rstrip("/")) for t in mc["targets"]]


# --------------------------------------------------------------------------- JSON Schema e indice

def json_schema(t: Table) -> str:
    props, req = {}, []
    for c in t.columns:
        base = {"uuid": {"type": "string", "format": "uuid"}, "string": {"type": "string", "maxLength": c.length},
                "text": {"type": "string"}, "int": {"type": "integer"}, "bigint": {"type": "integer"},
                "decimal": {"type": "number"}, "bool": {"type": "boolean"},
                "date": {"type": "string", "format": "date"}, "datetime": {"type": "string", "format": "date-time"},
                "json": {}}[c.type]
        p = dict(base)
        if c.nullable and "type" in p:
            p["type"] = [p["type"], "null"]
        if c.description:
            p["description"] = c.description
        if (c.primary_key and c.auto) or c.generated:
            p["readOnly"] = True
        elif c.required and c.default is None:
            req.append(member("typescript", c.name))
        if c.default is not None:
            p["default"] = c.default
        props[member("typescript", c.name)] = p
    doc = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{t.name}.schema.json",
           "$comment": f"{MARKER}. Sorgente: schemas/db/{t.name}.yaml", "title": t.name,
           "description": t.description or f"Record della tabella {t.db_name}", "type": "object",
           "additionalProperties": False, "properties": props, "required": req}
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def build_index(tables: Dict[str, Table], targets: List[dict], customs: Dict[Tuple[str, str], List[str]], mc: dict) -> str:
    langs = [t["lang"] for t in targets]
    title = {"python": "Python", "typescript": "TypeScript", "csharp": "C#", "java": "Java"}
    o = [f"<!-- {MARKER}. NON MODIFICARE: rigenerato da schemas/db e dai file custom. -->",
         "# Indice del modello dati", "",
         "Ogni tabella ha uno schema in `" + mc["schema_dir"] + "/<Tabella>.yaml`, un file generato con entità, CRUD e "
         "relazioni (non modificabile) e un file custom, punto d'ingresso e unico posto per i metodi specifici.", ""]
    o += ["| Tabella | Tabella DB | Colonne | Relazioni |", "|---|---|---|---|"]
    for n, t in tables.items():
        rel = ", ".join(f"{r.name} → {r.target}" for r in t.relations) or "—"
        o.append(f"| [{n}](#{n.lower()}) | `{t.db_name}` | {len(t.columns)} | {rel} |")
    for n, t in tables.items():
        o += ["", f"## {n}", ""]
        if t.description:
            o += [t.description, ""]
        o += [f"Tabella `{t.db_name}` · schema `{mc['schema_dir']}/{n}.yaml` · JSON Schema `{mc['json_schema_dir']}/{n}.schema.json`", ""]
        o += ["| Colonna | Tipo | Obbligatoria | Note |", "|---|---|---|---|"]
        for c in t.columns:
            notes = []
            if c.primary_key:
                notes.append("chiave" + (" generata" if c.auto else ""))
            if c.unique:
                notes.append("univoca")
            if c.generated:
                notes.append(c.generated)
            if c.name in t.fk_columns():
                r = next(r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == c.name)
                notes.append(f"→ {r.target} ({r.on_delete})")
            typ = c.type + (f"({c.length})" if c.length else "") + (f"({c.precision},{c.scale})" if c.type == "decimal" else "")
            o.append(f"| {c.name} | {typ} | {'sì' if not c.nullable else 'no'} | {', '.join(notes)} |")
        if targets:
            o += ["", "| Linguaggio | Punto d'ingresso (custom) | Generato |", "|---|---|---|"]
            for tg in targets:
                d, lang = tg["dir"].rstrip("/"), tg["lang"]
                gen_files = [f"{d}/{GEN_DIR}/{n}{EXT[lang]}"] + ([f"{d}/{GEN_DIR}/{n}RepositoryBase.java"] if lang == "java" else [])
                o.append(f"| {title[lang]} | `{d}/{custom_file(lang, n)}` | " + ", ".join(f"`{g}`" for g in gen_files) + " |")
            o += ["", "| Metodo generato | " + " | ".join(title[x] for x in langs) + " |", "|---" * (len(langs) + 1) + "|"]
            for meth in methods_of(t):
                o.append(f"| {meth.summary} | " + " | ".join(f"`{method_name(x, meth.key)}`" for x in langs) + " |")
            any_custom = False
            for tg in targets:
                names = customs.get((tg["lang"], n), [])
                if names:
                    if not any_custom:
                        o += ["", "Metodi custom:"]
                        any_custom = True
                    o.append(f"- {title[tg['lang']]}: " + ", ".join(f"`{x}`" for x in names))
            if not any_custom:
                o += ["", "Metodi custom: nessuno."]
    return "\n".join(o) + "\n"


# --------------------------------------------------------------------------- esecuzione

class Result:
    def __init__(self):
        self.written: List[str] = []
        self.removed: List[str] = []
        self.created: List[str] = []
        self.stale: List[str] = []
        self.problems: List[str] = []


def _is_generated(p: Path) -> bool:
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            return MARKER in f.read(600)
    except OSError:
        return False


def run(proj: Path, cfg: dict, check: bool = False, index_only: bool = False) -> Result:
    mc = model_config(cfg)
    res = Result()
    tables = load_schemas(proj / mc["schema_dir"])  # solleva SchemaError
    schema_rel = {n: f"{mc['schema_dir']}/{n}.yaml" for n in tables}
    desired: Dict[str, str] = {}
    managed_dirs: List[Path] = [proj / mc["json_schema_dir"]]
    customs_to_create: Dict[str, str] = {}
    for tg in mc["targets"]:
        lang, d = tg["lang"], tg["dir"].rstrip("/")
        managed_dirs.append(proj / d / GEN_DIR)
        if index_only:
            continue
        gen, custom = EMITTERS[lang].emit(tables, schema_rel, gen_options(tg))
        for rel, text in gen.items():
            desired[f"{d}/{rel}"] = text
        for rel, text in custom.items():
            customs_to_create[f"{d}/{rel}"] = text
    if not index_only:
        for n, t in tables.items():
            desired[f"{mc['json_schema_dir']}/{n}.schema.json"] = json_schema(t)

    # file custom: si creano una volta sola, poi sono del progetto
    for rel, text in customs_to_create.items():
        p = proj / rel
        if not p.exists():
            if check:
                res.stale.append(f"manca il file custom {rel}")
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
                res.created.append(rel)

    # metodi custom: indice e conflitti con i nomi generati
    customs: Dict[Tuple[str, str], List[str]] = {}
    for tg in mc["targets"]:
        lang, d = tg["lang"], tg["dir"].rstrip("/")
        mdir = proj / d
        if not mdir.is_dir():
            continue
        for f in sorted(mdir.iterdir()):
            if not f.is_file():
                continue
            tn = custom_table_of(lang, f.name)
            if tn is None:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            if tn not in tables:
                res.problems.append(f"{d}/{f.name}: la tabella {tn} non ha più uno schema; sposta i metodi o elimina il file")
                continue
            cls = f"{tn}Repository"
            customs[(lang, tn)] = scan_methods(lang, text, cls)
            for c in collisions(lang, tables[tn], text):
                res.problems.append(f"{d}/{f.name}: il metodo custom '{c}' ha lo stesso nome di un metodo generato")

    desired[mc["index_file"]] = build_index(tables, mc["targets"], customs, mc)

    for rel, text in desired.items():
        p = proj / rel
        current = p.read_text(encoding="utf-8") if p.exists() else None
        if current == text:
            continue
        if check:
            res.stale.append(f"{rel} non aggiornato" if current is not None else f"{rel} mancante")
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            res.written.append(rel)

    if not index_only:
        wanted = {str((proj / r).resolve()) for r in desired}
        for d in managed_dirs:
            if not d.is_dir():
                continue
            for f in sorted(d.rglob("*")):
                if f.is_file() and str(f.resolve()) not in wanted and _is_generated(f):
                    rel = f.relative_to(proj).as_posix()
                    if check:
                        res.stale.append(f"{rel} generato per una tabella che non esiste più")
                    else:
                        f.unlink()
                        res.removed.append(rel)
    return res


def main(argv: List[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    check, index_only, quiet = "--check" in argv, "--index" in argv, "--quiet" in argv
    proj = Path(args[0]).resolve() if args else rules.find_project_dir()
    cfg = rules.load_config(proj)
    if cfg is None:
        print(f"gen: nessun {rules.CONFIG_REL} in {proj}")
        return 0
    try:
        res = run(proj, cfg, check=check, index_only=index_only)
    except SchemaError as exc:
        print("Schemi non validi:", file=sys.stderr)
        for e in exc.errors:
            print(f"  - {e}", file=sys.stderr)
        return 2
    for p in res.problems:
        print(f"[BLOCCANTE] {p}", file=sys.stderr)
    if check:
        for s in res.stale:
            print(f"[BLOCCANTE] {s}: esegui il generatore", file=sys.stderr)
        if not quiet and not (res.stale or res.problems):
            print("gen --check: file generati aggiornati")
        return 1 if (res.stale or res.problems) else 0
    if not quiet:
        for label, items in (("scritti", res.written), ("creati (custom)", res.created), ("rimossi", res.removed)):
            for i in items:
                print(f"{label}: {i}")
        print(f"gen: {len(res.written)} scritti, {len(res.created)} custom creati, {len(res.removed)} rimossi")
    return 1 if res.problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
