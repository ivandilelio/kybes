# Sviluppo del kit

## Struttura del repository

| Percorso | Contenuto |
|---|---|
| `install.sh` | installer da usare sui progetti |
| `marketplace/` | marketplace di Claude Code; viene copiato nei progetti come `tools/kybes/` |
| `marketplace/plugins/kybes/skills/` | skill `kybes-architecture` |
| `marketplace/plugins/kybes/agents/` | agenti architect, implementer, reviewer |
| `marketplace/plugins/kybes/hooks/hooks.json` | registrazione degli hook |
| `marketplace/plugins/kybes/scripts/` | hook, regole (`rules.py`, `model_guard.py`), `arch_check.py` |
| `marketplace/plugins/kybes/scripts/gen/` | generatore: `schema.py` (lettura e validazione), `naming.py` (nomi per linguaggio), `emit_<linguaggio>.py`, `gen.py` (orchestrazione) |
| `templates/` | file copiati nei progetti dall'installer |
| `tests/` | suite di test del kit |
| `docs/` | questa documentazione |

## Test

```bash
tests/run.sh             # tutto quello che la macchina può eseguire
tests/run.sh python      # un gruppo: python, typescript, java, hooks
```

La suite installa il kit in due progetti temporanei, con i quattro linguaggi e gli schemi di esempio, e poi verifica:

| Gruppo | Verifica | Requisiti |
|---|---|---|
| sempre | generatore idempotente, `arch_check` pulito | python3 |
| `python` | CRUD, relazioni, gerarchie, cascade, vincoli univoci e validazione su SQLite | SQLAlchemy 2 |
| `typescript` | gli stessi casi su sql.js; compilazione `strict` anche per il dialetto postgres | Node 20+ e npm |
| `java` | compilazione con `-Xlint:all -Werror` contro stub fedeli di JPA e Hibernate (`tests/java/stubs`) | JDK 17+ |
| `hooks` | ogni regola con l'esito atteso (rifiuto o consenso), rigenerazione automatica, duplicati, blocco a fine lavoro | python3 |

Il codice C# non ha un test eseguibile nella suite: serve un SDK .NET. Prima di un rilascio va compilato in un progetto `net8.0` con EF Core 8.

## Aggiungere una regola

1. Implementa la regola in `rules.py` (contenuto dei file) o in `model_guard.py` (struttura del modello) e restituisci `Finding` con il livello letto dalla configurazione.
2. Aggiungi il livello predefinito in `DEFAULT_CONFIG` e nella configurazione scritta dall'installer.
3. Aggiungi un caso con l'esito atteso in `tests/hooks/test_hooks.sh`.
4. Documentala in `docs/controlli.md`.

## Aggiungere una capacità al generatore

1. Specifica la chiave in `docs/schema-yaml.md`.
2. Validala in `schema.py`: le chiavi sconosciute vengono rifiutate.
3. Implementala in tutti gli emettitori, con gli stessi nomi tramite `naming.py`.
4. Estendi i test Python e TypeScript e la compilazione Java.
