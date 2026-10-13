# Multi-tenant

Ogni tabella sceglie come separare i dati delle Organization con la chiave `tenancy` del suo schema. Il default del progetto è in `model.tenancy.default` (installer: `--tenancy`).

| `tenancy` | Dove stanno i dati | Cosa fa kybes |
|---|---|---|
| `none` | tabella condivisa da tutte le Organization (cataloghi, tipologie) | niente |
| `column` | stessa tabella, colonna `TenantId` | aggiunge la colonna, filtra ogni metodo, assegna il tenant in inserimento, controlla che i record collegati siano dello stesso tenant, rende univocità e indici per tenant, genera la row-level security |
| `schema` | uno schema PostgreSQL per Organization (`tenant_<chiave>`) | genera la funzione che crea lo schema del tenant, i nomi di schema e il `search_path` |
| `database` | un database per Organization | genera il DDL del database del tenant e l'URL a partire da un modello |

In tutti i casi diversi da `none` il repository lavora solo con un tenant legato alla sessione: senza, rifiuta di essere creato.

## Il contesto del tenant

Il tenant si lega una volta alla sessione dell'ORM, di solito nel middleware che ha già letto l'Organization dal token SSO. Una sessione serve un solo tenant.

| Linguaggio | Legare il tenant | Leggerlo | In una Unit of Work |
|---|---|---|---|
| Python | `bind_tenant(session, tenant)` | `tenant_of(session)` | `run_in_transaction(factory, work, tenant=t)` |
| TypeScript | `bindTenant(em, tenant)` | `tenantOf(em)` | `runInTransaction(ds, work, { tenant: t })` |
| Java | `Tenancy.bind(em, tenant)` | `Tenancy.of(em)` | `UnitOfWork.run(emf, work, tables, isolation, retries, backoff, t)` |
| C# | `db.BindTenant(tenant)` | `db.RequireTenant()` | `UnitOfWork.RunAsync(db, work, tenant: t)` |

Le firme dei metodi dei repository non cambiano: `getById(id)` resta `getById(id)`, ma con `tenancy: column` restituisce il record solo se è del tenant legato.

Il tipo dell'identificativo è `model.tenancy.id_type`: `uuid` (default, per esempio il `tid` di Entra ID) o `string` (fino a 64 caratteri).

## `column`

Lo schema non dichiara `TenantId`: la aggiunge il generatore, subito dopo la chiave primaria. Il nome è riservato.

| Operazione | Comportamento |
|---|---|
| lettura per chiave, conteggio, esistenza, pagine, ricerche univoche, liste per chiave esterna, query | solo righe del tenant legato |
| inserimento | `TenantId` preso dalla sessione; un valore diverso è rifiutato (`TenantId`: tenant diverso) |
| inserimento e aggiornamento con una chiave esterna verso un'altra tabella `column` | il record collegato deve essere dello stesso tenant, altrimenti errore `non trovato` sulla chiave |
| aggiornamento e cancellazione di un record di un altro tenant | come un record inesistente |
| figli di una relazione `one_to_many` verso una tabella `column` | solo quelli del tenant |
| colonne `unique` e indici | per tenant: `(tenant_id, numero)`; lo stesso numero d'ordine può esistere in due Organization |

Il filtro è nel codice generato. In più, `db/generated/tenancy/_rls.sql` attiva la row-level security di PostgreSQL come seconda difesa. Ogni riga è visibile e scrivibile solo se `app.tenant_id` coincide con il suo `TenantId`. La Unit of Work con il tenant imposta `app.tenant_id` per la transazione. Il ruolo dell'applicazione non deve avere `BYPASSRLS` e non deve essere un superutente.

## `schema`

Le tabelle `schema` non sono in `_all.sql`. Per ogni nuova Organization:

```sql
SELECT kybes_create_tenant_schema('tenant_<chiave>');   -- da db/generated/tenancy/_schema_per_tenant.sql
```

La funzione rifiuta nomi diversi da `tenant_[a-z0-9_]`, crea lo schema, le tabelle, le chiavi (anche verso le tabelle condivise in `public`) e gli indici. Il nome dello schema lo dà `schema_for(tenant)` (`schemaFor`, `Tenancy.schemaFor`, `Tenancy.SchemaFor`).

Le connessioni del tenant usano `search_path_for(tenant)`, cioè `"tenant_<chiave>", public`:

| Linguaggio | Dove si imposta |
|---|---|
| Python | `create_engine(url, connect_args={"options": "-csearch_path=" + search_path_for(t)})` |
| TypeScript | `new DataSource({ ..., extra: { options: "-c search_path=" + searchPathFor(t) } })` |
| Java | URL JDBC con `currentSchema=tenant_<chiave>,public` |
| C# | connection string Npgsql con `Search Path=tenant_<chiave>,public` |

Una tabella `schema` può riferirsi ad altre tabelle `schema` e a tabelle condivise (`none`).

## `database`

Le tabelle `database` stanno in `db/generated/tenancy/_database_per_tenant.sql`, da eseguire in ogni database di tenant. L'URL del database lo dà `database_url_for(modello, tenant)`, con un modello che contiene `{tenant}`, per esempio `postgresql://app@db/app_{tenant}`. Una tabella `database` può riferirsi solo ad altre tabelle `database`.

## Relazioni tra modalità

| Tabella figlia → padre | `none` | `column` | `schema` | `database` |
|---|---|---|---|---|
| `none` | sì | no | no | no |
| `column` | sì | sì, stesso tenant | no | no |
| `schema` | sì | no | sì | no |
| `database` | no | no | no | sì |

Il generatore rifiuta le altre combinazioni con il motivo: per esempio un dato condiviso non può dipendere da un tenant.

## Test generati

Ogni tabella multi-tenant ha il requisito `REQ-<Tabella>-TENANT` e questi casi:

| Caso | Tabelle | Verifica |
|---|---|---|
| `TC-<T>-TENANT-REQUIRED` | tutte le modalità | repository su una sessione senza tenant: errore |
| `TC-<T>-TENANT-ISOLATION` | `column` | un record del tenant A, con il tenant B legato, non si legge, non si conta, non si elenca, non si modifica, non si cancella; i suoi figli non si vedono |
| `TC-<T>-TENANT-ASSIGN` | `column` | l'inserimento prende il tenant della sessione; un tenant diverso è rifiutato |
| `TC-<T>-TENANT-UNIQUE` | `column` con colonne univoche | lo stesso valore in due tenant è accettato |
| `TC-<T>-<Relazione>-TENANT-PARENT` | `column` verso `column` | un padre di un altro tenant è rifiutato |

I moduli comuni hanno `REQ-KYBES-TENANT` (legare e scollegare il tenant, nomi di schema e database, Unit of Work con tenant). I test generati legano il tenant di prova `TENANT_A` alla sessione; i test custom lo ricevono allo stesso modo.

La CI del kit verifica su PostgreSQL reale anche il DDL: con la row-level security un ruolo senza `BYPASSRLS` vede e scrive solo le righe del proprio tenant; la funzione crea gli schemi di due tenant separati; il DDL crea le tabelle in un database di tenant.

## Archivio

Con `archive` l'archivio è separato per tenant: partizione `tenant=<id>` nei percorsi dei Parquet e degli oggetti per chiave, partizione `injected` in Athena (ogni query indica il tenant), lettura per chiave limitata al tenant della sessione. Il job elabora un tenant alla volta: per le tabelle `column` con un ruolo `BYPASSRLS` o con i tenant in `KYBES_TENANTS`, per `schema` e `database` come descritto in [archivio](archivio.md#multi-tenant).
