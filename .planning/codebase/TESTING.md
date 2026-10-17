# Testing Patterns

**Analysis Date:** 2026-10-17

## Test Framework

**Kit-level test runner:**
- Bash script: `tests/run.sh`
- Runs all test groups or a specific one: `tests/run.sh [python|jobs|typescript|java|csharp|sql|hooks]`
- Output: colored PASS/FAIL/SKIP per check
- Exit code: 0 all pass, 1 any failure

**Per-language test frameworks (in generated projects):**
- Python: `pytest` + `pytest-cov`
- TypeScript: `node:test` (Node.js built-in) + `c8` for coverage
- Java: JUnit 5 + JaCoCo
- C#: xUnit + coverlet

**Run Commands:**
```bash
tests/run.sh              # Run all kit tests
tests/run.sh python       # Python group only
tests/run.sh typescript   # TypeScript group only
tests/run.sh java         # Java group only
tests/run.sh csharp       # C# group only (syntax via tree-sitter)
tests/run.sh sql          # SQL DDL validation via pglast
tests/run.sh hooks        # Hook rule tests
tests/run.sh jobs         # Archive/job engine tests
```

## CI Pipeline

**GitHub Actions:** `.github/workflows/kit-tests.yml`

**Jobs:**
| Job | What it tests | Services |
|-----|---------------|----------|
| `tests` | Full `tests/run.sh` on SQLite, syntax checks, YAML reader, OpenAPI validation | None |
| `generated-java` | JUnit generated tests on PostgreSQL + MongoDB | postgres:16, mongo:7 (replica set) |
| `generated-csharp` | xUnit generated tests on PostgreSQL + MongoDB | postgres:16, mongo:7 |
| `generated-python-typescript` | pytest + node:test on PostgreSQL + MongoDB, DDL tenancy | postgres:16, mongo:7 |

**CI annotation:** `tests/ci/annotate.py` wraps test commands and produces GitHub Actions annotations from test reports.

## Test Architecture: Two Layers

### Layer 1: Kit Tests (`tests/`)

Hand-written integration tests that validate the generator output. They scaffold temporary projects, run the generator, then exercise the generated code.

**Test files:**
- `tests/python/test_model.py` -- CRUD, relations, cascade, validation on SQLite
- `tests/python/test_access.py` -- keyset paging, declared queries, Unit of Work on SQLite
- `tests/python/test_archive.py` -- archive validation, Hive layout, S3, manifest
- `tests/typescript/src/model.test.ts` -- CRUD, relations, cascade, validation on sql.js
- `tests/typescript/src/access.test.ts` -- keyset paging, declared queries, Unit of Work on sql.js
- `tests/java/runtime/PagingTest.java` -- paging logic, cursor compat, Unit of Work with fake EntityManager
- `tests/java/runtime/RunTests.java` -- minimal JUnit-free test runner for API framework tests
- `tests/csharp/syntax_check.py` -- tree-sitter C# syntax validation of generated code
- `tests/sql/tenancy_check.py` -- DDL tenancy validation on real PostgreSQL
- `tests/hooks/test_hooks.sh` -- hook rules and structure
- `tests/mongo/fake_mongo.py` -- pytest plugin providing mongomock for MongoDB collection tests

**Pattern (Python kit tests):**
```python
# Direct script execution, project path as argv[1]
import sys
sys.path.insert(0, sys.argv[1] + "/libs/db-models/python/src")
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from model.generated import Base, bind_tenant, ModelValidationError

eng = create_engine("sqlite://")
Base.metadata.create_all(eng)
with Session(eng) as s:
    bind_tenant(s, TENANT)
    repo = ClientiRepository(s)
    c = repo.create(Clienti(ragione_sociale="ACME Srl"))
    assert c.id is not None
print("OK")
```

**Pattern (TypeScript kit tests):**
```typescript
// Direct execution with node, no test runner
import { DataSource } from "typeorm";
import { ENTITIES, bindTenant } from "./model/generated";

const ds = new DataSource({ type: "sqljs", entities: ENTITIES, synchronize: true });
await ds.initialize();
const em = ds.manager;
bindTenant(em, TENANT);
const repo = new ClientiRepository(em);
const c = await repo.create({ ragioneSociale: "ACME Srl" });
assert.ok(c.id);
console.log("OK");
```

