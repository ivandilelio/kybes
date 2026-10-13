# Configurazione

La configurazione di un progetto sta in `.claude/kybes.config.json`. L'installer la crea alla prima esecuzione e poi non la tocca più, a meno di usare `--force`. L'agente non può modificarla.

```json
{
  "version": 1,
  "cloud": "aws",
  "languages": { "functions": "python", "microservices": "typescript" },
  "paths": {
    "db_models": ["libs/db-models/**"],
    "functions": ["services/*/functions/**"],
    "microservices": ["services/*/ms/**"],
    "jobs": ["jobs/**"],
    "utils": ["libs/utils/**"],
    "errors": ["libs/errors/**"],
    "frontend": ["frontend/**"],
    "infra": ["infra/**"]
  },
  "rules": { "orm_outside_db_models": "block", "duplicate_code": "block", "error_leak": "warn" },
  "model": {
    "schema_dir": "schemas/db",
    "json_schema_dir": "schemas/generated/json",
    "index_file": "MODEL_INDEX.md",
    "targets": [
      { "lang": "csharp", "dir": "libs/db-models/csharp/src/model", "namespace": "App.Model", "dialect": "postgres" },
      { "lang": "python", "dir": "libs/db-models/python/src/model" },
      { "lang": "typescript", "dir": "libs/db-models/typescript/src/model", "dialect": "postgres" },
      { "lang": "java", "dir": "libs/db-models/java/src/main/java/app/model", "package": "app.model", "dialect": "postgres" }
    ]
  },
  "verification": {
    "asil": "B",
    "generate_tests": true,
    "docs_dir": "docs/generated/verification",
    "coverage_reports": ["coverage/*.cobertura.xml", "coverage/*.jacoco.xml"],
    "thresholds": { "A": { "statement": 90 }, "B": { "statement": 95, "branch": 90 }, "C": { "statement": 100, "branch": 95 }, "D": { "statement": 100, "branch": 100 } }
  },
  "duplicates": { "min_lines": 8, "include_tests": false, "ignore": [] },
  "post_edit_commands": { "**/*.py": ["ruff check --quiet {file}"] },
  "stop_gate": { "enabled": true, "only_if_changes": true, "max_blocks": 3, "commands": ["python3 -B tools/kybes/plugins/kybes/scripts/verify.py . --quiet"] }
}
```

## Sezioni

| Sezione | Contenuto |
|---|---|
| `paths` | glob delle aree del progetto, usate dalle regole. Si aggiungono ai default; `ignore` e `protected` restano sempre attivi |
| `rules` | livello di ogni regola: `block`, `warn` o `off` (elenco in [controlli](controlli.md)) |
| `model.targets` | una voce per linguaggio del modello: `lang`, `dir`, e per C# `namespace`, per Java `package`; `dialect` vale `postgres` o `sqlite` |
| `verification` | ASIL predefinito delle tabelle, generazione dei test, cartella delle evidenze, report di copertura da controllare, soglie per ASIL (dettagli in [verifica](verifica.md)) |
| `duplicates` | soglia di righe per il controllo duplicati, inclusione dei test, glob da escludere |
| `extra_forbidden_modules` | moduli di database aggiuntivi da vietare fuori dal model; prefisso `js:` per i pacchetti npm |
| `post_edit_commands` | comandi per glob di file eseguiti dopo ogni scrittura; `{file}` è il file assoluto, `{rel}` quello relativo. Se il comando non è installato viene saltato |
| `stop_gate` | comandi eseguiti a fine lavoro (test, copertura); `only_if_changes` li salta se git non vede modifiche |

## Installer

Dal marketplace di Claude Code:

```text
/plugin marketplace add ivandilelio/kybes
/plugin install kybes@kybes
```

Poi, nel progetto, chiedi a Claude di configurare kybes: la skill `kybes-init` esegue l'installer con le opzioni scelte.

Dalla riga di comando, con il repository clonato:

```bash
./install.sh --target <repo> [opzioni]
```

| Opzione | Default | Effetto |
|---|---|---|
| `--fn-lang`, `--ms-lang` | `python`, `typescript` | linguaggi di function e microservizi (`python`, `typescript`, `csharp`, `java`) |
| `--model-langs` | function + microservizi | linguaggi in cui generare il modello |
| `--namespace`, `--java-package` | `App.Model`, `app.model` | namespace C# e package Java del modello |
| `--asil` | `B` | ASIL predefinito delle tabelle (`QM`, `A`, `B`, `C`, `D`) |
| `--scaffold` | no | struttura delle cartelle, modulo errori, `schemas/openapi.yaml`, pacchetti DB-Models (`pyproject.toml`, `package.json` e `tsconfig.json`, `pom.xml`, `src/DbModels.csproj` e `tests/DbModels.Tests.csproj`) |
| `--examples` | no | 5 schemi di esempio e generazione |
| `--ci` | `github` | workflow di controllo |
| `--scope` | `local` | dove registrare il plugin in Claude Code |
| `--no-plugin` | no | solo file, senza registrare il plugin |
| `--force` | no | rigenera configurazione, regole e scaffold esistenti |
| `--uninstall` | no | rimuove kit, regole e blocco in CLAUDE.md |

Ogni collega, dopo il clone del progetto, esegue una volta `tools/kybes/setup.sh`.
