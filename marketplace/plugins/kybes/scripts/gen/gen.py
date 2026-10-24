#!/usr/bin/env python3
"""Generatore di kybes: schemas/db/*.yaml -> model generati, JSON Schema, MODEL_INDEX.md.

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

import api_plan  # noqa: E402
import emit_api_python  # noqa: E402
import emit_api_typescript  # noqa: E402
import emit_api_java  # noqa: E402
import emit_api_csharp  # noqa: E402
import graphql_plan  # noqa: E402
import emit_graphql_python  # noqa: E402
import emit_graphql_typescript  # noqa: E402
import emit_graphql_java  # noqa: E402
import emit_graphql_csharp  # noqa: E402
import test_api_python  # noqa: E402
import test_api_typescript  # noqa: E402
import test_api_java  # noqa: E402
import test_api_csharp  # noqa: E402
import emit_archive  # noqa: E402
import emit_csharp  # noqa: E402
import emit_db  # noqa: E402
import test_python  # noqa: E402
import test_csharp  # noqa: E402
import test_java  # noqa: E402
import test_typescript  # noqa: E402
import verification  # noqa: E402
import emit_java  # noqa: E402
import emit_python  # noqa: E402
import emit_typescript  # noqa: E402
import rules  # noqa: E402
from naming import EXT, GEN_DIR, LANGS, MARKER, custom_file, gen_options, method_name, member  # noqa: E402
from schema import SchemaError, Table, load_schemas, methods_of  # noqa: E402
from schema import snake as snake_name  # noqa: E402

EMITTERS = {"python": emit_python, "typescript": emit_typescript, "csharp": emit_csharp, "java": emit_java}

DEFAULT_MODEL = {
    "schema_dir": "schemas/db",
    "json_schema_dir": "schemas/generated/json",
    "index_file": "MODEL_INDEX.md",
    "db_dir": "db/generated",
    "ddl_dialects": ["postgres"],
    "tenancy": {"default": "none", "id_type": "uuid"},
    "jobs_dir": "jobs/generated",
    "archive": {},
    "targets": [],
}

DEFAULT_VERIFICATION = {
    "asil": "B",
    "generate_tests": True,
    "docs_dir": "docs/generated/verification",
    "coverage_reports": [],
    # soglie di copertura strutturale per ASIL (percentuali); politica del progetto ispirata a ISO 26262-6 tab. 9
    "thresholds": {"QM": {}, "A": {"statement": 90}, "B": {"statement": 95, "branch": 90},
                   "C": {"statement": 100, "branch": 95}, "D": {"statement": 100, "branch": 100}},
}

DEFAULT_GRAPHQL = {
    "sdl_file": "schemas/generated/schema.graphql",
}

DEFAULT_API = {
    "contract": "schemas/openapi.yaml",
    "generated_contract": "schemas/generated/openapi.yaml",
    # claim già verificati dal gateway (Lambda: requestContext.authorizer; Kubernetes: header impostati dal gateway)
    "claims": {"subject": "sub", "tenant": "tid", "scopes": ["scp", "roles"]},
    "headers": {"subject": "x-kybes-subject", "tenant": "x-kybes-tenant", "scopes": "x-kybes-scopes"},
    "base_path": "",
}
API_EMITTERS = {"python": emit_api_python, "typescript": emit_api_typescript, "java": emit_api_java, "csharp": emit_api_csharp}
API_TEST_EMITTERS = {"python": test_api_python, "typescript": test_api_typescript, "java": test_api_java, "csharp": test_api_csharp}
GRAPHQL_EMITTERS = {"python": emit_graphql_python, "typescript": emit_graphql_typescript, "java": emit_graphql_java, "csharp": emit_graphql_csharp}


def api_config(cfg: dict) -> dict:
    out = dict(DEFAULT_API)
    out.update(cfg.get("api") or {})
    out["claims"] = {**DEFAULT_API["claims"], **((cfg.get("api") or {}).get("claims") or {})}
    out["headers"] = {**DEFAULT_API["headers"], **((cfg.get("api") or {}).get("headers") or {})}
    return out


def api_dir(tg: dict) -> str:
    """Cartella del codice API generato: default 'api' alla root del progetto."""
    if tg.get("api_dir"):
        return tg["api_dir"].rstrip("/")
    return "api"


def controller_dir(tg: dict) -> str:
    """Cartella dei controller generati: default 'controllers' alla root del progetto."""
    if tg.get("controller_dir"):
        return tg["controller_dir"].rstrip("/")
    return "controllers"


def graphql_dir(tg: dict) -> Optional[str]:
    """Cartella del codice GraphQL generato: None se non configurato."""
    d = tg.get("graphql_dir")
    return d.rstrip("/") if d else None


def graphql_config(cfg: dict) -> dict:
    out = dict(DEFAULT_GRAPHQL)
    out.update(cfg.get("graphql") or {})
    return out


def load_contract(proj: Path, ac: dict) -> Optional[dict]:
    p = proj / ac["contract"]
    if not p.exists():
        return None
    from miniyaml import load_file
    data = load_file(str(p))
    if not isinstance(data, dict):
        raise api_plan.ContractError([f"{ac['contract']}: deve contenere un documento OpenAPI"])
    return data


TEST_EMITTERS = {"python": test_python, "typescript": test_typescript, "java": test_java, "csharp": test_csharp}
TEST_FILE = {"python": lambda n: f"test_{snake_name(n)}.py", "typescript": lambda n: f"{n}.test.ts", "java": lambda n: f"{n}Test.java",
             "csharp": lambda n: f"{n}Tests.cs"}


def verification_config(cfg: dict) -> dict:
    out = dict(DEFAULT_VERIFICATION)
    out.update(cfg.get("verification") or {})
    if out["asil"] not in ("QM", "A", "B", "C", "D"):
        raise SystemExit(f"gen: verification.asil non valido: {out['asil']!r}")
    return out


def tests_dir(tg: dict) -> Optional[str]:
    """Cartella dei test del pacchetto del linguaggio: <pacchetto>/tests (personalizzabile con tests_dir)."""
    if tg.get("tests_dir"):
        return tg["tests_dir"].rstrip("/")
    d = tg["dir"].rstrip("/")
    if d.endswith("/src/model"):
        return d[: -len("/src/model")] + "/tests"
    if "/src/main/java/" in d:
        return d.replace("/src/main/java/", "/src/test/java/", 1)
    return None

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

def load_tables(proj: Path, cfg: dict) -> Dict[str, Table]:
    """Schemi del progetto con la modalità multi-tenant della configurazione (solleva SchemaError)."""
    mc = model_config(cfg)
    ten = {"default": "none", "id_type": "uuid", **(mc.get("tenancy") or {})}
    return load_schemas(proj / mc["schema_dir"], ten["default"], ten["id_type"])


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
        if c.tenant:
            continue  # il tenant viene dall'autenticazione, non dal contenuto della richiesta
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
        ten = {"none": "condivisa da tutte le Organization",
               "column": "per tenant con colonna `TenantId`: ogni metodo filtra per il tenant legato alla sessione",
               "schema": "per tenant nello schema `tenant_<chiave>`: la sessione va aperta con il search_path del tenant",
               "database": "per tenant in un database dedicato: la sessione va aperta sul database del tenant"}[t.tenancy or "none"]
        o += [f"Multi-tenant: **{t.tenancy or 'none'}**, {ten}.", ""]
        if t.mongo:
            o += [f"Storage: **MongoDB**, collection `{t.db_name}` (chiave in `_id`): stessi metodi delle tabelle SQL su una sessione MongoDB "
                  "(Python `mongo_session`, TypeScript `mongoSession`, Java `MongoSession.open`, C# `MongoSession.Open`); "
                  "transazioni con `run_in_mongo_transaction` / `runInMongoTransaction` / `MongoSession.transaction` / `MongoSession.TransactionAsync`; "
                  "indici creati da `ensure_mongo_indexes` / `ensureMongoIndexes` / `MongoIndexes.ensure` / `MongoIndexes.EnsureAsync`.", ""]
            if t.retention:
                o += [f"Ciclo di vita: cancellazione dopo {t.retention.delete_after} su `{t.retention.on}` con un indice TTL di MongoDB (nessun job).", ""]
        if (t.archive or t.retention) and not t.mongo:
            jd = mc.get("jobs_dir", "jobs/generated").rstrip("/")
            life = []
            if t.archive:
                a = t.archive
                life.append(f"archivio dopo {a.after} su `{a.on}` ({a.target}, Parquet, partizioni {', '.join(a.partition_by) or 'nessuna'}"
                            + (", letture per chiave anche dall'archivio" if a.read_through else "") + ")")
            if t.retention:
                life.append(f"cancellazione dopo {t.retention.delete_after}" + ("" if t.archive else f" su `{t.retention.on}`"))
            o += [f"Ciclo di vita: {'; '.join(life)} · job `{jd}/{t.job_name}/` ({t.job.mode}).", ""]
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
            if t.queries:
                o += ["", "Query dichiarate:", "", "| Query | Condizioni | Restituisce | " + " | ".join(title[x] for x in langs) + " |",
                      "|---|---|---|" + "---|" * len(langs)]
                for q in t.queries:
                    kind = {"page": "query_page", "list": "query_list", "one": "query_one"}[q.returns]
                    from schema import _describe
                    o.append(f"| {q.name} | {_describe(q)} | {q.returns} | " +
                             " | ".join(f"`{method_name(x, kind + ':' + q.name)}`" for x in langs) + " |")
            pg = t.pagination
            order_desc = ", ".join(f"{c}{' desc' if d else ''}" for c, d in t.order())
            sortable = ", ".join(member("typescript", c) for c in pg.sortable) or "solo chiave"
            o += ["", f"Paginazione: ordine predefinito {order_desc} · ordinabili per `sort`: {sortable} · "
                      f"limite predefinito {pg.default_limit}, massimo {pg.max_limit} · isolamento delle scritture: {t.isolation}"]
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
    tables = load_tables(proj, cfg)  # solleva SchemaError
    schema_rel = {n: f"{mc['schema_dir']}/{n}.yaml" for n in tables}
    desired: Dict[str, str] = {}
    managed_dirs: List[Path] = [proj / mc["json_schema_dir"], proj / mc["db_dir"]]
    customs_to_create: Dict[str, str] = {}
    for tg in mc["targets"]:
        lang, d = tg["lang"], tg["dir"].rstrip("/")
        managed_dirs.append(proj / d / GEN_DIR)
        if index_only:
            continue
        opts = gen_options(tg)
        opts["tenant_id_type"] = {"id_type": "uuid", **(mc.get("tenancy") or {})}["id_type"]
        gen, custom = EMITTERS[lang].emit(tables, schema_rel, opts)
        for rel, text in gen.items():
            desired[f"{d}/{rel}"] = text
        for rel, text in custom.items():
            customs_to_create[f"{d}/{rel}"] = text
    ac = api_config(cfg)
    ops, full = [], None
    if not index_only:
        try:
            doc = load_contract(proj, ac)
            if any(t.api for t in tables.values()) or (doc or {}).get("paths"):
                ops, full = api_plan.build(tables, doc)
        except api_plan.ContractError as exc:
            res.problems += [f"contratto API: {e}" for e in exc.errors]
        except Exception as exc:  # YAML non valido
            res.problems.append(f"contratto API: {ac['contract']} non leggibile: {exc}")
    vc = verification_config(cfg)
    if not index_only and tables:
        cycles = verification.builder_cycles(tables)
        if cycles:
            res.problems.append("cicli di chiavi esterne obbligatorie, impossibili da popolare nei test: " + "; ".join(cycles))
        cat = verification.build_catalog(tables, vc["asil"], {"id_type": "uuid", **(mc.get("tenancy") or {})}["id_type"])
        verification.add_api_cases(cat, tables, ops, vc["asil"])
        test_files: Dict[str, Dict[str, str]] = {}
        if vc.get("generate_tests", True):
            for tg in mc["targets"]:
                em = TEST_EMITTERS.get(tg["lang"])
                td = tests_dir(tg)
                if not em or not td:
                    continue
                managed_dirs.append(proj / td / GEN_DIR)
                if tg["lang"] == "typescript":
                    files = em.emit(cat, tables, vc["asil"], tg.get("dialect", "postgres"))
                elif tg["lang"] == "java":
                    files = em.emit(cat, tables, vc["asil"], gen_options(tg)["package"])
                elif tg["lang"] == "csharp":
                    files = em.emit(cat, tables, vc["asil"], gen_options(tg)["namespace"])
                else:
                    files = em.emit(cat, tables, vc["asil"])
                for rel, text in files.items():
                    desired[f"{td}/{rel}"] = text
                for rel, make in getattr(em, "CUSTOM_ONCE", {}).items():
                    customs_to_create[f"{td}/{rel}"] = make()
                test_files[tg["lang"]] = {n: f"{td}/{GEN_DIR}/{TEST_FILE[tg['lang']](n)}" for n in tables}
                aem = API_TEST_EMITTERS.get(tg["lang"])
                if aem and ops:
                    test_opts = gen_options(tg)
                    test_opts["api_dir"] = api_dir(tg)
                    test_opts["controller_dir"] = controller_dir(tg)
                    test_opts["model_dir"] = tg["dir"].rstrip("/")
                    test_opts["tests_dir"] = td
                    files = aem.emit(cat, tables, ops, vc["asil"], test_opts)
                    for rel, text in files.items():
                        desired[f"{td}/{rel}"] = text
                    test_files[f"{tg['lang']}-api"] = {k: f"{td}/{v}" for k, v in aem.index(tables, ops).items()}
        id_type = {"id_type": "uuid", **(mc.get("tenancy") or {})}["id_type"]
        life = emit_archive.lifecycle_tables(tables)
        managed_dirs.append(proj / mc["jobs_dir"])
        if life:
            res.problems += emit_archive.location_errors(tables, emit_archive.archive_config(mc))
            for rel, text in emit_archive.emit(tables, mc, cat, vc["asil"], id_type).items():
                desired[rel] = text
            jd = mc["jobs_dir"].rstrip("/")
            test_files["jobs"] = {n: f"{jd}/_engine/tests/test_{snake_name(n)}_job.py" for n in life}
            test_files["jobs"][verification.JOBS] = f"{jd}/_engine/tests/test_engine.py"
        managed_dirs.append(proj / vc["docs_dir"])
        for rel, text in verification.verification_docs(cat, tables, test_files, vc["asil"], vc["thresholds"]).items():
            desired[f"{vc['docs_dir']}/{rel}"] = text
    if not index_only:
        gc = ac["generated_contract"]
        managed_dirs.append((proj / gc).parent)
        if full is not None:
            desired[gc] = (f"# {MARKER}. NON MODIFICARE: unione di {ac['contract']} e dei blocchi api degli schemi.\n"
                           + api_plan.dump_yaml(full) + "\n")
        for tg in mc["targets"]:
            em = API_EMITTERS.get(tg["lang"])
            if not em:
                continue
            ad = api_dir(tg)
            cd = controller_dir(tg)
            managed_dirs.append(proj / ad / GEN_DIR)
            managed_dirs.append(proj / cd / GEN_DIR)
            if ops:
                opts = gen_options(tg)
                opts["api_dir"] = ad
                opts["controller_dir"] = cd
                opts["model_dir"] = tg["dir"].rstrip("/")
                api_files, ctrl_files = em.emit(tables, ops, ac, opts)
                for rel, text in api_files.items():
                    desired[f"{ad}/{rel}"] = text
                for rel, text in ctrl_files.items():
                    desired[f"{cd}/{rel}"] = text
        for n, t in tables.items():
            desired[f"{mc['json_schema_dir']}/{n}.schema.json"] = json_schema(t)
        if tables:
            desired[f"{mc['json_schema_dir']}/_page.schema.json"] = emit_db.page_schema()
            desired[f"{mc['db_dir']}/indexes.md"] = emit_db.index_report(tables)
            if "postgres" in mc.get("ddl_dialects", []):
                for rel, text in emit_db.ddl_files(tables, mc["schema_dir"]).items():
                    # tenancy/: policy e DDL per tenant in db/generated/tenancy, il resto in db/generated/ddl/postgres
                    target = f"{mc['db_dir']}/{rel}" if rel.startswith("tenancy/") else f"{mc['db_dir']}/ddl/postgres/{rel}"
                    desired[target] = text

        # GraphQL
        gqlc = graphql_config(cfg)
        has_graphql = any(graphql_dir(tg) for tg in mc["targets"])
        if has_graphql and any(t.api for t in tables.values()):
            gql_schema = graphql_plan.build(tables)
            sdl = gqlc["sdl_file"]
            managed_dirs.append((proj / sdl).parent)
            desired[sdl] = graphql_plan.render_sdl(gql_schema)
            for tg in mc["targets"]:
                gd = graphql_dir(tg)
                if not gd:
                    continue
                gem = GRAPHQL_EMITTERS.get(tg["lang"])
                if not gem:
                    continue
                managed_dirs.append(proj / gd / GEN_DIR)
                opts = gen_options(tg)
                opts["model_dir"] = tg["dir"].rstrip("/")
                gql_files = gem.emit(tables, gql_schema, opts)
                for rel, text in gql_files.items():
                    desired[f"{gd}/{rel}"] = text

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
