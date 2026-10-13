# Sviluppo del kit

## Struttura del repository

| Percorso | Contenuto |
|---|---|
| `.claude-plugin/marketplace.json` | marketplace pubblico: `/plugin marketplace add ivandilelio/kybes` |
| `install.sh` | scorciatoia per l'installer del plugin |
| `marketplace/` | marketplace di Claude Code; viene copiato nei progetti come `tools/kybes/` |
| `marketplace/plugins/kybes/skills/` | skill `kybes-architecture` |
| `marketplace/plugins/kybes/agents/` | agenti architect, implementer, reviewer |
| `marketplace/plugins/kybes/hooks/hooks.json` | registrazione degli hook |
| `marketplace/plugins/kybes/scripts/` | hook, regole (`rules.py`, `model_guard.py`), `arch_check.py`, `verify.py` (test e soglie di copertura nei progetti) |
| `marketplace/plugins/kybes/scripts/gen/` | generatore: `schema.py` (lettura e validazione), `naming.py` (nomi per linguaggio), `emit_<linguaggio>.py`, `verification.py` (requisiti e casi di test), `test_<linguaggio>.py` (test generati), `gen.py` (orchestrazione) |
| `marketplace/plugins/kybes/install.sh`, `templates/` | installer e file copiati nei progetti: stanno dentro il plugin perché Claude Code, installando dal marketplace, copia solo la cartella del plugin |
| `tests/` | suite di test del kit |
| `docs/` | questa documentazione |

## Test

```bash
tests/run.sh             # tutto quello che la macchina può eseguire
tests/run.sh python      # un gruppo: python, typescript, java, csharp, sql, hooks
```

La suite installa il kit in due progetti temporanei, con i quattro linguaggi e gli schemi di esempio, e poi verifica:

| Gruppo | Verifica | Requisiti |
|---|---|---|
| sempre | generatore idempotente, `arch_check` pulito | python3 |
| `python` | CRUD, relazioni, gerarchie, cascade, vincoli univoci, validazione; paginazione a cursore (pareggi, ordinamenti, cursori manomessi), ogni operatore delle query, Unit of Work con commit, rollback e retry, su SQLite | SQLAlchemy 2 |
| `typescript` | gli stessi casi su sql.js; compilazione `strict` con `noUnusedLocals` anche per il dialetto postgres | Node 20+ e npm |
| `java` | compilazione con `-Xlint:all -Werror` contro stub fedeli di JPA e Hibernate (`tests/java/stubs`); esecuzione della logica di paginazione e Unit of Work con un `EntityManager` finto che registra JPQL e parametri | JDK 17+ |
| `csharp` | sintassi del codice generato con il parser tree-sitter (non sostituisce il compilatore) | `pip install tree-sitter tree-sitter-c-sharp` |
| `sql` | DDL PostgreSQL validato dal parser di PostgreSQL | `pip install pglast` |
| `python`, `typescript` | i test generati nel progetto di prova, eseguiti con `verify.py`: tutti verdi e copertura entro le soglie ASIL; compilazione dei test generati anche per il dialetto postgres | pytest e pytest-cov; c8 |
| sempre (con i gruppi sopra) | compatibilità del cursore tra TypeScript, Python e Java | |
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
4. Aggiungi i casi di test al catalogo in `verification.py` e rendili in `test_python.py` e `test_typescript.py`: la suite controlla che la copertura dei test generati resti entro le soglie.
5. Estendi i test Python e TypeScript del kit e la compilazione Java.
