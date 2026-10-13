# Archivio e conservazione

Una tabella può spostare i record vecchi dalla tabella hot a un archivio in Parquet su Amazon S3 o Azure Blob Storage (`archive`), e cancellarli definitivamente dopo un TTL (`retention`). Le chiavi sono descritte in [schema delle tabelle](schema-yaml.md#archivio); qui c'è come funziona.

## Cosa genera kybes

| File | Contenuto |
|---|---|
| `jobs/generated/_engine/` | motore comune dei job (Python): `kybes_jobs/`, test, `pyproject.toml`, `Dockerfile` |
| `jobs/generated/<t>-archive/config.json` | configurazione del job della tabella: colonne, età, partizioni, figli, modalità |
| `jobs/generated/<t>-archive/kubernetes.yaml` | CronJob, ScaledJob KEDA o Deployment |
| `jobs/generated/<t>-retention/` | come sopra, per una tabella con sola conservazione |
| `jobs/generated/_engine/tests/test_<t>_job.py` | test del job della tabella sulla sua configurazione |
| `db/generated/athena/<T>.sql` | tabella esterna Athena sui Parquet (target `s3`) |
| `db/generated/synapse/<T>.sql` | vista Synapse serverless sui Parquet (target `blob`) |
| `kybes_archive_runs` in `db/generated/ddl/postgres/_all.sql` | registro dei passaggi confermati (in `_database_per_tenant.sql` per le tabelle per database) |
| `getById` dei repository | con `read_through: true`, cerca anche nell'archivio |

`<t>` è il nome della tabella in minuscolo con i trattini: `RigheOrdine` → `righe-ordine-archive`.

## Esempio

```yaml
table: Ordini
tenancy: column
archive:
  after: 5y                 # gli ordini più vecchi di 5 anni lasciano la tabella hot
  column: Data
  target: s3
  partition_by: [year, month]   # tenant in testa, implicita con tenancy: column
  read_through: true
  job: { mode: cron, schedule: "17 3 * * *" }
retention:
  delete_after: 10y         # poi spariscono anche dall'archivio
```

## Lo spostamento

Il job lavora su un'unità alla volta: la tabella, oppure la tabella di un tenant (vedi [Multi-tenant](#multi-tenant)). Per ogni unità:

1. prende il lock consultivo PostgreSQL dell'unità: se un altro job ci sta già lavorando, salta l'unità;
2. completa o scarta i passaggi rimasti a metà da un job interrotto (recupero);
3. archivia a lotti di `job.batch_size` righe, finché ci sono righe da spostare;
4. applica la conservazione.

Un lotto è una transazione:

| Passo | Cosa succede | Se fallisce |
|---|---|---|
| selezione | righe con `column` più vecchia di `after`, senza figli nella tabella hot, ordinate per età (`FOR UPDATE SKIP LOCKED`) | nessun effetto |
| staging | un Parquet per partizione e, con `read_through`, un oggetto JSON per record, scritti in `<tabella>/_staging/<tenant>/<passaggio>/` con un `manifest.json` | rollback, staging scartato |
| verifica | ogni file riletto: SHA-256 uguale a quello scritto; per i Parquet righe e chiavi uguali a quelle selezionate | rollback, staging scartato |
| cancellazione | `DELETE` delle righe selezionate; il numero di righe cancellate deve coincidere | rollback, staging scartato |
| registrazione | riga in `kybes_archive_runs`, nella stessa transazione della cancellazione | rollback, staging scartato |
| commit | le righe non sono più nella tabella hot, il passaggio è registrato | — |
| promozione | i file passano dallo staging alla posizione definitiva, verificati con lo SHA-256 del manifest; poi staging e registrazione vengono rimossi | il job successivo la completa (recupero) |

In ogni momento un record è nella tabella hot o nell'archivio verificato, mai in nessuno dei due. Il recupero distingue i due casi con `kybes_archive_runs`: un passaggio registrato viene promosso, uno non registrato viene scartato.

Un record con figli nella tabella hot (righe di un'altra tabella che lo referenziano con una relazione `many_to_one`) non viene archiviato, qualunque sia `on_delete`: archiviarlo li lascerebbe orfani o, con `cascade`, li cancellerebbe senza archiviarli. Per testate e righe, dai alle righe la stessa colonna di data e archiviale con lo stesso `after`: quando le righe sono uscite, esce anche la testata.

## Struttura dell'archivio

Percorsi relativi alla location dell'archivio (`model.archive.s3` o `model.archive.blob`):

```
<tabella>/tenant=<tenant>/year=2019/month=03/part-<passaggio>.parquet   dati, una partizione per cartella
<tabella>/_keys/tenant=<tenant>/<chiave>.json                         oggetto per chiave (read_through)
<tabella>/_staging/<tenant>/<passaggio>/...                           area di lavoro del job
```

`tenant=` c'è solo per le tabelle multi-tenant; le partizioni di data seguono `partition_by`. Tenant e chiave nei percorsi sono codificati: lettere, cifre, `_` e `-` restano, il resto diventa `%XX` in UTF-8 (`a/b` → `a%2Fb`). Le cartelle che iniziano con `_` sono ignorate da Athena e Synapse.

I Parquet (compressione Snappy) hanno le colonne della tabella con i nomi del database:

| Tipo dello schema | Parquet | Athena | Synapse |
|---|---|---|---|
| `uuid`, `string`, `text` | string | `string` | `varchar` |
| `int`, `bigint` | int32, int64 | `int`, `bigint` | `int`, `bigint` |
| `decimal` | decimal(p, s) | `decimal(p,s)` | `decimal(p,s)` |
| `bool` | boolean | `boolean` | `bit` |
| `date` | date32 | `date` | `date` |
| `datetime` | timestamp µs UTC | `timestamp` | `datetime2(6)` |
| `json` | string (JSON) | `string` | `varchar(max)` |

L'oggetto per chiave è un documento JSON con i nomi delle colonne dello schema: uuid in minuscolo, `decimal` e `bigint` come stringa (nessuna perdita di precisione in JavaScript), `date` come `AAAA-MM-GG`, `datetime` in ISO 8601 UTC con microsecondi, `json` come valore JSON. I quattro linguaggi lo decodificano nello stesso modo.

## Lettura dall'archivio (read_through)

Il lettore dell'archivio si lega alla sessione, come il tenant. Senza lettore `getById` legge solo la tabella hot.

| Linguaggio | Legare il lettore | Lettore su cartella | Interfaccia |
|---|---|---|---|
| Python | `bind_archive(session, reader)` | `FileArchiveReader(cartella)` | `fetch(path) -> bytes \| None` |
| TypeScript | `bindArchive(em, reader)` | `new FileArchiveReader(cartella)` | `fetch(path): Promise<Uint8Array \| null>` |
| Java | `Archive.bind(em, reader)` | `new Archive.FileReader(Path.of(cartella))` | `Archive.Reader`: `byte[] fetch(String path)`, null se assente |
| C# | `db.BindArchive(reader)` | `new FileArchiveReader(cartella)` | `IArchiveReader`: `Task<byte[]?> FetchAsync(string path, CancellationToken ct)` |

Il record letto dall'archivio non è collegato alla sessione: è in sola lettura. `update` e `delete` lavorano solo sulla tabella hot, quindi per loro un record archiviato non esiste. Con le tabelle multi-tenant il percorso contiene il tenant della sessione: un'Organization non legge l'archivio di un'altra.

Per S3 e Blob il lettore è una classe di poche righe con l'SDK del cloud che il progetto usa già:

```python
class S3ArchiveReader:  # boto3
    def __init__(self, bucket, prefix):
        self.s3, self.bucket, self.prefix = boto3.client("s3"), bucket, prefix

    def fetch(self, path):
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=f"{self.prefix}/{path}")["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None
```

```ts
// @aws-sdk/client-s3
const s3 = new S3Client({});
export const s3Reader: ArchiveReader = {
  async fetch(path) {
    try {
      const out = await s3.send(new GetObjectCommand({ Bucket: "kybes-archive", Key: `archive/${path}` }));
      return await out.Body!.transformToByteArray();
    } catch (e) {
      if ((e as { name?: string }).name === "NoSuchKey") return null;
      throw e;
    }
  },
};
```

```java
// AWS SDK for Java v2
S3Client s3 = S3Client.create();
Archive.Reader reader = path -> {
    try {
        return s3.getObjectAsBytes(b -> b.bucket("kybes-archive").key("archive/" + path)).asByteArray();
    } catch (NoSuchKeyException e) {
        return null;
    }
};
```

```csharp
// Azure.Storage.Blobs
public sealed class BlobArchiveReader(BlobContainerClient container, string prefix) : IArchiveReader
{
    public async Task<byte[]?> FetchAsync(string path, CancellationToken ct = default)
    {
        try { return (await container.GetBlobClient($"{prefix}/{path}").DownloadContentAsync(ct)).Value.Content.ToArray(); }
        catch (RequestFailedException e) when (e.Status == 404) { return null; }
    }
}
```

## Conservazione

| Configurazione | Cosa cancella |
|---|---|
| `archive` e `retention` | le partizioni dell'archivio finite prima di `delete_after` fa (una partizione `year=2019/month=03` finisce il 1° aprile 2019), con i loro oggetti per chiave |
| solo `retention` | le righe della tabella hot con `column` più vecchia di `delete_after`, a lotti; un figlio `restrict` trattiene il record, `cascade` e `set_null` seguono la regola dichiarata |

Mesi e anni si contano sul calendario: 1 mese prima del 31 marzo è il 29 febbraio di un anno bisestile.

Con tabelle `column`, il job applica la conservazione anche ai tenant che non hanno più righe nella tabella hot, cercandoli nell'archivio. Se la location contiene `{tenant}`, indica i tenant in `KYBES_TENANTS`.

## Multi-tenant

| `tenancy` | Unità del job | Tenant elaborati | Requisiti |
|---|---|---|---|
| `none` | la tabella | — | — |
| `column` | la tabella, un tenant alla volta | `SELECT DISTINCT` sulla colonna `TenantId` più quelli presenti nell'archivio, oppure `KYBES_TENANTS` | senza `KYBES_TENANTS` il ruolo del job deve avere `BYPASSRLS`: il job lo controlla e si ferma con un messaggio. Con `KYBES_TENANTS` basta la row-level security: il job imposta `app.tenant_id` in ogni transazione |
| `schema` | la tabella nello schema `tenant_<chiave>` | gli schemi `tenant_*` (tenant uuid) oppure `KYBES_TENANTS` | con tenant `string` serve `KYBES_TENANTS` |
| `database` | la tabella nel database del tenant | `KYBES_TENANTS` | `KYBES_DATABASE_URL` contiene `{tenant}`, come `database_url_for` |

L'archivio è sempre separato per tenant: partizione `tenant=<id>` nel percorso e, nella query Athena, partizione `injected` che obbliga a filtrare per tenant. Per tenere i file di ogni Organization sotto un prefisso proprio (per esempio con una policy IAM per prefisso), metti `{tenant}` nel prefisso della location: `s3://kybes-archive/{tenant}/archive`. Il nome del bucket o del container non può contenere `{tenant}`.

## Job su Kubernetes

| `job.mode` | Manifest | Quando gira |
|---|---|---|
| `cron` | `CronJob` (`concurrencyPolicy: Forbid`, fuso UTC) | a `job.schedule` |
| `keda` | `ScaledJob` KEDA con trigger `postgresql` e `TriggerAuthentication`, più un `CronJob` giornaliero | quando la query del trigger trova righe da elaborare (polling ogni `job.interval` secondi); il passaggio giornaliero completa i recuperi e applica la conservazione anche senza righe in arrivo |
| `engine` | `Deployment` con una replica (`--loop`) | sempre attivo, un passaggio ogni `job.interval` secondi; si ferma pulito con SIGTERM |

L'immagine è una sola per tutti i job:

```bash
docker build -f jobs/generated/_engine/Dockerfile -t kybes-jobs:latest jobs/generated
```

| Risorsa | Contenuto |
|---|---|
| segreto `kybes-jobs-db` | `url`: `KYBES_DATABASE_URL`; `keda`: stringa di connessione per il trigger KEDA; `azure-storage` (facoltativo): stringa di connessione dello storage account |
| ConfigMap `kybes-jobs` | `tenants` (facoltativo): `KYBES_TENANTS` |
| service account `kybes-jobs` | IRSA (S3) o workload identity (Blob): il job usa la catena di credenziali standard dell'SDK |

Nomi di immagine, namespace, service account e segreto si cambiano in `model.archive` (vedi [configurazione](configurazione.md)).

Il comando del container è `python -m kybes_jobs run /app/jobs/<t>-archive/config.json [--loop]`. Variabili:

| Variabile | Uso |
|---|---|
| `KYBES_DATABASE_URL` | `postgresql://utente:password@host:5432/db` (con `{tenant}` per le tabelle per database) |
| `KYBES_ARCHIVE_URL` | location dell'archivio se diversa da quella della configurazione, per esempio `file:///tmp/archivio` in sviluppo |
| `KYBES_TENANTS` | tenant da elaborare, separati da virgola |

Uscita: 0 riuscito, 1 errore durante il lavoro (il CronJob o KEDA ritentano), 2 configurazione non valida. Ogni evento è una riga JSON su stdout (`archived`, `purged`, `deleted`, `recovered`, `discarded`, `locked`, `done` con i conteggi); gli errori vanno su stderr.

Si può eseguire anche senza Kubernetes:

```bash
pip install -e "jobs/generated/_engine[s3]"
KYBES_DATABASE_URL=postgresql://app@localhost/app python -m kybes_jobs run jobs/generated/ordini-archive/config.json
```

## Interrogare l'archivio

`db/generated/athena/<T>.sql` crea la tabella `<tabella>_archive` con partition projection: le partizioni si calcolano dal percorso, senza `MSCK REPAIR`. Con le tabelle multi-tenant la partizione `tenant` è `injected`, quindi ogni query la deve indicare:

```sql
SELECT numero, totale FROM ordini_archive
WHERE tenant = '3f1c6a9e-...' AND year = 2019 AND month BETWEEN 1 AND 6;
```

`db/generated/synapse/<T>.sql` crea la vista `dbo.<tabella>_archive` per Azure Synapse serverless con `OPENROWSET` e le partizioni come colonne (`filepath()`).

## Configurazione

| Chiave in `kybes.config.json` | Default | Uso |
|---|---|---|
| `model.jobs_dir` | `jobs/generated` | cartella dei job generati |
| `model.archive.s3` | `s3://kybes-archive/archive` | location per `target: s3`, anche nel DDL Athena |
| `model.archive.blob` | `https://kybesarchive.blob.core.windows.net/archive` | location per `target: blob` (`https://<account>.blob.core.windows.net/<container>/prefisso` o `az://<container>/prefisso`) |
| `model.archive.image` | `kybes-jobs:latest` | immagine dei job |
| `model.archive.namespace` | `default` | namespace Kubernetes |
| `model.archive.service_account` | `kybes-jobs` | service account dei pod |
| `model.archive.db_secret` | `kybes-jobs-db` | segreto con `url`, `keda`, `azure-storage` |

## Test generati

| Requisito | Casi | Dove |
|---|---|---|
| `REQ-<T>-ARCHIVE` | `TC-<T>-JOB-ARCHIVE` (record vecchio archiviato nella sua partizione, recente rimasto), `TC-<T>-JOB-SAFE` (archivio non scrivibile: record nella tabella hot), `TC-<T>-JOB-CHILD-<Figlia>-<Relazione>` (record con figli trattenuto) | `jobs/generated/_engine/tests/test_<t>_job.py` |
| `REQ-<T>-RETENTION` | `TC-<T>-JOB-RETENTION` (partizione e oggetti per chiave cancellati) o, senza archivio, `TC-<T>-JOB-TTL` | come sopra |
| `REQ-<T>-ARCHIVE-READ` | `TC-<T>-ARCHIVE-READ`, `-READ-MISS`, `-HOT-FIRST`, `-READ-TENANT` | test generati del modello nei quattro linguaggi |
| `REQ-KYBES-ARCHIVE-READ` | percorsi, lettore su cartella, decodifica di ogni tipo | test dei moduli comuni nei quattro linguaggi |
| `REQ-KYBES-JOB-*` | configurazione, formati, archivi S3/Blob/file, spostamento, sicurezza e recupero, conservazione, tenant, lock, riga di comando | `jobs/generated/_engine/tests/test_engine.py`, specifica in `docs/generated/verification/kybes-jobs.md` |

`verify.py` esegue i test del motore come un linguaggio in più (`--lang=jobs`) e applica la soglia di copertura dell'ASIL più alto del progetto ai file di `kybes_jobs`. Servono le dipendenze del motore: `pip install -e "jobs/generated/_engine[test]"`. Con `KYBES_TEST_DATABASE_URL` i test girano su PostgreSQL (lock consultivi reali compresi), altrimenti su SQLite.

## Limiti

- Il motore dei job è in Python per tutti i progetti, qualunque sia il linguaggio del modello: è un'immagine a sé, non entra nel codice dell'applicazione.
- Lock consultivi, `SKIP LOCKED` e controllo della row-level security sono di PostgreSQL; su altri database il job va eseguito in una sola istanza.
- `read_through` vale per la lettura per chiave. Le query su molti record archiviati si fanno con Athena o Synapse.
- Un record con figli resta nella tabella hot finché i figli non sono archiviati o cancellati.
