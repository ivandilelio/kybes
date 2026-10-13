# kybes

Know Your Backend: un plugin che aiuta l'AI a generare applicazioni Model/View/Controller strutturate, senza sorprese, senza codice duplicato e con le stesse modalità in ogni progetto.

Regole architetturali, agenti e controlli automatici di Claude Code per generare gestionali cloud coerenti: API Gateway, Lambda o Kubernetes, Job KEDA, DB-Models, Utils, errori, CDN e SSO.

## Installazione

```bash
./install.sh --target /percorso/del/repo --scaffold
```

| Opzione | Default | Cosa fa |
|---|---|---|
| `--target DIR` | `.` | repository del gestionale |
| `--fn-lang` | `python` | linguaggio delle function (`python`, `typescript`, `csharp`, `java`) |
| `--ms-lang` | `typescript` | linguaggio dei microservizi (stessi valori) |
| `--model-langs` | function + microservizi | linguaggi in cui generare il modello, es. `csharp,python,typescript,java` |
| `--namespace` | `App.Model` | namespace C# del modello |
| `--java-package` | `app.model` | package Java del modello |
| `--examples` | no | copia 5 schemi di esempio in `schemas/db` e genera il modello |
| `--scaffold` | no | crea la struttura di cartelle, il modulo errori e `schemas/openapi.yaml` |
| `--ci` | `github` | aggiunge il workflow di controllo (`github`, `none`) |
| `--scope` | `local` | dove registrare il plugin in Claude Code (`local`, `project`, `user`) |
| `--no-plugin` | no | copia i file senza registrare il plugin |
| `--force` | no | rigenera configurazione, regole e scaffold esistenti |
| `--uninstall` | no | rimuove kit, regole e blocco in CLAUDE.md |

Puoi rilanciare l'installer per aggiornare il kit: configurazione e file tuoi restano invariati.

Ogni collega, dopo il clone, esegue una volta:

```bash
tools/claude-gestionale/setup.sh
```

Serve `python3`; il comando `claude` serve per registrare il plugin.

## Cosa installa nel repository

| Percorso | Ruolo |
|---|---|
| `tools/claude-gestionale/` | il plugin: skill, agenti, hook e script di controllo |
| `.claude/gestionale.config.json` | cartelle, livello di ogni regola (`block`/`warn`/`off`), linter, comandi di test |
| `.claude/rules/gestionale/*.md` | regole caricate solo quando Claude tocca la cartella corrispondente |
| `CLAUDE.md` | blocco di principi e istruzioni d'uso degli agenti, tra i marcatori `gestionale-kit` |
| `.github/workflows/architecture-check.yml` | gli stessi controlli in CI |

## Modello dati: uno schema, sempre gli stessi file

Ogni tabella è descritta da `schemas/db/<Tabella>.yaml` (colonne, chiave, vincoli, relazioni, indici). Il generatore produce in ogni linguaggio configurato:

| Linguaggio | File custom, punto d'ingresso | File generati (non si toccano) |
|---|---|---|
| C# (EF Core 8) | `model/Clienti.cs` | `model/generated/Clienti.cs`, `AppDbContext.cs` |
| Python (SQLAlchemy 2) | `model/Clienti.py` | `model/generated/Clienti.py` |
| TypeScript (TypeORM) | `model/Clienti.ts` | `model/generated/Clienti.ts`, `index.ts` |
| Java (JPA 3.1 / Hibernate 6) | `model/ClientiRepository.java` | `model/generated/Clienti.java`, `ClientiRepositoryBase.java` |

Ogni tabella riceve sempre gli stessi metodi:
- leggi per chiave, lista paginata, conteggio, esistenza;
- crea, aggiorna ed elimina, con validazione;
- `findBy` per le colonne univoche e `listBy` per le chiavi esterne;
- lettura del padre e dei figli per ogni relazione.

Il generatore produce anche `schemas/json/<Tabella>.schema.json` per la validazione delle API e `MODEL_INDEX.md`, l'indice di tutte le tabelle con file e metodi generati e custom.

```bash
python3 tools/claude-gestionale/plugins/gestionale-cloud/scripts/gen/gen.py .          # genera
python3 tools/claude-gestionale/plugins/gestionale-cloud/scripts/gen/gen.py . --check  # verifica (CI)
```

Con Claude Code non serve lanciarlo: parte da solo ogni volta che uno schema viene salvato.

Note per linguaggio:
- **Java:** con colonne `json` su PostgreSQL serve una libreria JSON nel classpath (es. `jackson-databind`). Le annotazioni `@OnDelete` e `@JdbcTypeCode` richiedono Hibernate 6.2+.
- **C#:** richiede `net8.0` con `Microsoft.EntityFrameworkCore` 8 e il provider del database (es. `Npgsql.EntityFrameworkCore.PostgreSQL`).
- **TypeScript:** `dialect` `postgres` (default) o `sqlite` nella configurazione del target.

## Come lavora con Claude Code

- **Agenti** (con la skill precaricata):
  - `gestionale-cloud:architect` sostituisce il Plan integrato, che non legge CLAUDE.md;
  - `gestionale-cloud:implementer` esegue un task alla volta;
  - `gestionale-cloud:reviewer` verifica le modifiche in modo indipendente.
- **Prima di ogni scrittura** l'hook rifiuta:
  - ORM o driver DB fuori dal modello, in tutti e quattro i linguaggi;
  - segreti in chiaro;
  - modifiche ai file del kit;
  - modifiche ai file generati;
  - file nella cartella model che non corrispondono a una tabella;
  - metodi custom con il nome di un metodo generato.
- **Dopo il salvataggio di uno schema** il generatore aggiorna tutti i linguaggi, i JSON Schema e l'indice, e lo comunica all'agente.
- **Dopo ogni scrittura** l'hook rimanda all'agente avvisi architetturali ed errori dei linter, da correggere subito. Gli avvisi coprono: SQL a mano, dettagli interni negli errori, Utils impura, attese lunghe o WebSocket nelle function.
- **A fine lavoro**, anche di ogni subagent, l'hook impedisce la chiusura finché non passano:
  - `arch_check`, che controlla regole, struttura e codice duplicato (blocchi di 8 o più righe);
  - `gen --check`;
  - i comandi in `stop_gate.commands`.

  Dopo 3 tentativi lascia chiudere con un avviso.

Il controllo completo si lancia anche a mano:

```bash
python3 tools/claude-gestionale/plugins/gestionale-cloud/scripts/arch_check.py . [--strict] [--json]
```

Per vedere il payload reale ricevuto dagli hook, avvia Claude Code con `GESTIONALE_HOOK_DEBUG=1`. I file vengono salvati nella cartella temporanea come `gestionale-hook-*.json`.
