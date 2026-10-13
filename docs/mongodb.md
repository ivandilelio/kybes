# MongoDB

Una tabella può vivere in MongoDB invece che in un database SQL: basta `storage: mongo` nel suo schema. kybes genera nei quattro linguaggi lo stesso repository delle tabelle SQL. Restano uguali:
- nomi di file e classi;
- metodi e firme;
- validazioni ed errori;
- paginazione a cursore, con lo stesso formato del cursore;
- query dichiarate;
- tenant;
- test ISO 26262-6.

Il codice che usa il repository non sa dove stanno i dati: cambia solo la sessione con cui lo crea.

```yaml
# schemas/db/Segnalazioni.yaml
table: Segnalazioni
storage: mongo
tenancy: column
columns:
  - { name: Id, type: uuid, primary_key: true }
  - { name: Codice, type: string, length: 20, required: true, unique: true }
  - { name: Priorita, type: int, required: true }
queries:
  - name: ApertePerPriorita
    returns: page
    where:
      - { column: Priorita, op: gte, param: DaPriorita }
    order_by: [-Priorita]
```

Nello stesso progetto possono convivere tabelle SQL e collection MongoDB. Un progetto può avere anche solo collection. In quel caso kybes non genera i moduli che servono solo alle tabelle SQL:
- Unit of Work SQL;
- archivio;
- `AppDbContext` in C#;
- parti SQL di paginazione e tenant.

Anche i test non richiedono un PostgreSQL.

## Formato dei documenti

La collection ha il nome della tabella nel DB (`db_name`). I campi hanno i nomi delle colonne nel DB, con il formato seguente:

| Colonna | Nel documento |
|---|---|
| chiave primaria | `_id` |
| `uuid` | stringa minuscola (`"0b7c…"`), confrontabile e ordinabile come in PostgreSQL |
| `string`, `text` | stringa |
| `int` | int32 |
| `bigint` | int64 (in TypeScript il driver restituisce `bigint`, il modello espone la stringa come per SQL) |
| `decimal` | Decimal128, senza perdita di precisione |
| `bool` | booleano |
| `date` | data BSON a mezzanotte UTC |
| `datetime` | data BSON, al millisecondo: i valori generati (`generated`) sono già troncati al millisecondo |
| `json` | valore BSON (documento, array, numero…), non una stringa |
| valore nullo | campo assente dal documento |

Le chiavi intere generate (`auto` su `int` o `bigint`) vengono da un contatore per collection nella collection `kybes_counters` (`{_id: "<collection>", seq: n}`). Le chiavi `uuid` generate sono UUID v4. Una chiave indicata dal chiamante resta quella; fa eccezione Java, dove la chiave generata non ha setter.

## Sessione e transazioni

| Linguaggio | Sessione (come un `Session` / `EntityManager` / `AppDbContext`) | Transazione | Indici |
|---|---|---|---|
| Python | `mongo_session(client, "app", tenant)` | `run_in_mongo_transaction(client, "app", work, tenant=t)` | `ensure_mongo_indexes(db)` |
| TypeScript | `mongoSession(client, "app", tenant)` | `runInMongoTransaction(client, "app", work, { tenant: t })` | `await ensureMongoIndexes(db)` |
| Java | `MongoSession.open(client, "app", tenant)` | `MongoSession.transaction(client, "app", em -> …, t)` | `MongoIndexes.ensure(db)` |
| C# | `MongoSession.Open(client, "app", tenant)` | `await MongoSession.TransactionAsync(client, "app", async em => …, t)` | `await MongoIndexes.EnsureAsync(db)` |

```python
from pymongo import MongoClient
from model import SegnalazioniRepository, mongo_session, run_in_mongo_transaction

client = MongoClient(os.environ["MONGO_URL"], tz_aware=True)
repo = SegnalazioniRepository(mongo_session(client, "app", tenant))
page = repo.list_aperte_per_priorita(da_priorita=3)

def chiudi(ms):
    return SegnalazioniRepository(ms).update(id, {"stato": "chiusa"})

run_in_mongo_transaction(client, "app", chiudi, tenant=tenant)
```

- **Transazioni:** sono multi-documento e richiedono un replica set, anche di un solo nodo. Il driver ripete da solo gli errori transitori (`TransientTransactionError`). L'isolamento è sempre snapshot, quindi la chiave `transactions` dello schema non è ammessa su una collection.
- **Fuori da una transazione:** ogni scrittura è atomica sul singolo documento.
- **Indici:** si creano all'avvio dell'applicazione o nel deploy. La funzione è idempotente: rilanciarla non cambia nulla.
- **Tenant:** con `tenancy: column` e `database` si lega alla sessione come per SQL (`bind_tenant`, `bindTenant`, `bindTenant`, `BindTenant`). Senza un tenant legato il repository rifiuta di essere creato.

## Indici

Gli indici sono quelli che kybes calcola per SQL ([Query e indici](query-e-indici.md)), con gli stessi nomi (`ux_…`, `ix_…`, `qx_…`) e lo stesso ordine dei campi. Con `tenancy: column` il primo campo è `tenant_id`.

- **Colonne `unique` facoltative:** l'indice univoco è parziale (`partialFilterExpression: {campo: {$exists: true}}`), come in PostgreSQL dove i valori nulli non si scontrano. Più documenti senza il valore sono ammessi.
- **`retention`:** diventa un indice TTL sulla colonna dell'età, con `expireAfterSeconds` uguale alla durata in secondi. Se esiste già un indice semplice e non univoco su quella colonna, diventa lui l'indice TTL; altrimenti kybes crea `ttl_<collection>_<colonna>`. MongoDB cancella i documenti scaduti con un suo processo in background (circa ogni 60 secondi): non serve un job.