### Layer 2: Generated Tests (in target projects)

The generator produces test files for each table, following ISO 26262-6 verification methodology.

**Test catalog:** `marketplace/plugins/kybes/scripts/gen/verification.py`
- Defines `Requirement`, `TestCase`, `Catalog` dataclasses
- Test methods: `req` (requirements analysis), `eq` (equivalence classes), `bv` (boundary values), `eg` (error guessing), `mcdc` (MC/DC on query conditions)
- Stable IDs derived from schema names (not order)
- ASIL levels per table drive coverage thresholds

**Test generators per language:**
- `marketplace/plugins/kybes/scripts/gen/test_python.py` -- emits pytest files
- `marketplace/plugins/kybes/scripts/gen/test_typescript.py` -- emits node:test files
- `marketplace/plugins/kybes/scripts/gen/test_java.py` -- emits JUnit 5 files
- `marketplace/plugins/kybes/scripts/gen/test_csharp.py` -- emits xUnit files
- `marketplace/plugins/kybes/scripts/gen/test_api_python.py` -- API endpoint tests (FastAPI/httpx)
- `marketplace/plugins/kybes/scripts/gen/test_api_typescript.py` -- API endpoint tests
- `marketplace/plugins/kybes/scripts/gen/test_api_java.py` -- API endpoint tests
- `marketplace/plugins/kybes/scripts/gen/test_api_csharp.py` -- API endpoint tests

**Verification runner:** `marketplace/plugins/kybes/scripts/verify.py`
- Runs generated tests per language with coverage collection
- Validates coverage meets ASIL thresholds
- Usage: `python3 verify.py <project> [--lang=python] [--quiet]`

## Coverage

**ASIL-based thresholds** (ISO 26262-6 Table 9), configured in generator defaults:

| ASIL | Statement | Branch |
|------|-----------|--------|
| QM | -- | -- |
| A | 90% | -- |
| B | 95% | 90% |
| C | 100% | 95% |
| D | 100% | 100% |

**Coverage tools per language:**
- Python: `pytest-cov` (coverage.py)
- TypeScript: `c8` (V8 native coverage)
- Java: JaCoCo (via Maven)
- C#: coverlet (via dotnet test)

## Test Fixtures

**Location:** `tests/fixtures/`

**YAML schema fixtures:**
- `tests/fixtures/tenancy/*.yaml` -- tables with schema-based and database-based tenancy (Documenti, Voci, Registri, Tipologie, Fascicoli)
- `tests/fixtures/mongo/*.yaml` -- MongoDB collection schemas (Accessi, Reparti, Etichette, Segnalazioni, NoteSegnalazione)

**Usage:** Fixtures are copied into temporary project `schemas/db/` directories during test setup, then the generator runs to produce code from them.

## Mocking

**MongoDB:** `tests/mongo/fake_mongo.py` -- a pytest plugin that patches pymongo with mongomock. Activated via `PYTEST_ADDOPTS="-p fake_mongo"`.

**Java EntityManager:** `tests/java/runtime/PagingTest.java` uses a hand-rolled fake EntityManager for testing paging logic without a real database.

**Java stubs:** `tests/java/stubs/` -- stub JPA/Hibernate annotations for `javac` compilation checks without a full framework.

**Database backends for tests:**
- SQLite / sql.js: used in kit tests for fast, in-memory testing
- PostgreSQL: used in CI for dialect-specific DDL and real database testing
- MongoDB (replica set): used in CI for transaction-aware collection tests

## Cross-Language Cursor Compatibility

Tests verify that keyset pagination cursors are interoperable:
- A cursor encoded by TypeScript can be decoded by Python
- A cursor encoded by Python can be decoded by Java (and vice versa)
- Tested in `tests/run.sh` with cross-language assertions

## Idempotency Checks

The generator supports `--check` mode (exit 1 if files would change). This is tested in `tests/run.sh` and used in CI to verify generated code is up to date:
```bash
python3 gen.py <project> --check   # Verify without writing
```

## OpenAPI Contract Validation

When `openapi-spec-validator` is installed, `tests/run.sh` validates that generated OpenAPI 3.0 contracts (`schemas/generated/openapi.yaml`) are spec-compliant.

---

*Testing analysis: 2026-10-17*
