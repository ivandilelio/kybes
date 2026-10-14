# Specifica dello schema di tabella

Ogni tabella è descritta da un file `schemas/db/<Tabella>.yaml`. È l'unica sorgente di verità: model, test, DDL, JSON Schema, indice, archivio e job vengono tutti da qui. Chiavi sconosciute o valori non validi fanno fallire la generazione con un messaggio che indica file e campo.

La colonna **Stato** dice se il generatore già usa la chiave o se arriva in una fase della [roadmap](roadmap.md). Le chiavi di una fase futura sono già riservate: il formato non cambierà, e finché la fase non è completata il generatore le rifiuta con un messaggio esplicito.

## Esempio completo

```yaml
table: Ordini                       # PascalCase, uguale al nome del file
description: Testata degli ordini
storage: sql                        # sql | mongo
tenancy: column                     # none | column | schema | database

columns:
  - { name: Id, type: uuid, primary_key: true }
  - { name: Numero, type: string, length: 20, required: true, unique: true }
  - { name: ClienteId, type: uuid, required: true }
  - { name: Stato, type: string, length: 12, required: true, default: aperto }
  - { name: Data, type: date, required: true }
  - { name: Totale, type: decimal, precision: 14, scale: 2, required: true, default: 0 }
  - { name: CreatoIl, type: datetime, generated: on_create }

relations:
  - { name: Cliente, kind: many_to_one, target: Clienti, foreign_key: ClienteId, on_delete: restrict }
  - { name: Righe, kind: one_to_many, target: RigheOrdine, foreign_key: OrdineId }

indexes:
  - { columns: [Numero, ClienteId] }

queries:
  - name: ApertiDelCliente
    where:
      - ClienteId
      - { column: Stato, op: eq, value: aperto }
      - { column: Data, op: gte, param: DaData }
    order_by: [{ column: Data, dir: desc }]
    returns: page

pagination:
  default_order: [{ column: Data, dir: desc }]
  sortable: [Data, Numero, Totale]
  max_limit: 200

transactions:
  isolation: read_committed

verification:
  asil: B

archive:
  after: 5y
  column: Data
  target: s3
  format: parquet
  partition_by: [year, month]
  read_through: true
  job: { mode: cron, schedule: "17 3 * * *" }

retention:
  delete_after: 10y
```

## Chiavi di primo livello

| Chiave | Obbligatoria | Valori | Default | Stato |
|---|---|---|---|---|
| `table` | sì | nome PascalCase uguale al nome del file | — | disponibile |
| `db_name` | no | nome della tabella nel database | snake_case di `table` | disponibile |
| `description` | no | testo libero, finisce in indice, JSON Schema e documentazione | — | disponibile |
| `columns` | sì | lista di colonne | — | disponibile |
| `relations` | no | lista di relazioni | — | disponibile |
| `indexes` | no | lista di indici | — | disponibile |
| `queries` | no | query di accesso dichiarate | — | disponibile |
| `pagination` | no | ordinamenti ammessi e limiti di pagina | ordine per chiave, `max_limit` 100 | disponibile |
| `transactions` | no | livello di isolamento delle scritture | `read_committed` | disponibile |
| `verification` | no | livello ASIL della tabella: decide soglie di copertura e casi MC/DC dei test generati | `asil` della configurazione (B) | disponibile |
| `tenancy` | no | `none`, `column`, `schema`, `database` | `model.tenancy.default` della configurazione (`none`) | disponibile |
| `archive` | no | spostamento dei dati vecchi su S3 o Blob in Parquet | nessun archivio | disponibile |
| `retention` | no | cancellazione definitiva dopo un TTL | nessuna | disponibile |
| `storage` | no | `sql`, `mongo` | `sql` | disponibile |
| `api` | no | `true` o mappa: espone la tabella come API REST | non esposta | disponibile |

## Colonne