## Query

| `op` | Filtro MongoDB |
|---|---|
| `eq` | `{campo: v}` |
| `ne` | `{campo: {$nin: [v, null]}}`: come in SQL, un valore assente non è "diverso" |
| `lt`, `lte`, `gt`, `gte` | `{campo: {$lt: v}}`… |
| `in` | `{campo: {$in: [...]}}`; una lista vuota restituisce subito un risultato vuoto |
| `prefix` | `{campo: {$regex: "^…"}}` con i caratteri speciali protetti; con un indice sul campo MongoDB lo usa come intervallo |
| `is_null` | `{campo: null}` (assente o nullo) |
| `not_null` | `{campo: {$ne: null}}` |

La paginazione a cursore è la stessa delle tabelle SQL ([Paginazione](paginazione.md)): stesso contratto, stesse validazioni di `limit` e `sort`, stesso cursore. Il keyset diventa un `$or` di condizioni sulle colonne dell'ordinamento, seguito dalla chiave.

## Integrità referenziale

MongoDB non ha chiavi esterne. Le garantisce il repository generato:

| Operazione | Controllo |
|---|---|
| inserimento e aggiornamento con una chiave esterna | il record collegato deve esistere (e, con `tenancy: column`, essere del tenant legato), altrimenti `ModelValidationError` con `non trovato` sulla chiave |
| cancellazione con figli `restrict` | rifiutata con `ModelValidationError` sul nome della relazione inversa: `record collegati` |
| cancellazione con figli `set_null` | la chiave esterna viene tolta dai figli (`$unset`) prima della cancellazione |

I controlli sono letture separate dalla scrittura. Per avere la garanzia anche con scritture concorrenti si esegue il lavoro in una transazione MongoDB.

## Cosa non è ammesso

Il generatore rifiuta lo schema, con un messaggio che indica l'alternativa:

| Configurazione | Perché | Alternativa |
|---|---|---|
| relazione tra una collection e una tabella SQL | non c'è un posto dove garantirla né una transazione comune | stessa `storage` per le due tabelle, oppure una colonna semplice con il riferimento |
| `on_delete: cascade` verso una collection | una cancellazione a cascata su più collection non è atomica senza transazione | `restrict` o `set_null` |
| `tenancy: schema` | MongoDB non ha schemi | `column` o `database` (un database MongoDB per tenant) |
| `archive` | l'archivio Parquet lavora sulle tabelle SQL | `retention` (indice TTL) o una tabella SQL |
| `retention.job` | la cancellazione la fa l'indice TTL | togliere `job` |
| `retention` su una collection a cui altre tabelle si riferiscono | l'indice TTL cancella senza controllare i record collegati | nessuna relazione verso la collection con `retention` |
| `transactions` | l'isolamento delle transazioni MongoDB è sempre snapshot | togliere la chiave |

## Dipendenze

`install.sh --scaffold` aggiunge il driver ufficiale a ogni pacchetto del modello:

| Linguaggio | Driver |
|---|---|
| Python | `pymongo` (extra `mongo`: `pip install -e "libs/db-models/python[mongo]"`) |
| TypeScript | `mongodb` 7 |
| Java | `org.mongodb:mongodb-driver-sync` |
| C# | `MongoDB.Driver` |

In Python il client va creato con `tz_aware=True`, così le date tornano con il fuso UTC.

## Test

I test generati delle collection ([Verifica di unità](verifica.md)) girano su un MongoDB vero, indicato da `KYBES_TEST_MONGO_URL`. Ogni test usa un database nuovo (`kybes_test_<casuale>`) con gli indici del modello e lo elimina alla fine. Le transazioni richiedono un replica set:

```bash
docker run -d --name mongo -p 27017:27017 mongo:7 --replSet rs0
docker exec mongo mongosh --eval 'rs.initiate({_id: "rs0", members: [{_id: 0, host: "localhost:27017"}]})'
export KYBES_TEST_MONGO_URL="mongodb://localhost:27017/?replicaSet=rs0"
python3 tools/kybes/plugins/kybes/scripts/verify.py
```

Senza `KYBES_TEST_MONGO_URL`, `verify.py` segnala che i test non sono stati eseguiti e non li considera superati. Il workflow di CI installato da kybes avvia MongoDB con replica set quando uno schema dichiara `storage: mongo`.

Oltre ai casi delle tabelle SQL, il catalogo aggiunge:

| Caso | Verifica |
|---|---|
| `TC-<T>-<Rel>-PARENT-MISSING` | chiave esterna verso un record inesistente: errore `non trovato` |
| `TC-<T>-DELETE-<Figlio>-<Rel>` | cancellazione con figli `restrict` (rifiutata) o `set_null` (chiave tolta dai figli) |
| `TC-<T>-KEY-GIVEN` | chiave indicata dal chiamante conservata; in Java, chiave sempre generata e diversa a ogni inserimento |
| `TC-<T>-<Col>-UNIQUE-NULL` | più documenti senza la colonna univoca facoltativa |
| `TC-<T>-TTL-INDEX` | indice TTL presente, sulla colonna giusta e con la durata dichiarata |
| `TC-KYBES-MONGO-*` | conversioni di tutti i tipi, prefisso con caratteri speciali, contatori, sessione e tenant, commit e rollback di una transazione, indici ripetibili e parziali |
