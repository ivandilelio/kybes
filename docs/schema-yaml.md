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
  after: 365d
  on: Data
  target: s3
  format: parquet
  partition_by: [year, month]
  read_through: true
  job: { mode: cron, schedule: "0 2 * * *" }

retention:
  delete_after: 3650d
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
| `verification` | no | livello ASIL della tabella (accettato e validato; usato dai test generati della fase 3) | `asil` della configurazione (B) | in corso |
| `tenancy` | no | `none`, `column`, `schema`, `database` | `tenancy` della configurazione (`none`) | fase 4 |
| `archive` | no | spostamento dei dati vecchi su cold storage | nessun archivio | fase 5 |
| `retention` | no | cancellazione definitiva dopo un TTL | nessuna | fase 5 |
| `storage` | no | `sql`, `mongo` | `sql` | fase 6 |

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
| `default` | valore semplice | non ammesso per `uuid`, `date`, `datetime`, `json` |
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

## Verifica (fase 3)

| Chiave | Valori | Note |
|---|---|---|
| `asil` | `QM`, `A`, `B`, `C`, `D` | alza o abbassa per questa tabella il livello predefinito; decide il criterio di copertura richiesto ai test |

## Multi-tenant (fase 4)

| Valore di `tenancy` | Isolamento | Cosa genera |
|---|---|---|
| `none` | tabella condivisa da tutte le Organization | niente |
| `column` | colonna `TenantId` aggiunta, filtro obbligatorio in ogni metodo | policy row-level security in `db/generated/tenancy/` |
| `schema` | la tabella vive in uno schema DB per Organization | risoluzione dello schema dal contesto del tenant |
| `database` | un database per Organization | risoluzione della connessione dal contesto del tenant |

In tutti i casi i metodi del repository ricevono il contesto del tenant e non possono leggere dati di un'altra Organization. Anche l'archivio è separato per tenant.

## Archivio (fase 5)

| Chiave | Valori | Note |
|---|---|---|
| `after` | durata (`90d`, `12m`, `5y`) | età oltre la quale un record lascia la tabella hot |
| `on` | colonna `date` o `datetime` | colonna su cui si misura l'età |
| `target` | `s3`, `blob` | Amazon S3 o Azure Blob Storage |
| `format` | `parquet` | |
| `partition_by` | `year`, `month`, `day`, `tenant` | partizioni del percorso; `tenant` è implicita quando `tenancy` non è `none` |
| `read_through` | `true`/`false` | i metodi di lettura per chiave cercano anche nell'archivio se il record non è più nella tabella hot |
| `job.mode` | `cron`, `keda`, `engine` | CronJob Kubernetes, ScaledJob KEDA o Deployment sempre attivo |
| `job.schedule` | espressione cron | per `cron` |

Lo spostamento è sicuro in ogni passo:
1. scrive il file Parquet;
2. lo verifica (righe e checksum);
3. cancella dalla tabella hot nella stessa finestra di transazione.

Se un passo fallisce, il record resta nella tabella hot.

## Conservazione (fase 5)

| Chiave | Valori | Note |
|---|---|---|
| `delete_after` | durata | cancellazione definitiva dall'archivio dopo il TTL, eseguita dallo stesso job |

## Storage (fase 6)

Con `storage: mongo` la tabella diventa una collection MongoDB. Nomi di file, classi e metodi restano identici a quelli SQL, quindi il codice che usa il repository non cambia.

Ci sono però differenze esplicite. Non sono supportati:
- `on_delete: cascade`;
- le query `prefix` su colonne non indicizzate;
- `tenancy: schema`.

Le transazioni multi-documento richiedono un replica set.
