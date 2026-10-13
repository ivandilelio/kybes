# kybes (Claude Code plugin)

Know Your Backend: makes AI-generated backends predictable. The same folders, file names and data-access methods in every project, no duplicated code, rules enforced by hooks.

## What's inside

| Component | Purpose |
|---|---|
| `skills/kybes-architecture` | architectural rules: runtimes, layers, data model, queries, pagination, transactions, errors, SSO |
| `skills/kybes-init` | sets up kybes in a project (config, path rules, CLAUDE.md block, scaffold, CI) |
| `agents/architect`, `implementer`, `reviewer` | planning, implementation and independent review, with the architecture skill preloaded |
| `hooks/hooks.json` | `PreToolUse` (deny non-compliant writes), `PostToolUse` (regenerate model, lint), `Stop`/`SubagentStop` (block completion until checks pass) |
| `scripts/gen/` | deterministic generator: YAML schema → C#, Python, TypeScript and Java models, JSON Schema, PostgreSQL DDL, index analysis, `MODEL_INDEX.md`, ISO 26262-6 unit tests and verification docs |
| `scripts/verify.py` | runs generated and custom model tests, gates structural coverage per table ASIL |
| `install.sh`, `templates/` | project installer and the files it copies |

## Quick start

```text
/plugin marketplace add ivandilelio/kybes
/plugin install kybes@kybes
```

Then ask Claude, inside your project: *"set up kybes in this project"*.

Hooks are inactive in a repository until it has `.claude/kybes.config.json`, so installing the plugin does not affect other projects.

Full documentation: https://github.com/ivandilelio/kybes
