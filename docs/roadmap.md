# Roadmap

Ogni fase viene verificata con la suite del kit (`tests/run.sh`) prima di essere pubblicata.

| Fase | Contenuto | Stato |
|---|---|---|
| 0 | Plugin, agenti, hook, generatore del modello in C#, Python, TypeScript, Java, controllo duplicati, installer | completata |
| 1 | Rinomina in kybes, documentazione, mappa prevedibile delle cartelle, suite di test del kit | completata |
| 2 | Query dichiarate nello schema, analisi e generazione degli indici, DDL PostgreSQL, paginazione a cursore UI/API/DB-Model, Unit of Work con isolamento e retry | completata |
| 3 | Test unitari generati secondo ISO 26262-6 (classi di equivalenza, valori limite, ID di requisito), soglie di copertura per ASIL, matrice di tracciabilità | in corso |
| 4 | Multi-tenant scelto per tabella: colonna tenant con row-level security, schema per tenant, database per tenant | pianificata |
| 5 | Archivio hot/cold: Parquet su S3/Blob partizionato per tenant e data, lettura via Athena, job di spostamento e TTL come CronJob, Job+KEDA o engine 24/7 | pianificata |
| 6 | MongoDB nei quattro linguaggi con la stessa interfaccia dei repository SQL | pianificata |

## Nota su ISO 26262

La conformità a ISO 26262 riguarda l'intero processo di sviluppo: safety plan, analisi dei rischi, qualifica degli strumenti, revisioni indipendenti. Non è una proprietà del solo codice.

kybes copre la parte che si può automatizzare a livello di unità software (ISO 26262-6, verifica di unità):
- test derivati in modo sistematico dai requisiti dello schema;
- criteri di copertura legati all'ASIL;
- tracciabilità bidirezionale tra requisito, codice e test;
- evidenze pronte per l'audit.

La certificazione resta un passo del processo dell'organizzazione.
