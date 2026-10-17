# Technology Stack

**Analysis Date:** 2026-10-17

## Languages

**Primary:**
- Python 3.12 - Code generator core (`marketplace/plugins/kybes/scripts/gen/gen.py`, 41 modules), hooks (`marketplace/plugins/kybes/scripts/`), tests (`tests/python/`), CI annotation (`tests/ci/annotate.py`)
- YAML - Schema definition language (input files in `schemas/db/*.yaml`)

**Secondary (generated output targets):**
- TypeScript 5.6+ - Generated TypeORM models and Fastify API (`tests/typescript/`)
- Java 21 - Generated Hibernate/JPA models and API (`tests/java/`)
- C# / .NET 8 - Generated EF Core models and ASP.NET Core minimal API (`tests/csharp/`)
- SQL (DDL) - Generated migration scripts, multi-tenant DDL (`tests/sql/`)

## Runtime

**Environment:**
- Python 3.12 (generator runtime)
- Node.js 22 (TypeScript test runtime)
- JDK 21 Temurin (Java test runtime)
- .NET 8.0 (C# test runtime)

**Package Manager:**
- pip (Python dependencies, no lockfile in repo)
- npm (TypeScript tests, `tests/typescript/package.json`)
- Maven (Java tests, POM at `marketplace/plugins/kybes/templates/scaffold/libs/db-models/java/pom.xml`)
- dotnet CLI (C# tests)

## Frameworks

**Core:**
- No web framework in generator itself — it is a pure code-generation tool

**Generated output uses:**
- SQLAlchemy (Python ORM output)
- TypeORM ^1.1.2 (TypeScript ORM output) via `tests/typescript/package.json`
- Hibernate/JPA (Java ORM output)
- Entity Framework Core (C# ORM output)
- Fastify ^5.2.0 (TypeScript API output) via `tests/typescript/package.json`
- FastAPI (Python API output, installed in CI)
- ASP.NET Core minimal API (C# API output)

**Testing:**
- pytest + pytest-cov (Python)
- Node.js built-in test runner with c8 ^10.1.0 coverage (`tests/typescript/package.json`)
- JUnit + JaCoCo (Java)
- xUnit + Coverlet (C#)

**Build/Dev:**
- GitHub Actions CI (``.github/workflows/kit-tests.yml``)
- Bash (`install.sh`, `tests/run.sh`)

## Key Dependencies

**Critical (Python generator):**
- pglast - PostgreSQL SQL parser (CI dependency)
- tree-sitter + tree-sitter-c-sharp - C# syntax checking (`tests/csharp/syntax_check.py`)
- openapi-spec-validator - OpenAPI contract validation (CI)
- pyarrow - Parquet support for archive
- duckdb - Query engine for archived data

**Infrastructure (CI test services):**
- PostgreSQL 16 - Primary relational DB for generated model tests
- MongoDB 7 (replica set) - Document DB for generated collection tests
- Azurite 3 - Azure Blob Storage emulator for archive tests
- sql.js ^1.11.0 - In-process SQLite for TypeScript unit tests
- mongomock / pymongo - MongoDB mocking and driver for Python tests

**Cloud SDKs (for generated archive/storage code):**
- boto3 - AWS S3 archive target
- azure-storage-blob - Azure Blob archive target
- moto - AWS mock for tests

## Configuration

**Environment:**
- `KYBES_TEST_DATABASE_URL` - PostgreSQL connection for CI tests
- `KYBES_TEST_MONGO_URL` - MongoDB connection for CI tests
- `KYBES_TEST_AZURITE` - Azure Blob emulator connection string
- Project configuration via `model.yaml` in target projects (not in this repo)

**Build:**
- `tsconfig.json` at `tests/typescript/tsconfig.json`
- GitHub Actions workflow at `.github/workflows/kit-tests.yml`
- Install script at `install.sh` (delegates to `marketplace/plugins/kybes/install.sh`)

## Platform Requirements

**Development:**
- Python 3.12+
- Git (projects must be git repos for install.sh)

**Production:**
- Kybes is a development tool / code generator — no production runtime of its own
- Generated code targets: PostgreSQL 16, MongoDB 7, AWS S3, Azure Blob Storage, Kubernetes (for archive jobs)

---

*Stack analysis: 2026-10-17*
