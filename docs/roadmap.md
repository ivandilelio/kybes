# Roadmap

Ogni fase viene verificata con la suite del kit (`tests/run.sh`) prima di essere pubblicata.

| Fase | Contenuto | Stato |
|---|---|---|
| 0 | Plugin, agenti, hook, generatore del modello in C#, Python, TypeScript, Java, controllo duplicati, installer | completata |
| 1 | Rinomina in kybes, documentazione, mappa prevedibile delle cartelle, suite di test del kit | completata |
| 2 | Query dichiarate nello schema, analisi e generazione degli indici, DDL PostgreSQL, paginazione a cursore UI/API/DB-Model, Unit of Work con isolamento e retry | completata |
| 3 | Test unitari generati secondo ISO 26262-6 (classi di equivalenza, valori limite, ID di requisito), soglie di copertura per ASIL, matrice di tracciabilità, test dei metodi custom obbligatori, `verify.py` (Python e TypeScript) | completata |
| 3b | Test generati JUnit 5 (Java, Hibernate) e xUnit (C#, EF Core) dallo stesso catalogo, eseguiti su PostgreSQL; nuovi requisiti emersi dalla copertura reale (colonne facoltative, oggetto collegato, pagina predefinita, date generate, nullo esplicito su colonne con default) | completata |
| 4 | Multi-tenant scelto per tabella: colonna tenant con filtro in ogni metodo e row-level security, schema per tenant, database per tenant; contesto del tenant nella sessione nei quattro linguaggi; test generati di isolamento | completata |
| 5 | Archivio hot/cold: Parquet su S3/Blob partizionato per tenant e data con spostamento verificato e recupero, read-through per chiave nei quattro linguaggi, conservazione (TTL) dell'archivio o della tabella hot, motore dei job con CronJob, ScaledJob KEDA o Deployment 24/7, tabelle esterne Athena e viste Synapse, test generati del motore e dei job | completata |
| 6 | MongoDB nei quattro linguaggi con la stessa interfaccia dei repository SQL: `storage: mongo` per tabella, documenti con formato comune, stessi metodi, query, paginazione a cursore e tenant, integrità referenziale nel repository, transazioni MongoDB, stessi indici più indici parziali e TTL per la conservazione, test generati eseguiti su MongoDB con replica set | completata |
| 7 | API REST nei quattro linguaggi: CRUD, query e relazioni dal blocco `api` dello schema, endpoint custom da `schemas/openapi.yaml`, contratto OpenAPI 3.0.3 generato, validazione dell'input, routing e middleware uguali in ogni linguaggio, identità dai claim del gateway, adattatori per AWS Lambda, server HTTP senza framework e framework (FastAPI, Fastify, Spring Boot, ASP.NET Core), test generati ISO 26262-6 per operazioni e nucleo | completata |
| 8 | Robustezza del gate e profili piattaforma: regex ORM estese (Spring Data MongoDB, AWS SDK DynamoDB), pattern error-leak Java e C#, `paths.generated_ignore` per codice di terzi, test esclusi da `orm_outside_db_models`, profilo piattaforma (`platform.downgrade`), checklist estesa (paginazione multi-sorgente, header propagation, scaffold detection, HPA, config), avviso config mancante in `arch_check --strict` | completata |

## Nota su ISO 26262

La conformità a ISO 26262 riguarda l'intero processo di sviluppo: safety plan, analisi dei rischi, qualifica degli strumenti, revisioni indipendenti. Non è una proprietà del solo codice.

kybes copre la parte che si può automatizzare a livello di unità software (ISO 26262-6, verifica di unità):
- test derivati in modo sistematico dai requisiti dello schema;
- criteri di copertura legati all'ASIL;
- tracciabilità bidirezionale tra requisito, codice e test;
- evidenze pronte per l'audit.

La certificazione resta un passo del processo dell'organizzazione.
