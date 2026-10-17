# Codebase Structure

**Analysis Date:** 2026-10-17

## Directory Layout

```
kybes/
├── install.sh                    # Root shortcut to plugin installer
├── README.md                     # Project overview
├── LICENSE                       # License
├── docs/                         # Documentation (Italian)
├── tests/                        # Kit test suite
├── marketplace/plugins/kybes/    # The plugin (core of the project)
└── .github/workflows/            # CI for the kit itself
```

## Directory Purposes

**`marketplace/plugins/kybes/`** (the plugin):
```
marketplace/plugins/kybes/
├── install.sh                # Idempotent installer for target projects
├── README.md
├── LICENSE
├── .claude-plugin/
│   └── plugin.json           # Claude Code plugin manifest
├── agents/                   # AI agent definitions
│   ├── architect.md          # Plans runtime, schema changes
│   ├── implementer.md        # Executes tasks one at a time
│   └── reviewer.md           # Independent review
├── hooks/
│   └── hooks.json            # Hook bindings (pre_write, post_edit, stop_gate)
├── scripts/                  # Hook implementations and rule checks
│   ├── hook_common.py        # Shared hook utilities
│   ├── rules.py              # Rule logic (shared by hooks and CI)
│   ├── model_guard.py        # Blocks ORM imports outside model layer
│   ├── arch_check.py         # Structural verification
│   ├── pre_write.py          # Rejects violating writes
│   ├── post_edit.py          # Regenerates on schema change, lints
│   ├── stop_gate.py          # Blocks completion until checks pass
│   ├── verify.py             # Verification script
│   └── gen/                  # Code generator
│       ├── schema.py         # YAML schema loader/validator
│       ├── miniyaml.py       # Custom YAML parser (no PyYAML)
│       ├── emit_python.py    # Python model emitter
│       ├── emit_db.py        # DDL + JSON Schema emitter
│       ├── emit_api_typescript.py  # TypeScript API emitter
│       ├── runtime_csharp.py       # C# model emitter
│       ├── runtime_mongo.py        # MongoDB variant emitter
│       ├── api_plan.py       # API endpoint planner
│       ├── mongo_plan.py     # MongoDB index planner
│       ├── sqlonly.py         # SQL-only utilities
│       ├── test_api_*.py     # API test generators (python/typescript/java/csharp)
│       ├── runtime_api_*_tests.py  # API runtime test generators
│       └── engine/           # Archive/retention job engine
│           ├── kybes_jobs/   # Python package
│           │   ├── __init__.py
│           │   ├── __main__.py   # CLI entry point
│           │   ├── engine.py     # Job execution logic
│           │   ├── config.py     # Job configuration
│           │   ├── storage.py    # S3/Blob storage abstraction
│           │   └── codec.py      # Serialization
│           └── tests/
│               ├── conftest.py
│               └── test_engine.py
├── skills/                   # Claude Code skills
│   ├── kybes-init/           # Installation skill
│   └── kybes-architecture/   # Architecture rules skill
└── templates/                # Templates copied to target projects
    ├── setup.sh              # Setup script
    ├── CLAUDE.kybes.md       # CLAUDE.md block template
    ├── ci/
    │   └── architecture-check.yml  # CI pipeline template
    ├── rules/                # Per-directory rules for Claude
    │   ├── jobs.md
    │   ├── db-models.md
    │   ├── microservices.md
    │   ├── functions.md
    │   ├── utils-errors.md
    │   └── frontend-infra.md
    ├── esempi-schemi/        # Example YAML schemas
    │   ├── Clienti.yaml
    │   ├── Prodotti.yaml
    │   ├── Ordini.yaml
    │   ├── RigheOrdine.yaml
    │   ├── Categorie.yaml
    │   ├── Eventi.yaml
    │   └── api/openapi.yaml
    └── scaffold/             # Project scaffold templates
        ├── README.kybes.md
        ├── schemas/openapi.yaml
        └── libs/
            ├── db-models/
            │   ├── python/pyproject.toml
            │   ├── typescript/package.json
            │   ├── typescript/tsconfig.json
            │   ├── java/pom.xml
            │   └── csharp/
            │       ├── src/DbModels.csproj
            │       └── tests/DbModels.Tests.csproj
            └── errors/
                ├── python/app_errors.py
                └── typescript/appErrors.ts
```