| Chiave | Valori | Note |
|---|---|---|
| `name` | PascalCase | diventa `snake_case` in Python e nel DB, `camelCase` in TypeScript e Java, resta PascalCase in C# |
| `type` | `uuid`, `string`, `text`, `int`, `bigint`, `decimal`, `bool`, `date`, `datetime`, `json` | |
| `length` | intero positivo | obbligatorio per `string`; per testi lunghi usa `text` |
| `precision`, `scale` | interi | solo `decimal`, default 18 e 2 |
| `primary_key` | `true` | esattamente una colonna; chiavi composte non supportate |
| `auto` | `true`/`false` | solo sulla chiave: valore generato dal sistema; default `true` per `uuid`, `int`, `bigint` |
| `required` | `true`/`false` | NOT NULL e validazione in tutti i linguaggi |
| `unique` | `true` | vincolo univoco con nome `ux_<tabella>_<colonna>` e metodo `findBy<Colonna>` |
| `default` | valore semplice | non ammesso per `uuid`, `date`, `datetime`, `json`. Su una colonna obbligatoria: se il valore manca vale il default, un nullo esplicito è rifiutato come `obbligatorio` |
| `generated` | `on_create`, `on_update` | solo `datetime`: data di creazione o di ultima modifica, impostata dal model |
| `db_name` | nome colonna nel DB | default snake_case |
| `description` | testo | finisce nel JSON Schema e nella documentazione |

## Relazioni

| Chiave | Valori | Note |
|---|---|---|
| `name` | PascalCase | nome della navigazione (es. `Cliente`, `Righe`) |
| `kind` | `many_to_one`, `one_to_many` | la `one_to_many` richiede la `many_to_one` corrispondente nella tabella target |
| `target` | nome di una tabella | anche la stessa tabella, per le gerarchie |
| `foreign_key` | nome di colonna | per `many_to_one` è una colonna di questa tabella, per `one_to_many` della tabella target; il tipo deve coincidere con la chiave del target |
| `on_delete` | `restrict`, `cascade`, `set_null` | solo su `many_to_one`; default `restrict`; `set_null` richiede la FK non obbligatoria |

Per ogni chiave esterna viene creato un indice `ix_<tabella>_<fk>`, salvo che la colonna sia già la prima di un altro indice.

## Indici

| Chiave | Valori | Note |
|---|---|---|
| `columns` | lista di colonne | l'ordine conta |
| `unique` | `true`/`false` | nome `ux_...` se univoco, `ix_...` altrimenti |

## Query dichiarate

Le query di accesso abituali si dichiarano nello schema e non si scrivono a mano (dettagli in [query e indici](query-e-indici.md)). Il generatore crea il metodo in tutti i linguaggi e verifica che un indice le copra. Se non c'è, lo crea con nome `qx_<tabella>_<query>` e lo riporta in `db/generated/indexes.md`.

