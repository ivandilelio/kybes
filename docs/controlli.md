# Controlli

I controlli girano in tre momenti: prima di ogni scrittura, dopo ogni scrittura e a fine lavoro. La stessa logica gira in CI, quindi una regola non si aggira lavorando fuori da Claude Code.

## Prima della scrittura (`pre_write`)

La scrittura viene rifiutata e l'agente riceve il motivo con la correzione da fare.

| Regola | Cosa blocca | Livello predefinito |
|---|---|---|
| `orm_outside_db_models` | import di ORM o driver di database fuori dal model (Python, TypeScript/JavaScript, C#, Java) | block |
| `hardcoded_secrets` | chiavi AWS, chiavi private, token, password in chiaro | block |
| `protected_paths` | modifiche al kit e alla sua configurazione | block |
| `generated_files` | modifiche ai file generati, ai JSON Schema e a `MODEL_INDEX.md` | block |
| `model_layout` | file o sottocartelle nella cartella model che non corrispondono a una tabella | block |
| `custom_method_collision` | metodi custom con il nome di un metodo generato | block |

## Dopo la scrittura (`post_edit`)

| Azione | Quando |
|---|---|
| rigenerazione del model e notifica all'agente dei file aggiornati | salvataggio di uno schema |
| errori dello schema rimandati all'agente, nessun file toccato | schema non valido |
| aggiornamento di `MODEL_INDEX.md` | salvataggio di un file custom |
| linter configurati in `post_edit_commands` | ogni file che corrisponde al pattern |
| avvisi architetturali | ogni file di codice |

Gli avvisi coprono, con livello predefinito `warn`:

| Regola | Cosa segnala |
|---|---|
| `raw_sql_outside_db_models` | SQL scritto a mano fuori dal model |
| `error_leak` | messaggi di eccezione o stack trace nelle risposte, eccezioni ignorate |
| `utils_impure` | rete, database, SDK cloud o variabili d'ambiente in `libs/utils` |
| `function_long_running` | attese lunghe o WebSocket nelle Lambda |

## A fine lavoro (`stop_gate`)

Vale per la sessione principale e per ogni subagent. Il lavoro non si chiude finché passano tutti:

1. `arch_check`: tutte le regole su tutto il repository, compreso il **codice duplicato** (blocchi di almeno 8 righe significative uguali in due punti);
2. `gen --check`: file generati allineati agli schemi, nessun file custom orfano, nessun conflitto di nomi;
3. i comandi in `stop_gate.commands` (test, contract test, copertura).

Dopo 3 rifiuti consecutivi nella stessa sessione il lavoro può chiudersi, con un avviso che elenca i problemi rimasti. Questo evita che un agente resti bloccato all'infinito.

## In CI

Il workflow `.github/workflows/architecture-check.yml` esegue `gen --check` e `arch_check --strict`. In modalità strict anche gli avvisi fanno fallire la build.

## Livelli e configurazione

Ogni regola si imposta su `block`, `warn` o `off` in `.claude/kybes.config.json` (vedi [configurazione](configurazione.md)). Il file di configurazione è protetto: l'agente non può modificarlo, lo cambi tu.
