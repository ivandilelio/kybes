---
name: kybes-architecture
description: Regole architetturali vincolanti per progettare, pianificare e generare codice di gestionali cloud (ERP, BPM, backoffice) - API Gateway, Lambda vs Kubernetes, Job KEDA, librerie DB-Models e Utils, validazione, errori, CDN, SSO. Usala prima di ogni piano o modifica di codice in un progetto gestionale.
---

# Architettura di riferimento per gestionali cloud

Queste regole sono vincolanti per ogni piano e ogni riga di codice. Se una richiesta le viola, segnalalo e proponi l'alternativa conforme prima di scrivere codice.

La configurazione del progetto (cartelle, linguaggi, comandi di controllo) è in `.claude/kybes.config.json`. Leggila all'inizio del lavoro: i percorsi indicati lì prevalgono su quelli di esempio qui sotto.

Cloud predefinito: AWS (API Gateway, Lambda, EKS, SQS/EventBridge, S3+CloudFront). Su altri cloud usa gli equivalenti (Azure: APIM, Functions, AKS, Service Bus, Storage+Front Door).

## 1. Separazione delle responsabilità (MVC distribuito)

- **View**: SPA statica servita da CDN (sez. 8).
- **Controller**: handler dietro API Gateway, come function o microservizi (sez. 2).
- **Model**: libreria DB-Models condivisa (sez. 4).

Nessun controller contiene SQL, query ORM o driver DB: tutto passa da DB-Models. Un hook lo verifica e blocca la scrittura.

## 2. Esposizione e runtime delle API

- Ogni API passa da **API Gateway** (autenticazione, throttling, routing, versioning `/v1`).
- Albero decisionale del runtime, da applicare e motivare per ogni endpoint:
  1. Innescata da schedule, coda o evento, oppure batch → **Job** (sez. 3).
  2. Sincrona, stateless (legge/scrive DB, Redis o pubblica un evento), termina entro **10 s** → **Function** (Lambda), pay-per-use.
  3. Oltre 10 s, asincrona di lunga durata, WebSocket/streaming o connessioni persistenti → **Microservizio su Kubernetes**, esposto all'API Gateway tramite VPC link / ingress.
- Nota: API Gateway REST ha comunque un timeout di integrazione di circa 29 s.
- Ogni function o microservizio espone **un solo bounded context**, mai l'accesso generico al DB. Niente endpoint "CRUD universale".
- Le function accedono al DB relazionale tramite connection pooler (RDS Proxy / PgBouncer).
- Le scritture sono **idempotenti** (`Idempotency-Key` o chiave naturale).

## 3. Kubernetes e Job

- Node group dimensionati per profilo di carico, autoscaling dei nodi (Cluster Autoscaler o Karpenter), HPA sui deployment.
- Job agganciati a eventi/code con **KEDA** (scaler SQS, Kafka, cron...), scale-to-zero a coda vuota.
- Job a calendario: `ScaledJob` KEDA con trigger cron o `CronJob` nativo.
- Ogni Job: idempotente, retry limitati, timeout esplicito, dead-letter queue oltre i tentativi.
- Resource requests/limits obbligatori su ogni container.

## 4. Libreria DB-Models

- Unica sede di entità ORM, repository/DAO, migrazioni, schemi di validazione del modello, manipolazione dati legata alla persistenza.
- Pubblicata su registry privato con **semver e tag**, importata a build time con versione pinnata.
- Un'implementazione per ogni linguaggio usato (C#, Python, TypeScript, Java), tutte **generate dallo stesso schema** (sez. 4b): la coerenza non dipende dalla disciplina ma dal generatore, e `gen --check` in CI fallisce se un file generato non è allineato.
- Release coordinate: stessa versione per tutte le implementazioni.
- Le migrazioni girano solo dalla pipeline, mai all'avvio dell'applicazione.

## 4b. Modello dati: schema → generatore → un file per tabella

Questa è la regola che rende ogni progetto navigabile allo stesso modo. Il CRUD non si scrive mai a mano.

**Sorgente di verità.** Ogni tabella ha un file `schemas/db/<Tabella>.yaml` con colonne, chiave, vincoli, relazioni e indici. Il nome della tabella è PascalCase e coincide con il nome del file.

