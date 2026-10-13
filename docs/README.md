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
| [Verifica di unità](verifica.md) | sviluppatori, qualità | test generati ISO 26262-6, metodi custom, soglie per ASIL, `verify.py` |
| [Roadmap](roadmap.md) | tutti | fasi completate e pianificate, nota su ISO 26262 |
| [Sviluppo del kit](sviluppo.md) | chi mantiene kybes | struttura del repository, test, come estenderlo |
