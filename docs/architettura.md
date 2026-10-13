# Architettura

kybes fa in modo che un'AI generi backend sempre con la stessa struttura. Ci arriva con tre leve:

1. **Il codice ripetitivo non lo scrive l'AI.** Un generatore deterministico produce entità, CRUD, relazioni, validazione, JSON Schema e indice a partire dagli schemi YAML. A parità di schema, due progetti hanno file identici.
2. **Le regole stanno nel contesto giusto.** La skill, le regole per cartella e gli agenti dicono all'AI dove va ogni cosa e come si lavora.
3. **Le regole verificabili sono controlli, non istruzioni.** Hook di Claude Code e CI rifiutano le scritture fuori regola e impediscono di chiudere il lavoro finché i controlli non passano.

## Livelli dell'applicazione

| Livello | Dove | Responsabilità |
|---|---|---|
| View | `frontend/` | SPA statica servita da CDN, login SSO aziendale (OIDC) |
| API | API Gateway | autenticazione, throttling, validazione strutturale con i JSON Schema generati |
| Controller | `services/<contesto>/functions` o `ms` | handler sottile: middleware di validazione, chiamata al service, risposta |
| Service | `services/<contesto>/...` | regole di business, apertura delle transazioni (Unit of Work) |
| Model | `libs/db-models/<linguaggio>` | accesso ai dati: un file per tabella, generato più metodi custom |
| Dati | database SQL o MongoDB, archivio su S3/Blob | |

Solo il model accede ai dati. Un hook blocca import di ORM e driver di database in qualsiasi altro punto, in tutti e quattro i linguaggi.

## Runtime

| Caso | Runtime |
|---|---|
| Sincrono, stateless, entro 10 secondi | Function (Lambda), a consumo |
| Oltre 10 secondi, WebSocket, connessioni persistenti | Microservizio su Kubernetes dietro API Gateway |
| Schedule, coda, evento, batch | Job: CronJob, Job con KEDA, o engine sempre attivo |

Ogni function o microservizio espone un solo bounded context.

## Flusso di lavoro con Claude Code

```
richiesta
  → kybes:architect     piano: runtime per endpoint, modifiche agli schemi, metodi riusati e nuovi
  → kybes:implementer   un task alla volta
       Write/Edit ──► hook pre_write   rifiuta ciò che viola le regole
                 ──► hook post_edit   rigenera il model se cambia uno schema, linter, avvisi
  → kybes:reviewer      verifica indipendente contro la checklist
  → hook stop_gate      arch_check + gen --check + test: senza esito positivo il lavoro non si chiude
```

Il subagent Plan integrato in Claude Code non legge `CLAUDE.md`. Per questo il piano lo produce `kybes:architect`, che ha la skill precaricata.

## Componenti del kit

| Componente | Percorso nel kit | Ruolo |
|---|---|---|
| Skill `kybes-architecture` | `marketplace/plugins/kybes/skills/` | regole architetturali complete |
| Agenti | `marketplace/plugins/kybes/agents/` | architect, implementer, reviewer |
| Hook | `marketplace/plugins/kybes/hooks/hooks.json` | pre_write, post_edit, stop_gate |
| Regole | `marketplace/plugins/kybes/scripts/rules.py`, `model_guard.py` | logica dei controlli, condivisa da hook e CI |
| Generatore | `marketplace/plugins/kybes/scripts/gen/` | schema YAML → model nei quattro linguaggi |
| Template | `marketplace/plugins/kybes/templates/` | blocco CLAUDE.md, regole per cartella, scaffold, CI, schemi di esempio |
| Installer | `marketplace/plugins/kybes/install.sh` (con `install.sh` in radice come scorciatoia) e skill `kybes-init` | installa il kit in un progetto, idempotente |

Approfondimenti:
- [generatore](generatore.md)
- [controlli](controlli.md)
- [configurazione](configurazione.md)
- [struttura delle cartelle](struttura-cartelle.md)