```yaml
table: Ordini
description: Testata degli ordini
columns:
  - { name: Id, type: uuid, primary_key: true }          # chiave generata dal sistema
  - { name: Numero, type: string, length: 20, required: true, unique: true }
  - { name: ClienteId, type: uuid, required: true }
  - { name: Totale, type: decimal, precision: 14, scale: 2, required: true, default: 0 }
  - { name: CreatoIl, type: datetime, generated: on_create }
relations:
  - { name: Cliente, kind: many_to_one, target: Clienti, foreign_key: ClienteId, on_delete: restrict }
  - { name: Righe, kind: one_to_many, target: RigheOrdine, foreign_key: OrdineId }
indexes:
  - { columns: [Numero, ClienteId] }
```

- **Tipi:** `uuid`, `string` (con `length`), `text`, `int`, `bigint`, `decimal` (`precision`, `scale`), `bool`, `date`, `datetime`, `json`.
- **Opzioni di colonna:** `primary_key` (una sola, `auto` true di default su uuid/int/bigint), `required`, `unique`, `default`, `generated: on_create|on_update` (solo datetime), `db_name`, `description`.
- **Relazioni:** `many_to_one` dichiara la FK nella tabella; `one_to_many` è l'inverso e richiede la `many_to_one` corrispondente nella tabella target. `on_delete`: `restrict` (default), `cascade`, `set_null`.
- Il nome della tabella DB è lo snake_case del nome (`RigheOrdine` → `righe_ordine`), salvo `db_name`.

**Generatore.** Salvando uno schema con Write/Edit il generatore riparte da solo (hook). Da terminale: `python3 tools/kybes/plugins/kybes/scripts/gen/gen.py .`; con `--check` verifica senza scrivere. Produce, per ogni linguaggio configurato in `.claude/kybes.config.json`:

| Linguaggio | Punto d'ingresso (custom, tuo) | Generato (non si modifica) | ORM |
|---|---|---|---|
| C# | `model/<Tabella>.cs` (partial class `<Tabella>Repository`) | `model/generated/<Tabella>.cs`, `AppDbContext.cs` | EF Core 8 |
| Python | `model/<Tabella>.py` (`<Tabella>Repository` estende la base) | `model/generated/<Tabella>.py` | SQLAlchemy 2 |
| TypeScript | `model/<Tabella>.ts` (`<Tabella>Repository` estende la base) | `model/generated/<Tabella>.ts`, `index.ts` (`ENTITIES`) | TypeORM |
| Java | `model/<Tabella>Repository.java` (estende la base) | `model/generated/<Tabella>.java`, `<Tabella>RepositoryBase.java` | JPA 3.1 / Hibernate 6 |

Inoltre `schemas/generated/json/<Tabella>.schema.json` (validazione di API Gateway e middleware) e `MODEL_INDEX.md` (indice di tabelle, file, metodi generati e custom).