| Chiave | Valori | Note |
|---|---|---|
| `name` | PascalCase | metodo `list<Name>` / `find<Name>` (C# `List<Name>Async`, Python `list_<name>`) |
| `where` | lista di condizioni | una colonna da sola significa `op: eq` con parametro omonimo |
| `where[].op` | `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`, `prefix`, `is_null`, `not_null` | `prefix` è un `LIKE 'x%'` che può usare l'indice |
| `where[].param` | nome del parametro | default: nome della colonna |
| `where[].value` | costante | la condizione non diventa un parametro del metodo |
| `order_by` | lista di colonne o `{column, dir}` | `dir`: `asc` (default) o `desc`; la chiave primaria viene aggiunta in coda per un ordine stabile |
| `returns` | `page`, `list`, `one` | `page` usa la paginazione a cursore, `one` restituisce il primo risultato o niente |

## Paginazione

Tutte le liste usano la paginazione a cursore (keyset), non `OFFSET` (dettagli in [paginazione](paginazione.md)). Il costo resta costante anche alla pagina diecimila, e i risultati non saltano né si ripetono se nel frattempo vengono inseriti record.

| Chiave | Valori | Note |
|---|---|---|
| `default_order` | come `order_by` | ordinamento quando la UI non ne chiede uno |
| `sortable` | colonne | le sole colonne ordinabili dalla UI; per ognuna serve un indice (creato se manca) |
| `max_limit` | intero | limite massimo di righe per pagina accettato dall'API (default 100) |
| `default_limit` | intero | righe per pagina quando la richiesta non indica `limit` (default 50) |

Le colonne in `default_order` e `sortable` devono essere obbligatorie e di tipo `uuid`, `string`, `int`, `bigint`, `decimal`, `date` o `datetime`.

Il contratto è lo stesso dalla UI al database. La UI invia `limit`, `cursor` e `sort` e riceve `items` e `next_cursor`. Il cursore è opaco: codifica i valori dell'ultima riga. Lo stesso contratto vale per API e DB-Model, ed è descritto in `schemas/generated/json/_page.schema.json`.

## Transazioni

| Chiave | Valori | Note |
|---|---|---|
| `isolation` | `read_committed`, `repeatable_read`, `serializable` | livello predefinito quando il service apre una Unit of Work che scrive su questa tabella |

Le transazioni si aprono nel service con la Unit of Work generata, mai dentro i metodi del model (dettagli in [transazioni](transazioni.md)). Con `serializable`, la Unit of Work ritenta in automatico in caso di conflitto di serializzazione.

## Verifica

| Chiave | Valori | Note |
|---|---|---|
| `asil` | `QM`, `A`, `B`, `C`, `D` | alza o abbassa per questa tabella il livello predefinito; decide il criterio di copertura richiesto ai test e, da C, i casi MC/DC delle query (dettagli in [verifica](verifica.md)) |

## Multi-tenant

| Valore di `tenancy` | Isolamento | Cosa genera |
|---|---|---|
| `none` | tabella condivisa da tutte le Organization | niente |
| `column` | colonna `TenantId` aggiunta dal generatore (nome riservato), filtro in ogni metodo, univocità e indici per tenant | policy row-level security in `db/generated/tenancy/` |
| `schema` | la tabella vive in uno schema PostgreSQL per Organization | funzione `kybes_create_tenant_schema` in `db/generated/tenancy/_schema_per_tenant.sql` |
| `database` | un database per Organization | DDL del database del tenant in `db/generated/tenancy/_database_per_tenant.sql` |

In tutti i casi il repository lavora solo con un tenant legato alla sessione e non legge né modifica dati di un'altra Organization. Le relazioni ammesse tra tabelle con modalità diverse, il contesto del tenant nei quattro linguaggi e i test generati sono in [multi-tenant](multi-tenant.md). Anche l'archivio è separato per tenant (sotto).

## Archivio

| Chiave | Obbligatoria | Valori | Default |
|---|---|---|---|
| `after` | sì | durata: `90d`, `12m`, `5y` | — |
| `column` | sì | colonna `date` o `datetime`, `required` o `generated: on_create` | — |
| `target` | no | `s3`, `blob` | `s3` |
| `format` | no | `parquet` | `parquet` |
| `partition_by` | no | `year`, `month`, `day`, `tenant` (le date sono gerarchiche) | `[year, month]`; `tenant` in testa, implicita quando `tenancy` non è `none` |
| `read_through` | no | `true`/`false` | `false` |
| `job` | no | come e quando gira il job (sotto) | `mode: cron`, ogni notte |

I record con `column` più vecchia di `after` passano dalla tabella hot all'archivio. Un record con figli nella tabella hot (una relazione `many_to_one` di un'altra tabella che punta a lui) resta finché ha figli: archivia prima i figli, con la loro colonna di data.

Con `read_through: true` la lettura per chiave (`getById` e corrispondenti) cerca nell'archivio un record che non è più nella tabella hot. Gli altri metodi leggono solo la tabella hot.

Lo spostamento è sicuro in ogni passo:
1. scrive i file Parquet in un'area di staging e li rilegge (righe, chiavi, SHA-256);
2. cancella le righe dalla tabella hot e registra il passaggio in `kybes_archive_runs`, nella stessa transazione;
3. dopo il commit sposta i file nella posizione definitiva.

