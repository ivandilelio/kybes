---
name: kybes-init
description: Set up kybes in the current project (config, path rules, CLAUDE.md block, scaffold, CI, optional example schemas, first model generation). Use when the user asks to install, initialise, set up or update kybes in a repository.
---

# Set up kybes in a project

kybes needs a small amount of project configuration before its hooks and generator become active: until `.claude/kybes.config.json` exists, every kybes hook is a no-op in that repository.

1. Find the plugin root: it is two directories above this skill's directory (`<plugin root>/skills/kybes-init/`). The installer is `<plugin root>/install.sh`.
2. Ask the user, in one AskUserQuestion call, only what is not already clear from the conversation or the repository:
   - languages of the data model (`csharp`, `python`, `typescript`, `java`, one or more);
   - C# namespace and/or Java package, if those languages are selected;
   - default multi-tenant mode of the tables (`--tenancy none|column|schema|database`, default `none`) and the tenant id type (`--tenant-id uuid|string`, default `uuid`);
   - default ASIL of the tables (`QM`, `A`, `B`, `C`, `D`; default `B`): it sets the coverage thresholds of the generated ISO 26262-6 unit tests;
   - where the archive lives, if the project will archive old data: `--archive-s3 s3://bucket/prefix` and/or `--archive-blob https://<account>.blob.core.windows.net/<container>/prefix` (defaults are placeholders, changeable later in `model.archive`);
   - whether to create the standard folder scaffold (`--scaffold`) and the example schemas (`--examples`).
3. Run the installer from the project root:

   ```bash
   bash "<plugin root>/install.sh" --target . --model-langs <langs> [--namespace X] [--java-package y] [--asil B] [--tenancy column] [--archive-s3 s3://bucket/prefix] [--scaffold] [--examples]
   ```

   The installer is idempotent: it never overwrites the user's config, rules or files (only with `--force`), and it refreshes the `kybes` block in `CLAUDE.md`.
4. Report what was created in a few lines:
   - `.claude/kybes.config.json`;
   - `.claude/rules/kybes/`;
   - `tools/kybes/`, the versioned copy used by CI;
   - `MODEL_INDEX.md`, if schemas exist;
   - the generated unit tests in `libs/db-models/<lang>/tests/generated/` and the verification docs in `docs/generated/verification/`.

   To run the model tests, the DB-models packages need their test tools (the scaffold creates the package files): `pip install -e "libs/db-models/python[test]"`, `npm install` in `libs/db-models/typescript`, Maven for `libs/db-models/java/pom.xml`, the .NET 8 SDK for `libs/db-models/csharp`. Java and C# tests run on PostgreSQL: set `KYBES_TEST_DATABASE_URL=postgresql://user:password@host:5432/db` (a local `postgres:16` container is enough). Then `python3 -B tools/kybes/plugins/kybes/scripts/verify.py .` runs the tests and checks coverage per ASIL.

   Then suggest the next step: describe a table in `schemas/db/<Table>.yaml`; the model is generated automatically when the schema is saved.

Do not edit `.claude/kybes.config.json` yourself after installation: it is protected, and only the user changes it.
