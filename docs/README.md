# Documentazione di kybes

| Documento | Per chi | Contenuto |
|---|---|---|
| [Architettura](architettura.md) | tutti | come kybes vincola la generazione: livelli, runtime, flusso con Claude Code |
| [Struttura delle cartelle](struttura-cartelle.md) | tutti | dove finisce ogni file, generato o tuo, in ogni progetto |
| [Schema delle tabelle](schema-yaml.md) | chi definisce il modello dati | specifica completa di `schemas/db/<Tabella>.yaml` |
| [Generatore](generatore.md) | sviluppatori | cosa produce, metodi per linguaggio, nomi di vincoli e indici, requisiti |
| [Query e indici](query-e-indici.md) | chi definisce il modello dati | query dichiarate, scelta automatica degli indici, DDL |
| [Paginazione](paginazione.md) | backend e frontend | contratto a cursore UI/API/DB-Model |
| [Transazioni](transazioni.md) | backend | Unit of Work, isolamento, retry |
| [Controlli](controlli.md) | sviluppatori, revisori | regole, momenti in cui scattano, livelli |
| [Configurazione](configurazione.md) | chi installa | `kybes.config.json` e opzioni dell'installer |
| [Multi-tenant](multi-tenant.md) | sviluppatori, architetti | isolamento per tabella (column, schema, database), contesto del tenant, row-level security, test di isolamento |
| [Archivio e conservazione](archivio.md) | sviluppatori, architetti, operations | spostamento sicuro su S3/Blob in Parquet, read-through, TTL, job Kubernetes, Athena e Synapse |
| [API REST](api.md) | backend, architetti | blocco `api` dello schema, endpoint custom in OpenAPI, validazione, routing e middleware, identità dal gateway, adattatori Lambda/server/framework, test |
| [MongoDB](mongodb.md) | sviluppatori, architetti | collection con `storage: mongo`: formato dei documenti, sessione e transazioni, indici e TTL, integrità referenziale, limiti, test |
| [Verifica di unità](verifica.md) | sviluppatori, qualità | test generati ISO 26262-6, metodi custom, soglie per ASIL, `verify.py` |
| [Roadmap](roadmap.md) | tutti | fasi completate e pianificate, nota su ISO 26262 |
| [Sviluppo del kit](sviluppo.md) | chi mantiene kybes | struttura del repository, test, come estenderlo |