Se un passo fallisce prima del commit, le righe restano nella tabella hot e lo staging viene scartato; se il processo si interrompe dopo, il job successivo completa lo spostamento. I dettagli sono in [archivio](archivio.md).

Vincoli controllati dal generatore:
- una colonna della tabella non può chiamarsi come una partizione (`tenant`, `year`, `month`, `day`): rinominala con `db_name`;
- una tabella condivisa (`tenancy: none`) non può avere archivio o conservazione se tabelle per schema o per database di tenant si riferiscono a lei;
- `job.mode: keda` vale solo per `tenancy` `none` e `column` (il trigger conta le righe in un solo database).

## Job

| Chiave | Valori | Default | Note |
|---|---|---|---|
| `mode` | `cron`, `keda`, `engine` | `cron` | CronJob Kubernetes, ScaledJob KEDA attivato dalle righe da elaborare, Deployment sempre attivo |
| `schedule` | espressione cron di 5 campi | `17 3 * * *` | `cron`: quando gira; `keda`: passaggio giornaliero di sicurezza |
| `interval` | secondi, da 30 a 86400 | 300 | `keda`: polling del trigger; `engine`: pausa tra due passaggi |
| `batch_size` | righe per transazione, da 1 a 10000 | 1000 | |

`job` sta in `archive`, oppure in `retention` per una tabella senza archivio.

## Conservazione

| Chiave | Obbligatoria | Valori | Note |
|---|---|---|---|
| `delete_after` | sì | durata | con archivio: deve superare `archive.after` |
| `column` | senza archivio | colonna `date` o `datetime` | con archivio l'età è quella di `archive.column` |
| `job` | no | come sopra | solo senza archivio |

Con un archivio, la conservazione cancella le partizioni dell'archivio finite prima di `delete_after` fa, con i loro oggetti per chiave: serve `year` in `partition_by`. Senza archivio cancella dalla tabella hot le righe con `column` più vecchia di `delete_after`; un figlio `restrict` trattiene il record, `cascade` e `set_null` seguono la regola della relazione.

## Storage

Con `storage: mongo` la tabella diventa una collection MongoDB. Nomi di file, classi e metodi restano identici a quelli SQL, quindi il codice che usa il repository non cambia. Dettagli in [MongoDB](mongodb.md).

Il generatore rifiuta:
- relazioni tra una collection e una tabella SQL;
- `on_delete: cascade` verso una collection;
- `tenancy: schema`;
- `archive`, `retention.job` e `transactions`;
- `retention` su una collection a cui altre tabelle si riferiscono.

`retention` diventa un indice TTL. Le transazioni multi-documento richiedono un replica set.

## API

`api` espone la tabella come API REST: CRUD, query dichiarate e relazioni, con validazione, routing, controller e test generati. `api: true` usa i valori predefiniti.

```yaml
api:
  path: ordini                         # predefinito: nome della tabella in kebab-case
  operations: [list, get, create, update, delete]
  queries: [DelClienteDal]             # predefinito: tutte
  relations: [Righe]                   # predefinito: tutte
  scopes: { read: ordini.read, write: [ordini.write] }
  context: vendite                     # predefinito: primo segmento di path
```

| Chiave | Valori | Default |
|---|---|---|
| `path` | segmenti in minuscolo separati da `/`, senza `/` iniziale | kebab-case di `table` |
| `operations` | sottoinsieme di `list`, `get`, `create`, `update`, `delete` | tutte |
| `queries` | nomi di query dichiarate | tutte |
| `relations` | nomi di relazioni | tutte |
| `scopes.read`, `scopes.write` | uno scope o una lista (servono tutti) | nessuno |
| `context` | nome in minuscolo: raggruppa le operazioni per servizio | primo segmento di `path` |

Endpoint, formato JSON, endpoint custom e runtime sono descritti in [API REST](api.md).