**`tests/`** (kit's own tests):
```
tests/
├── run.sh                    # Test runner
├── python/                   # Python model tests
│   ├── test_model.py
│   ├── test_archive.py
│   └── test_access.py
├── typescript/               # TypeScript tests
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── access.test.ts
│       └── model.test.ts
├── java/                     # Java tests
│   ├── runtime/
│   │   ├── RunTests.java
│   │   └── PagingTest.java
│   └── stubs/                # Minimal stubs for compilation
├── csharp/
│   └── syntax_check.py       # C# syntax verification
├── hooks/
│   └── test_hooks.sh         # Hook tests
├── ci/
│   └── annotate.py           # CI annotation helper
├── mongo/
│   └── fake_mongo.py         # MongoDB test double
├── sql/
│   └── tenancy_check.py      # Tenancy SQL verification
└── fixtures/                 # Test fixture YAML schemas
    ├── tenancy/              # Multi-tenant test schemas
    │   ├── Documenti.yaml
    │   ├── Voci.yaml
    │   ├── Registri.yaml
    │   ├── Tipologie.yaml
    │   └── Fascicoli.yaml
    └── mongo/                # MongoDB test schemas
        ├── Accessi.yaml
        ├── Reparti.yaml
        ├── Etichette.yaml
        ├── Segnalazioni.yaml
        └── NoteSegnalazione.yaml
```

**`docs/`** (documentation, in Italian):
- `architettura.md` — Architecture overview
- `struttura-cartelle.md` — Target project folder structure
- `schema-yaml.md` — YAML schema specification
- `generatore.md` — Generator documentation
- `controlli.md` — Verification checks
- `configurazione.md` — Configuration reference
- `api.md` — REST API documentation
- `multi-tenant.md` — Multi-tenancy guide
- `mongodb.md` — MongoDB support
- `transazioni.md` — Transaction patterns
- `paginazione.md` — Cursor pagination
- `query-e-indici.md` — Queries and indexes
- `archivio.md` — Archive and retention
- `verifica.md` — Verification system
- `sviluppo.md` — Development guide
- `roadmap.md` — Roadmap

## Key File Locations

**Entry Points:**
- `install.sh`: Root installer shortcut
- `marketplace/plugins/kybes/install.sh`: Main installer
- `marketplace/plugins/kybes/scripts/gen/engine/kybes_jobs/__main__.py`: Engine CLI

**Configuration:**
- `marketplace/plugins/kybes/.claude-plugin/plugin.json`: Plugin manifest
- `marketplace/plugins/kybes/hooks/hooks.json`: Hook definitions
- `.github/workflows/kit-tests.yml`: CI workflow

**Core Logic:**
- `marketplace/plugins/kybes/scripts/gen/schema.py`: Schema parsing/validation
- `marketplace/plugins/kybes/scripts/gen/engine/kybes_jobs/engine.py`: Job engine
- `marketplace/plugins/kybes/scripts/rules.py`: Rule enforcement logic
- `marketplace/plugins/kybes/scripts/model_guard.py`: Import guard

**Testing:**
- `tests/run.sh`: Test runner entry point
- `tests/fixtures/`: YAML schema fixtures

## Naming Conventions

**Files:**
- Python: `snake_case.py` (e.g., `hook_common.py`, `emit_python.py`)
- YAML schemas: `PascalCase.yaml` (e.g., `Clienti.yaml`, `Prodotti.yaml`)
- Agents/rules: `kebab-case.md` (e.g., `db-models.md`, `frontend-infra.md`)

**Directories:**
- `kebab-case` for multi-word dirs (e.g., `db-models`, `esempi-schemi`)
- `snake_case` for Python packages (e.g., `kybes_jobs`)

**Generated files in target projects:**
- `<T>` = PascalCase table name (e.g., `Clienti`)
- `<t>` = snake_case table name (e.g., `clienti`)
- Generated dirs always named `generated/`

## Where to Add New Code

**New language emitter:**
- Implementation: `marketplace/plugins/kybes/scripts/gen/emit_<language>.py` or `runtime_<language>.py`
- Tests: `tests/<language>/`

**New hook script:**
- Implementation: `marketplace/plugins/kybes/scripts/<hook_name>.py`
- Registration: Add to `marketplace/plugins/kybes/hooks/hooks.json`
- Shared logic: Add to `marketplace/plugins/kybes/scripts/hook_common.py`

**New rule template:**
- Template: `marketplace/plugins/kybes/templates/rules/<rule-name>.md`

**New test fixture:**
- Schema fixtures: `tests/fixtures/mongo/` or `tests/fixtures/tenancy/`

**New agent:**
- Agent definition: `marketplace/plugins/kybes/agents/<agent-name>.md`

**New example schema:**
- Location: `marketplace/plugins/kybes/templates/esempi-schemi/<TableName>.yaml`

**New scaffold template:**
- Location: `marketplace/plugins/kybes/templates/scaffold/`

## Special Directories

**`marketplace/plugins/kybes/scripts/gen/engine/`:**
- Purpose: Archive/retention job engine, deployed to target projects under `jobs/generated/_engine/`
- Generated: No (source code of the engine itself)
- Committed: Yes

**`tests/java/stubs/`:**
- Purpose: Minimal Java stub classes for compilation tests (jakarta, hibernate, bson, spring)
- Generated: No
- Committed: Yes

**`tests/fixtures/`:**
- Purpose: YAML schema fixtures for testing generator output
- Generated: No
- Committed: Yes

---

*Structure analysis: 2026-10-17*
