# External Integrations

**Analysis Date:** 2026-10-17

## APIs & External Services

**Claude Code Plugin Ecosystem:**
- Anthropic Claude Code - Plugin/marketplace integration
  - Plugin manifest: `marketplace/plugins/kybes/.claude-plugin/plugin.json`
  - Marketplace listing: `.claude-plugin/marketplace.json`
  - Hooks: `marketplace/plugins/kybes/hooks/hooks.json`
  - Agents: `marketplace/plugins/kybes/agents/` (reviewer, architect, implementer)

**OpenAPI:**
- Generated APIs produce OpenAPI contracts validated in CI with `openapi-spec-validator`
- API generation modules: `marketplace/plugins/kybes/scripts/gen/api_plan.py`, `emit_api_*.py`

## Data Storage

**Databases (generated code targets):**
- PostgreSQL 16
  - Connection: `KYBES_TEST_DATABASE_URL` (tests)
  - Client: SQLAlchemy (Python), TypeORM (TypeScript), Hibernate (Java), EF Core (C#)
  - Multi-tenant modes: row-level security, schema-per-tenant, database-per-tenant (`marketplace/plugins/kybes/scripts/gen/runtime_tenant.py`)
- MongoDB 7 (replica set required for transactions)
  - Connection: `KYBES_TEST_MONGO_URL` (tests)
  - Client: pymongo (Python), mongodb ^7.0.0 (TypeScript)
  - Collection-based models with TTL index support

**File/Object Storage (archive targets):**
- AWS S3 - Hot-to-cold archive via `boto3`
  - Config: `model.archive.s3` (e.g., `s3://kybes-archive/archive`)
  - External query: AWS Athena tables generated for archived data
- Azure Blob Storage - Hot-to-cold archive via `azure-storage-blob`
  - Config: `model.archive.blob` (e.g., `https://<account>.blob.core.windows.net/<container>/prefix`)
  - External query: Azure Synapse serverless views generated
  - Local emulator: Azurite for tests

**Archive format:**
- Parquet (via pyarrow) and DuckDB for query

**Caching:**
- None detected

## Authentication & Identity

**Auth Provider:**
- Not applicable — Kybes is a code generator, not a running service
- Generated multi-tenant code handles tenant isolation via configurable `tenant-id` column

## Monitoring & Observability

**Error Tracking:**
- None (development tool)

**Logs:**
- Python `print`-based output in generator
- CI annotation system via `tests/ci/annotate.py`

## CI/CD & Deployment

**Hosting:**
- Distributed as a Claude Code plugin via marketplace (`marketplace/plugins/kybes/`)

**CI Pipeline:**
- GitHub Actions (`.github/workflows/kit-tests.yml`)
- Jobs: `tests`, `generated-java`, `generated-csharp`, `generated-python-typescript`
- Services: PostgreSQL 16, MongoDB 7 (Docker), Azurite (npx)
- Coverage thresholds enforced per ASIL level via `marketplace/plugins/kybes/scripts/verify.py`

**Plugin Validation:**
- `npx @anthropic-ai/claude-code plugin validate` in CI

## Environment Configuration

**Required env vars (CI only):**
- `KYBES_TEST_DATABASE_URL` - PostgreSQL connection
- `KYBES_TEST_MONGO_URL` - MongoDB connection
- `KYBES_TEST_AZURITE` - Azurite connection string

**Secrets location:**
- No secrets in repository; test credentials are ephemeral CI service defaults

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None

## Kubernetes Integration (Generated)

**Archive Jobs:**
- Kubernetes Job manifests generated for archive/retention operations
  - Config: namespace, service account, image, DB secret
  - Scaling modes: cron, KEDA (event-driven), engine
  - Source: `marketplace/plugins/kybes/scripts/gen/emit_archive.py`
  - Job engine: `marketplace/plugins/kybes/scripts/gen/engine/`

---

*Integration audit: 2026-10-17*
