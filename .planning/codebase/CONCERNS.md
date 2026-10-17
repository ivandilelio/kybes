# Codebase Concerns

**Analysis Date:** 2026-10-17

## Tech Debt

**Massive code generation modules with heavy duplication:**
- Issue: Each target language (Python, Java, C#, TypeScript) has a parallel set of emitter, runtime, and test generator files with very similar structure. The four `emit_*.py` files total ~3,000 lines, the four `runtime_api_*.py` files total ~4,000 lines, and the four `test_*.py` files total ~3,800 lines. Much of the logic (field mapping, validation patterns, pagination) is duplicated across languages with only syntax differences.
- Files: `marketplace/plugins/kybes/scripts/gen/emit_python.py` (686 lines), `marketplace/plugins/kybes/scripts/gen/emit_java.py` (844 lines), `marketplace/plugins/kybes/scripts/gen/emit_csharp.py` (768 lines), `marketplace/plugins/kybes/scripts/gen/emit_typescript.py` (716 lines), and their corresponding `runtime_api_*.py` and `test_*.py` counterparts
- Impact: Adding a new feature (e.g., a new column type or API operation) requires changes in 12+ files across all four language tracks. High risk of inconsistency between languages.
- Fix approach: Extract language-agnostic logic (field iteration, validation rules, pagination structure) into shared data structures or a template engine, reducing each emitter to language-specific syntax only.

**sys.path manipulation for imports:**
- Issue: Multiple scripts use `sys.path.insert(0, ...)` to make sibling modules importable, then suppress linting with `# noqa: E402`. This is a workaround for the lack of a proper Python package structure.
- Files: `marketplace/plugins/kybes/scripts/gen/gen.py` (lines 21-22), `marketplace/plugins/kybes/scripts/verify.py` (lines 36-41), `marketplace/plugins/kybes/scripts/model_guard.py` (lines 14-19)
- Impact: Fragile import resolution; breaks if scripts are invoked from unexpected working directories. IDE navigation and refactoring tools may not resolve these imports.
- Fix approach: Convert `scripts/gen/` into a proper Python package with `pyproject.toml` or at minimum an `__init__.py` and relative imports.

**Custom YAML parser instead of standard library:**
- Issue: A hand-rolled YAML parser (`miniyaml.py`) is used as a fallback when PyYAML is not installed. This parser supports only a subset of YAML and must be maintained in parallel with any schema format changes.
- Files: `marketplace/plugins/kybes/scripts/gen/miniyaml.py`
- Impact: Potential parsing differences between miniyaml and PyYAML. Any new YAML feature used in schemas may silently fail with the fallback parser.
- Fix approach: Either require PyYAML as a dependency (it's ubiquitous) or add comprehensive tests comparing miniyaml output against PyYAML for all fixture files.

## Security Considerations

**shell=True in subprocess calls:**
- Risk: Two files use `subprocess.run(cmd, shell=True, ...)` where `cmd` comes from configuration (`stop_gate.commands` and `post_edit` hook commands). If a project's `kybes.json` config is attacker-controlled, this allows arbitrary command execution.
- Files: `marketplace/plugins/kybes/scripts/stop_gate.py` (line 78), `marketplace/plugins/kybes/scripts/post_edit.py` (line 34)
- Current mitigation: Commands come from a project-local config file that the developer controls. The timeout (600s) limits runaway processes.
- Recommendations: Document the trust boundary clearly. Consider using `shlex.split()` with `shell=False` where possible, or at least validate commands against an allowlist pattern.

**No .env in .gitignore:**
- Risk: The `.gitignore` file does not contain any `.env` pattern. If a user adds environment files with secrets to a kybes-managed project, they could be committed accidentally.
- Files: `.gitignore`
- Current mitigation: No `.env` files currently exist in the repo.
- Recommendations: Add `.env*` to `.gitignore` as a safety net.

## Performance Bottlenecks

**Full schema reload on every generator invocation:**
- Problem: `gen.py` loads and validates all YAML schemas from disk on every run, even in `--check` mode. For projects with many tables, this involves parsing dozens of YAML files and running cross-table validation.
- Files: `marketplace/plugins/kybes/scripts/gen/gen.py`, `marketplace/plugins/kybes/scripts/gen/schema.py`
- Cause: No caching or incremental generation. The generator always processes all tables.
- Improvement path: Add a content-hash-based cache so unchanged schemas skip regeneration. Store hashes in a manifest file alongside generated output.

**Stop gate runs all checks serially:**
- Problem: The stop gate hook runs `arch_check`, then `gen --check`, then each custom command sequentially. In projects with multiple custom commands, this can take several minutes.
- Files: `marketplace/plugins/kybes/scripts/stop_gate.py` (lines 63-83)
- Cause: Sequential `subprocess.run` calls with a 600s timeout each.
- Improvement path: Run independent checks in parallel using `concurrent.futures` or `asyncio.subprocess`.

## Fragile Areas

**Generator output stability:**
- Files: All `marketplace/plugins/kybes/scripts/gen/emit_*.py` and `marketplace/plugins/kybes/scripts/gen/runtime_*.py`
- Why fragile: Generated code is compared byte-for-byte in `--check` mode. Any whitespace or ordering change in the emitter breaks CI. The emitters build code via string concatenation with f-strings, making it hard to predict exact output.
- Safe modification: Always run `gen.py` in normal mode after changes, then diff the output. Never change formatting without also updating all test expectations.
- Test coverage: The `tests/` directory covers model/access/archive behavior but does not have unit tests for individual emitter functions. The engine has its own test suite at `marketplace/plugins/kybes/scripts/gen/engine/tests/test_engine.py`.

**miniyaml parser:**
- Files: `marketplace/plugins/kybes/scripts/gen/miniyaml.py`
- Why fragile: Hand-written recursive parser for a subset of YAML. Edge cases in quoting, escaping, or nested inline structures could produce silent data corruption.
- Safe modification: Test any change against all fixture files in `tests/fixtures/`.
- Test coverage: No dedicated unit tests for miniyaml found.

## Test Coverage Gaps

**No unit tests for code emitters:**
- What's not tested: The 12+ emitter modules (`emit_*.py`, `runtime_*.py`, `test_*.py`) that produce generated code for Python/Java/C#/TypeScript have no direct unit tests. Correctness is only verified indirectly via `gen --check` comparing full output.
- Files: `marketplace/plugins/kybes/scripts/gen/emit_python.py`, `marketplace/plugins/kybes/scripts/gen/emit_java.py`, `marketplace/plugins/kybes/scripts/gen/emit_csharp.py`, `marketplace/plugins/kybes/scripts/gen/emit_typescript.py`
- Risk: A bug in one emitter function (e.g., wrong type mapping for `decimal` in C#) could go undetected until a user hits it in a generated project. Full-output comparison tests are brittle and don't isolate failures.
- Priority: Medium

**No tests for miniyaml:**
- What's not tested: The custom YAML parser has no dedicated test file.
- Files: `marketplace/plugins/kybes/scripts/gen/miniyaml.py`
- Risk: Parsing regressions could silently corrupt schema loading when PyYAML is absent.
- Priority: High

**No tests for hook scripts:**
- What's not tested: `stop_gate.py`, `post_edit.py`, `pre_write.py`, `model_guard.py` have no unit tests. `tests/hooks/test_hooks.sh` exists but is a shell script with limited coverage.
- Files: `marketplace/plugins/kybes/scripts/stop_gate.py`, `marketplace/plugins/kybes/scripts/post_edit.py`, `marketplace/plugins/kybes/scripts/pre_write.py`
- Risk: Hook logic errors (counter management, config parsing, failure aggregation) could block or silently skip checks.
- Priority: Medium

**Java tests use stub libraries, not real dependencies:**
- What's not tested: Java tests compile against hand-written stub classes in `tests/java/stubs/` that mimic Jakarta Persistence, Spring, MongoDB, and JUnit APIs. These stubs may drift from actual library behavior.
- Files: `tests/java/stubs/` (80+ stub files)
- Risk: Generated Java code may compile against stubs but fail with real libraries if API signatures have changed.
- Priority: Low (compilation check is still valuable)

## Dependencies at Risk

**No dependency management for Python scripts:**
- Risk: The generator scripts have no `requirements.txt` or `pyproject.toml`. Dependencies (PyYAML optional, pytest/pytest-cov/pyarrow/sqlalchemy for verification) are checked at runtime with try/except imports in `verify.py`.
- Impact: Users may get cryptic errors if dependencies are missing. Version pinning is absent.
- Migration plan: Add a `pyproject.toml` with optional dependency groups for different verification levels.

## Missing Critical Features

**No incremental generation:**
- Problem: The generator always regenerates all files for all tables and all target languages. There is no way to regenerate only files affected by a schema change.
- Blocks: Fast iteration on large projects with many schemas and multiple language targets.

**No generated code diffing/migration support:**
- Problem: When a schema changes (e.g., adding a column), the generator overwrites generated code but does not produce database migration scripts (ALTER TABLE, etc.).
- Blocks: Safe schema evolution in production environments.

---

*Concerns audit: 2026-10-17*