**Metodi generati, sempre gli stessi per ogni tabella** (nomi nell'idioma del linguaggio):

| Neutro | C# | Python | TypeScript / Java |
|---|---|---|---|
| leggi per chiave | `GetByIdAsync` | `get_by_id` | `getById` |
| pagina a cursore | `ListPageAsync(PageRequest)` | `list_page(PageRequest)` | `listPage` |
| conteggio / esistenza | `CountAsync`, `ExistsAsync` | `count`, `exists` | `count`, `exists` |
| inserisci / aggiorna / elimina (con validazione) | `CreateAsync`, `UpdateAsync`, `DeleteAsync` | `create`, `update`, `delete` | `create`, `update`, `delete` |
| per colonna univoca | `FindBy<Col>Async` | `find_by_<col>` | `findBy<Col>` |
| per chiave esterna (pagina) | `ListBy<Fk>Async` | `list_by_<fk>` | `listBy<Fk>` |
| padre (many_to_one) | `Get<Relazione>Async` | `get_<relazione>` | `get<Relazione>` |
| figli (one_to_many, pagina) | `List<Relazione>Async` | `list_<relazione>` | `list<Relazione>` |
| query dichiarata `page`/`list` | `List<Query>Async` | `list_<query>` | `list<Query>` |
| query dichiarata `one` | `Find<Query>Async` | `find_<query>` | `find<Query>` |

**Regole operative (verificate dagli hook):**
1. Prima di cercare nel codice, leggi `MODEL_INDEX.md`: dice in quale file sta ogni metodo di ogni tabella.
2. Tabella nuova o colonna nuova → modifica solo `schemas/db/<Tabella>.yaml`. Non creare a mano file in `model/` per tabelle senza schema.
3. I file in `generated/`, `schemas/generated/json/` e `MODEL_INDEX.md` non si modificano mai (scrittura rifiutata).
4. I metodi custom di una tabella vanno solo nel suo file `model/<Tabella>` e non possono avere il nome di un metodo generato. Prima di scriverne uno, controlla che non esista già tra i generati.
5. Nella cartella `model` non si creano altri file né sottocartelle. La logica di business sta nei service, le trasformazioni pure in `libs/utils`.
6. Fuori dalla cartella model nessun import di ORM o driver DB, in nessun linguaggio.
7. **Query:** l'accesso abituale (filtri in AND sulla tabella, ordinamento, una o più righe) si dichiara in `queries` nello schema, non si scrive a mano. Il generatore crea il metodo e l'indice che lo copre (`db/generated/indexes.md`). I metodi custom servono solo per join, aggregazioni e logiche non esprimibili come query dichiarata; per loro l'indice va dichiarato in `indexes`.
8. **Paginazione:** tutte le liste usano il cursore (`PageRequest` → `Page` con `items`, `nextCursor`, `limit`), mai `OFFSET`. Le colonne ordinabili dalla UI sono solo quelle in `pagination.sortable`, e devono essere `required`. L'API espone `limit`, `cursor` e `sort` secondo `schemas/generated/json/_page.schema.json`; un errore su questi campi è un 400.
9. **Transazioni:** i metodi del model non fanno commit. Il service apre la Unit of Work generata (`run_in_transaction`, `runInTransaction`, `UnitOfWork.RunAsync`, `UnitOfWork.run`) indicando le tabelle scritte: il livello di isolamento è il più severo tra quelli dichiarati in `transactions.isolation`, e sui conflitti (40001, 40P01) il blocco viene ripetuto. Dentro la transazione niente effetti esterni (email, chiamate HTTP): vanno dopo il commit o in outbox.
10. Il DDL di riferimento è `db/generated/ddl/postgres/_all.sql`: le migrazioni si confrontano con questo, non con la sincronizzazione automatica degli ORM.

**Niente codice duplicato.** Un blocco di 8 o più righe significative uguale in due punti blocca la chiusura del lavoro. La correzione è sempre estrarre: accesso ai dati → metodo custom nel model della tabella; trasformazione pura → `libs/utils`; regola di business → service.

## 4b-bis. Multi-tenant

- Ogni tabella dichiara `tenancy`: `none` per i dati condivisi (cataloghi, tipologie), `column` per i dati di una Organization nella stessa tabella (il caso normale), `schema` o `database` solo se il cliente chiede separazione fisica. Il default è `model.tenancy.default`.
- Con `column` non si dichiara `TenantId`: la aggiunge il generatore; univocità e indici diventano per tenant.
- Il tenant si lega alla sessione nel middleware, dal token SSO, prima di creare i repository: Python `bind_tenant(session, t)`, TypeScript `bindTenant(em, t)`, Java `Tenancy.bind(em, t)`, C# `db.BindTenant(t)`; nelle transazioni si passa alla Unit of Work (`tenant=`). Mai filtrare a mano per tenant nei service e mai prendere il tenant dal payload della richiesta.
- Relazioni ammesse: una tabella condivisa non punta a tabelle di un tenant; `column` → `none`/`column`; `schema` → `none`/`schema`; `database` → solo `database`.
- `db/generated/tenancy/_rls.sql` (row-level security) va applicato in produzione: il ruolo dell'applicazione non ha `BYPASSRLS`.
- Dettagli: docs/multi-tenant.md del kit.

## 4b-ter. Archivio e conservazione

- I dati vecchi non si spostano né si cancellano con job scritti a mano: si dichiarano `archive` e `retention` nello schema della tabella. Il generatore produce configurazione e manifest del job (`jobs/generated/<t>-archive/`), il motore comune (`jobs/generated/_engine/`), il DDL Athena o Synapse e i test.
- `archive` quando il dato serve ancora (audit, consultazione): Parquet su S3 o Blob, partizionato per tenant e data. `retention` da sola quando il dato non ha valore dopo il TTL. Entrambe per una conservazione con scadenza (es. 10 anni).
- `job.mode`: `cron` di default; `keda` per tabelle con molto flusso (il job parte quando ci sono righe da elaborare; solo `tenancy` `none` o `column`); `engine` solo se serve un passaggio continuo.
- `read_through: true` solo se API o UI devono aprire per chiave un record archiviato. Elenchi, ricerche e report sui dati archiviati si fanno con Athena o Synapse, non dal model.
- Un record con figli nella tabella hot non viene archiviato: per testata e righe, dai alle righe la stessa colonna di data e lo stesso `after`.
- Il lettore dell'archivio si lega alla sessione come il tenant (`bind_archive`, `bindArchive`, `Archive.bind`, `db.BindArchive`). Il job gira con un ruolo dedicato: `BYPASSRLS`, oppure i tenant in `KYBES_TENANTS`.
- Dettagli: docs/archivio.md del kit.

## 4c. Verifica di unità (ISO 26262-6)

- Il generatore scrive i test di unità del modello in `libs/db-models/<lang>/tests/generated/` e le evidenze in `docs/generated/verification/` (requisiti `REQ-*`, specifiche dei casi `TC-*`, tracciabilità, soglie). Non si modificano: cambia lo schema.
- L'ASIL di una tabella è `verification.asil` nello schema (default in configurazione, B). Decide le soglie di copertura; da ASIL C il generatore aggiunge un caso MC/DC per ogni condizione di ogni query.
- **Ogni metodo custom ha un test custom** in `libs/db-models/<lang>/tests/custom/`, scritto insieme al metodo:
  - l'identificativo del caso `TC-<Tabella>-<CASO>` e il requisito `REQ-<Tabella>-<CHIAVE>` nel nome o nel docstring/titolo del test, il requisito anche nel commento del metodo;
  - casi derivati con i metodi della norma: analisi dei requisiti (il caso nominale), classi di equivalenza (un record dentro e uno fuori dal filtro), valori limite (vuoto, uno, massimo), stima degli errori (record inesistente, input non valido);
  - le fixture e i builder dei test generati: in Python `session`/`session_factory` e `kybes_builders.build_<tabella>`; in TypeScript `withDb` da `../generated/_db` e `build<Tabella>` da `../generated/kybes_builders`; in Java `KybesDb.open()`/`KybesDb.close(em)` e `KybesBuilders.build<Tabella>(em, x -> ...)` (test in `src/test/java/<package>/custom/`); in C# `KybesDb.Open()` e `KybesBuilders.Build<Tabella>(db, x => ...)`.
  - Java e C# girano su PostgreSQL (`KYBES_TEST_DATABASE_URL=postgresql://utente:password@host:5432/db`); Python e TypeScript usano lo stesso URL se impostato, altrimenti SQLite in memoria.
  La regola `custom_tests` blocca la chiusura se un metodo custom non compare in un test con un id `TC-<Tabella>-`.
- `verify.py` (in `stop_gate.commands` e in CI) esegue test generati e custom e confronta la copertura di ogni file del modello con la soglia della sua tabella. Una soglia mancata si risolve con un test, mai abbassando la soglia o escludendo file.

## 5. Libreria Utils

- Solo trasformazioni dati riusate in **almeno due** punti.
- Funzioni pure: niente DB, rete o configurazione; nessuna dipendenza da DB-Models.
- Se una funzione serve in un solo posto, resta lì.

## 6. Validazione degli input (tre livelli)

1. **API Gateway**: validazione strutturale contro lo schema OpenAPI.
2. **Middleware** comune in ogni function e microservizio: validazione semantica e autorizzazione (ruolo, tenant, ownership).
3. **Model**: validazione dello schema prima della persistenza.

Gli schemi vengono tutti da `schemas/`.

## 7. Gestione degli errori

Modulo errori condiviso (`libs/errors`) che garantisce:
- **Rollback**: transazioni per operazioni multi-step; saga con compensazioni per operazioni distribuite.
- **Accodamento**: errori transitori → coda di riprocessamento; eventi con pattern **outbox** e dead-letter queue.
- **Comunicazione controllata**: la risposta contiene solo codice applicativo, messaggio generico e `correlationId`. Mai stack trace, query, nomi di tabelle, hostname, segreti o `str(exception)`. Il dettaglio va nei log con lo stesso `correlationId`.
- Classi minime: `VALIDATION` (4xx), `AUTH` (401/403), `NOT_FOUND` (404), `CONFLICT` (409), `TRANSIENT` (503 + retry), `INTERNAL` (500).

## 8. Interfaccia grafica

- SPA in file statici su CDN (S3 + CloudFront) con origin privato.
- Asset con hash e cache lunga; `index.html` senza cache.

## 9. Autenticazione

- **SSO con account aziendale** via OIDC/SAML (es. Microsoft Entra ID).
- Authorization Code + PKCE nella SPA; JWT validati da un authorizer su API Gateway.
- Ruoli dai gruppi/claim dell'IdP, verificati di nuovo nel middleware.

## 10. Requisiti trasversali

- **IaC** (Terraform o CDK) per ogni risorsa.
- **Segreti** in Secrets Manager / Parameter Store, mai nel codice (un hook blocca i segreti in chiaro).
- **Osservabilità**: log JSON con `correlationId` propagato ovunque; metriche e tracing OpenTelemetry.
- **Ambienti** dev/staging/prod e pipeline CI: lint, test, contract test DB-Models, `arch_check`, scansione dipendenze.

## Struttura di repository

```
/infra                      IaC
/libs/db-models/<lang>/.../model            un file per tabella (custom) + generated/
/libs/db-models/<lang>/tests       generated/ (test ISO 26262-6 generati) + custom/ (test dei metodi custom)
/docs/generated/verification      requisiti, specifiche dei test, tracciabilità
/schemas/db                 <Tabella>.yaml: sorgente di verità del modello
/schemas/generated/json               JSON Schema generati
/MODEL_INDEX.md             indice generato di tabelle, file e metodi
/libs/utils
/libs/errors                modulo errori + middleware di validazione
/services/<contesto>/functions
/services/<contesto>/ms
/jobs/<nome>
/frontend
/schemas/openapi.yaml       contratto delle API
```

## Formato obbligatorio del piano

Ogni piano deve contenere una tabella per endpoint/Job:

| Endpoint o Job | Bounded context | Runtime (Lambda/K8s/Job) | Motivo (regola sez. 2) | Tabelle via DB-Models | Idempotenza |
|---|---|---|---|---|---|

seguita da: modifiche agli schemi `schemas/db/<Tabella>.yaml` (colonne, relazioni, indici, `tenancy` di ogni tabella nuova), metodi custom da aggiungere con il file di destinazione (`model/<Tabella>`), metodi generati che verranno riusati, test da scrivere (per ogni metodo custom: id `TC-<Tabella>-<CASO>`, requisito `REQ-<Tabella>-<CHIAVE>`, metodo di derivazione), ASIL delle tabelle toccate, impatti su IaC.

## Checklist prima di consegnare

- [ ] Runtime scelto con l'albero della sez. 2 e motivato
- [ ] Tabelle e colonne cambiate solo in `schemas/db`, generatore eseguito (`gen --check` verde)
- [ ] Metodi custom solo in `model/<Tabella>`, nessun duplicato di metodi generati, nessun blocco di codice duplicato
- [ ] Ogni metodo custom ha un test in `tests/custom/` con id `TC-` e requisito `REQ-`; `verify.py` verde (test e soglie ASIL)
- [ ] Ogni tabella nuova ha `tenancy`; il tenant è legato alla sessione dal middleware (mai dal payload), le transazioni lo passano alla Unit of Work
- [ ] Età e TTL dei dati dichiarati con `archive`/`retention` nello schema, nessun job di pulizia scritto a mano
- [ ] Nessun accesso al DB fuori da DB-Models
- [ ] Endpoint limitati al proprio bounded context
- [ ] Validazione ai tre livelli
- [ ] Errori dal modulo comune, nessun dettaglio interno in risposta
- [ ] Scritture idempotenti, transazioni/compensazioni definite
- [ ] SSO e autorizzazione verificati
- [ ] IaC, segreti, log con correlationId inclusi
