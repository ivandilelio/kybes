<!-- kybes:start (blocco gestito dall'installer: modifiche qui vengono sovrascritte) -->
## Regole architetturali (kybes)

Questo progetto segue l'architettura della skill `kybes-architecture`. In sintesi:

- Ogni API dietro API Gateway. Sincrona, stateless ed entro 10 s → Lambda. Oltre 10 s, WebSocket o long-running → microservizio Kubernetes. Schedule/eventi/batch → Job KEDA.
- Ogni function o microservizio espone un solo bounded context. Accesso ai dati SOLO tramite `libs/db-models`.
- Modello dati: `schemas/db/<Tabella>.yaml` è la sorgente di verità. Il generatore produce entità, CRUD e relazioni in `model/generated/` (mai a mano). I metodi custom di una tabella stanno solo in `model/<Tabella>` (Java: `model/<Tabella>Repository.java`).
- **Prima di cercare nel codice leggi `MODEL_INDEX.md`**: dice in che file sta ogni metodo di ogni tabella.
- Niente codice duplicato: si estrae nel model (dati), in `libs/utils` (trasformazioni) o nel service (regole).
- `libs/utils` solo funzioni pure riusate in almeno due punti.
- Validazione su tre livelli (API Gateway, middleware, model) con schemi da `schemas/`.
- Errori solo tramite `libs/errors`: mai stack trace o messaggi di eccezione al client, sempre `correlationId`.
- Frontend statico su CDN, accesso SSO aziendale (OIDC).

Modo di lavorare:
- Per pianificare usa l'agente **kybes:architect**, non il subagent Plan integrato (che non legge questo file).
- Per scrivere codice delega i task all'agente **kybes:implementer**, uno per task.
- A fine lavoro fai verificare le modifiche all'agente **kybes:reviewer**.
- Se un hook rifiuta una scrittura o blocca la chiusura, correggi la causa: non aggirarlo.
- Cartelle, linguaggi e comandi di controllo: `.claude/kybes.config.json` (lo modifica solo l'utente).
<!-- kybes:end -->
