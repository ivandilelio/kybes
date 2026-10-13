# kybes

**Know Your Backend**: un plugin che aiuta l'AI a generare applicazioni Model/View/Controller strutturate, senza sorprese, senza codice duplicato e con le stesse modalità in ogni progetto.

Con kybes, in qualunque progetto e su qualunque quantità di codice, sai già dove trovare le cose:
- `schemas/db/Clienti.yaml` descrive la tabella;
- `model/Clienti.cs` (o `.py`, `.ts`, `ClientiRepository.java`) espone CRUD, relazioni e metodi custom di quella tabella;
- `MODEL_INDEX.md` elenca tutto il resto.

## Come funziona

1. **Il codice ripetitivo lo produce un generatore, non l'AI.** Dagli schemi YAML nascono entità, CRUD, relazioni, validazione e JSON Schema in C# (EF Core), Python (SQLAlchemy), TypeScript (TypeORM) e Java (JPA). I file sono sempre gli stessi, con gli stessi nomi.
2. **Le regole arrivano all'AI nel momento giusto**, tramite una skill, regole per cartella e tre agenti: architect, implementer e reviewer.
3. **Le regole verificabili sono controlli automatici.** Gli hook di Claude Code e la CI rifiutano:
   - l'accesso ai dati fuori dal model;
   - le modifiche ai file generati;
   - i file fuori posto;
   - il codice duplicato;
   - i segreti in chiaro.

   Il lavoro non si chiude finché i controlli non passano.

## Installazione in un progetto

```bash
git clone https://github.com/ivandilelio/kybes
kybes/install.sh --target /percorso/del/progetto --scaffold --examples \
  --model-langs csharp,python,typescript,java
```

Rilanciarlo aggiorna il kit senza toccare i tuoi file. Ogni collega, dopo il clone del progetto, esegue `tools/kybes/setup.sh`.

## Documentazione

| | |
|---|---|
| [Architettura](docs/architettura.md) | livelli, runtime, flusso di lavoro con Claude Code |
| [Struttura delle cartelle](docs/struttura-cartelle.md) | dove finisce ogni file, generato o tuo |
| [Schema delle tabelle](docs/schema-yaml.md) | specifica completa di `schemas/db/<Tabella>.yaml` |
| [Generatore](docs/generatore.md) | cosa produce e con quali nomi |
| [Query e indici](docs/query-e-indici.md) | query dichiarate, indici automatici, DDL |
| [Paginazione](docs/paginazione.md) | contratto a cursore dalla UI al DB |
| [Transazioni](docs/transazioni.md) | Unit of Work con isolamento e retry |
| [Controlli](docs/controlli.md) | regole e momenti in cui scattano |
| [Configurazione](docs/configurazione.md) | `kybes.config.json` e opzioni dell'installer |
| [Roadmap](docs/roadmap.md) | fasi completate e in arrivo |
| [Sviluppo del kit](docs/sviluppo.md) | test e come estendere kybes |

## Stato

Sono disponibili:
- il generatore del modello, con query dichiarate, indici automatici, DDL, paginazione a cursore e Unit of Work;
- i controlli;
- l'installer.

La [roadmap](docs/roadmap.md) indica le fasi in arrivo:
- test ISO 26262-6;
- multi-tenant;
- archivio hot/cold con job;
- MongoDB.
