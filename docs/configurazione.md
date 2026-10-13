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
  "duplicates": { "min_lines": 8, "include_tests": false, "ignore": [] },
  "post_edit_commands": { "**/*.py": ["ruff check --quiet {file}"] },
  "stop_gate": { "enabled": true, "only_if_changes": true, "max_blocks": 3, "commands": ["pytest -q"] }
}
```

## Sezioni

| Sezione | Contenuto |
|---|---|
| `paths` | glob delle aree del progetto, usate dalle regole. Si aggiungono ai default; `ignore` e `protected` restano sempre attivi |
| `rules` | livello di ogni regola: `block`, `warn` o `off` (elenco in [controlli](controlli.md)) |
| `model.targets` | una voce per linguaggio del modello: `lang`, `dir`, e per C# `namespace`, per Java `package`; `dialect` vale `postgres` o `sqlite` |
| `duplicates` | soglia di righe per il controllo duplicati, inclusione dei test, glob da escludere |
| `extra_forbidden_modules` | moduli di database aggiuntivi da vietare fuori dal model; prefisso `js:` per i pacchetti npm |
| `post_edit_commands` | comandi per glob di file eseguiti dopo ogni scrittura; `{file}` è il file assoluto, `{rel}` quello relativo. Se il comando non è installato viene saltato |
| `stop_gate` | comandi eseguiti a fine lavoro (test, copertura); `only_if_changes` li salta se git non vede modifiche |

## Installer

```bash
./install.sh --target <repo> [opzioni]
```

| Opzione | Default | Effetto |
|---|---|---|
| `--fn-lang`, `--ms-lang` | `python`, `typescript` | linguaggi di function e microservizi (`python`, `typescript`, `csharp`, `java`) |
| `--model-langs` | function + microservizi | linguaggi in cui generare il modello |
| `--namespace`, `--java-package` | `App.Model`, `app.model` | namespace C# e package Java del modello |
| `--scaffold` | no | struttura delle cartelle, modulo errori, `schemas/openapi.yaml` |
| `--examples` | no | 5 schemi di esempio e generazione |
| `--ci` | `github` | workflow di controllo |
| `--scope` | `local` | dove registrare il plugin in Claude Code |
| `--no-plugin` | no | solo file, senza registrare il plugin |
| `--force` | no | rigenera configurazione, regole e scaffold esistenti |
| `--uninstall` | no | rimuove kit, regole e blocco in CLAUDE.md |

Ogni collega, dopo il clone del progetto, esegue una volta `tools/kybes/setup.sh`.
