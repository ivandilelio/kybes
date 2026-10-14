# API REST

kybes genera le API REST esposte dai servizi con lo stesso approccio del modello: si dichiara cosa esporre, il generatore produce contratto, validazione, routing, middleware, controller e test nei quattro linguaggi. Il codice scritto a mano si riduce alla logica degli endpoint custom.

| Cosa | Dove lo scrivi | Cosa genera kybes |
|---|---|---|
| CRUD, query dichiarate e relazioni di una tabella | blocco `api:` in `schemas/db/<Tabella>.yaml` | operazioni, schemi JSON, controller |
| endpoint custom (azioni, report, flussi) | `schemas/openapi.yaml`, un `operationId` per endpoint | interfaccia `Operations` da implementare nel service |
| contratto completo | — | `schemas/generated/openapi.yaml` (OpenAPI 3.0.3), da pubblicare sul gateway |
| validazione dell'input, routing, errori, identità | — | nucleo indipendente dal runtime, uguale nei quattro linguaggi |
| esecuzione | — | adattatori per AWS Lambda, server HTTP senza framework e framework |
| test ISO 26262-6 | — | test di unità per ogni operazione e per il nucleo, con copertura per ASIL |

Il codice API generato sta accanto al modello, nella cartella `api` (`api/generated`), ed è protetto dagli hook come il resto del codice generato.

## Il blocco `api` dello schema

```yaml
# schemas/db/Ordini.yaml
table: Ordini
# ... columns, relations, queries ...
api:
  path: ordini                         # predefinito: nome della tabella in kebab-case
  operations: [list, get, create, update, delete]   # predefinito: tutte
  queries: [DelClienteDal, PerNumero]  # predefinito: tutte le query dichiarate
  relations: [Cliente, Righe]          # predefinito: tutte le relazioni
  scopes: { read: ordini.read, write: [ordini.write] }
  context: vendite                     # predefinito: primo segmento di path
```

`api: true` espone la tabella con tutti i valori predefiniti. Senza blocco `api` la tabella non è esposta.

| Chiave | Valori |
|---|---|
| `path` | segmenti in minuscolo separati da `/`, senza `/` iniziale (`ordini`, `vendite/ordini`) |
| `operations` | sottoinsieme di `list`, `get`, `create`, `update`, `delete` |
| `queries` | nomi di query dichiarate in `queries` |
| `relations` | nomi di relazioni della tabella |
| `scopes.read`, `scopes.write` | uno scope o una lista: servono **tutti** per leggere (`list`, `get`, query, relazioni) o scrivere |
| `context` | nome del contesto (minuscolo): raggruppa le operazioni per microservizio o function |

Due tabelle non possono avere lo stesso `path`.

### Endpoint generati

| Operazione | Metodo e percorso | Esito | operationId |
|---|---|---|---|
| list | `GET /ordini?limit=&cursor=&sort=` | 200, pagina | `listOrdini` |
| get | `GET /ordini/{id}` | 200, 404 | `getOrdini` |
| create | `POST /ordini` | 201 con `Location`, 409, 422 | `createOrdini` |
| update | `PATCH /ordini/{id}`, corpo parziale | 200, 404, 409, 422 | `updateOrdini` |
| delete | `DELETE /ordini/{id}` | 204, 404, 409 (record collegati) | `deleteOrdini` |
| query | `GET /ordini/query/del-cliente-dal?clienteId=&daData=` | 200 (pagina, lista o record), 404 per `returns: one` | `ordiniDelClienteDal` |
| relazione | `GET /ordini/{id}/cliente`, `GET /ordini/{id}/righe` | 200 (record o pagina), 404 | `ordiniCliente`, `ordiniRighe` |

La pagina ha la forma `{"items": [...], "nextCursor": "..." | null, "limit": n}`: è il [contratto di paginazione](paginazione.md) del modello, con `limit`, `cursor` e `sort` come parametri di query.

Il contratto generato contiene per ogni tabella gli schemi `Ordini`, `OrdiniPage`, `OrdiniCreate` (campi scrivibili, obbligatori quelli richiesti senza default) e `OrdiniUpdate` (tutti facoltativi), più `Error`. Le operazioni generate hanno `x-kybes: {generated: true, table, kind}`.

### Formato JSON

Uguale in tutti i linguaggi, perché un client non deve sapere in che linguaggio è scritto il servizio.

| Colonna | JSON |
|---|---|
| `uuid` | stringa in minuscolo |
| `string`, `text` | stringa (`maxLength` dalla lunghezza della colonna) |
| `int` | intero a 32 bit |
| `bigint` | stringa di cifre (un numero JSON perde precisione oltre 2^53) |
| `decimal` | stringa con al più `scale` decimali in ingresso; in uscita esattamente `scale` decimali (`"12.50"`), troncati verso lo zero e mai arrotondati, con lo zero sempre senza segno (`"0.00"`) |
| `bool` | booleano |
| `date` | `"AAAA-MM-GG"` |
| `datetime` | ISO 8601 in ingresso (qualsiasi fuso); in uscita sempre UTC al millisecondo (`"2026-02-03T04:05:06.123Z"`) |
| `json` | qualsiasi valore JSON |
| colonna vuota | `null` |

La colonna del tenant non compare mai nel JSON: il tenant viene dall'identità.

## Endpoint custom

Gli endpoint che non sono CRUD si scrivono in `schemas/openapi.yaml`, in OpenAPI 3.0. Ognuno diventa un metodo dell'interfaccia `Operations`, che il service implementa. kybes unisce questi endpoint con quelli generati dagli schemi in `schemas/generated/openapi.yaml`.

```yaml
# schemas/openapi.yaml
openapi: 3.0.3
info: { title: Gestionale API, version: 0.1.0 }
components:
  securitySchemes:
    sso: { type: openIdConnect, openIdConnectUrl: https://login.example.com/.well-known/openid-configuration }
  schemas:
    Conferma:
      type: object
      required: [nota]
      additionalProperties: false
      properties:
        nota: { type: string, minLength: 1, maxLength: 200 }
        urgente: { type: boolean }
security:
  - sso: []
paths:
  /ordini/{id}/conferma:
    post:
      operationId: confermaOrdine
      x-kybes-context: vendite
      security: [{ sso: [ordini.write] }]
      parameters:
        - { name: id, in: path, required: true, schema: { type: string, format: uuid } }
        - { name: notifica, in: query, required: true, schema: { type: boolean } }
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/Conferma' }
      responses:
        '200': { description: ok }
```

Regole controllate dal generatore (gli errori bloccano la generazione e indicano il punto esatto):
- `operationId` obbligatorio, in camelCase, unico anche rispetto alle operazioni generate: diventa il nome del metodo;
- segmenti del percorso in minuscolo o parametri `{nomeCamel}`; i parametri di path dichiarati devono coincidere con quelli del percorso;
- parametri solo `in: path` o `in: query` (header e cookie li gestisce il gateway), di tipo scalare o array di scalari;
- corpo solo `application/json`;
- `$ref` solo verso `#/components/schemas/` e `#/components/parameters/`, senza schemi ricorsivi;
- negli schemi solo le parole chiave che il validatore applica (vedi sotto); `description`, `example`, `title` e simili sono ammesse come documentazione;
- stato di successo: il primo 2xx in `responses` (204 senza corpo);
- `x-kybes-context` facoltativo: predefinito il primo segmento del percorso.

Gli scope di un endpoint custom sono quelli della sua `security` (o della `security` globale). Un endpoint con `security: []` è pubblico.

### Implementare gli endpoint custom

Ogni metodo riceve il `Call` con path, query e body **già validati e convertiti**, l'identità e il correlationId. Restituisce il corpo JSON (con lo stato del contratto) oppure una risposta con stato e header propri: `ApiResponse(status, body, headers)` in Python, `reply(...)` in TypeScript, `ApiResponse.reply(...)` in Java, `ApiResponse.Reply(...)` in C#. I nomi degli header vanno in minuscolo; se la risposta ha un corpo e non indica `content-type`, il nucleo aggiunge `application/json`. `call.base_path` (`basePath`, `BasePath`) è il prefisso dei percorsi, da usare negli header `location`. Gli errori applicativi si sollevano con `ApiError(kind, code, fields)`; gli errori del modello (`ModelValidationError`, tenant mancante, vincoli del database) vengono tradotti dal nucleo.

```python
# Python: un metodo per operationId, nome in snake_case
class Vendite:
    def conferma_ordine(self, call):
        with session_factory() as s:
            ...
        return {"stato": "confermato"}
```

```typescript
// TypeScript: implementa Operations
const vendite: Operations = {
  async confermaOrdine(call) { return { stato: "confermato" }; },
  async reportVendite(call) { return reply(200, { anno: call.query.anno }); },
};
```

```java
// Java: implementa Operations
public final class Vendite implements Operations {
    public Object confermaOrdine(Call call) { return Map.of("stato", "confermato"); }
    public Object reportVendite(Call call) { return ApiResponse.reply(200, Map.of("anno", call.query().get("anno"))); }
}
```

```csharp
// C#: implementa IOperations
public sealed class Vendite : IOperations
{
    public Task<object?> ConfermaOrdine(Call call) => Task.FromResult<object?>(new Dictionary<string, object?> { ["stato"] = "confermato" });
    public Task<object?> ReportVendite(Call call) => Task.FromResult<object?>(ApiResponse.Reply(200, new Dictionary<string, object?> { ["anno"] = call.Query["anno"] }));
}
```

## Il nucleo: routing e middleware

Ogni richiesta attraversa gli stessi passi, nello stesso ordine, in tutti i linguaggi:

1. **correlationId**: dall'header `x-correlation-id` se valido (`[A-Za-z0-9._-]{1,128}`), altrimenti nuovo. Torna sempre nella risposta.
2. **routing**: i segmenti fissi vincono sui parametri (`/ordini/report` prima di `/ordini/{id}`); percorso sconosciuto → 404 `ROUTE_NOT_FOUND`; metodo non ammesso → 405 `METHOD_NOT_ALLOWED` con l'header `allow`.
3. **identità e scope**: operazione protetta senza identità → 401 `IDENTITY_REQUIRED`; scope mancanti → 403 `SCOPE_REQUIRED`.
4. **parametri**: parametri di query sconosciuti, conversione dal testo (interi, numeri, booleani, liste ripetendo il parametro), regole dello schema → 400 `INVALID_REQUEST`.
5. **corpo**: serve `content-type: application/json` (415 `JSON_REQUIRED`); JSON non valido, NaN o UTF-8 non valido → `JSON non valido`; poi lo schema. Un corpo dove non è previsto → `corpo non ammesso`.
6. **controller o metodo del service**, con la traduzione degli errori.

### Validazione

Il validatore applica un sottoinsieme preciso di JSON Schema (OpenAPI 3.0), scritto nel codice generato e senza dipendenze: `type`, `nullable`, `enum`, `minLength`/`maxLength` (in caratteri Unicode), `pattern`, `format` (`uuid`, `date`, `date-time`), `minimum`/`maximum`, `items`, `minItems`/`maxItems`, `properties`, `required`, `additionalProperties` (booleano o schema). Per ogni campo si riporta la prima regola violata, con testi uguali in tutti i linguaggi:

| Regola | Testo |
|---|---|
| campo richiesto assente | `obbligatorio` |
| tipo | `tipo atteso: integer` |
| `null` senza `nullable` | `nullo non ammesso` |
| `enum` | `valore non ammesso` |
| lunghezza | `lunghezza minima 3`, `lunghezza massima 20` |
| `pattern` | `formato non valido` |
| `format` | `formato uuid`, `formato date`, `formato date-time` |
| intervallo | `valore minimo 1`, `valore massimo 200` |
| elementi | `almeno 1 elementi`, `al massimo 5 elementi` |
| campo in più con `additionalProperties: false` | `non ammesso` |
| parametro di query non previsto | `parametro sconosciuto` |
| parametro scalare ripetuto | `un solo valore` |

I percorsi dei campi annidati usano `.` e `[i]`: `righe[2].quantita`.

### Errori

```json
{"error": {"code": "INVALID_REQUEST", "message": "Richiesta non valida", "correlationId": "…", "fields": {"nome": "obbligatorio"}}}
```

`fields` compare solo per gli errori 400, 409 e 422. Il messaggio è sempre generico: i dettagli degli errori inattesi finiscono nel log con il correlationId, mai nella risposta.

| Causa | Stato | `code` |
|---|---|---|
| richiesta non conforme al contratto | 400 | `INVALID_REQUEST` |
| `limit`, `sort` o `cursor` rifiutati dal modello | 400 | `INVALID_PAGE` |
| identità assente | 401 | `IDENTITY_REQUIRED` |
| scope mancanti | 403 | `SCOPE_REQUIRED` |
| tenant assente o non valido | 403 | `TENANT_REQUIRED` |
| percorso o record inesistente | 404 | `ROUTE_NOT_FOUND`, `RECORD_NOT_FOUND` |
| metodo non ammesso | 405 | `METHOD_NOT_ALLOWED` |
| eliminazione con record collegati | 409 | `RELATED_RECORDS` |
| vincolo del database (unicità, chiave esterna) | 409 | `CONSTRAINT` |
| chiave duplicata in MongoDB | 409 | `DUPLICATE` |
| corpo non JSON | 415 | `JSON_REQUIRED` |
| regola del modello (`ModelValidationError`) | 422 | `MODEL_RULE` |
| conflitto di serializzazione o deadlock dopo i tentativi | 503 | `RETRY_LATER` |
| qualsiasi altro errore | 500 | `UNEXPECTED` |

## Identità: solo dal gateway

Il servizio **non verifica token**: li verifica API Gateway (authorizer JWT o Lambda). Il nucleo legge i claim già verificati:
- **Lambda**: da `requestContext.authorizer` (`jwt.claims` per HTTP API, `lambda` per gli authorizer Lambda, `claims` per REST API, anche come stringa JSON);
- **Kubernetes** (server HTTP o framework): dagli header impostati dal gateway, `x-kybes-subject`, `x-kybes-tenant`, `x-kybes-scopes`.

Il servizio dietro il gateway deve essere raggiungibile solo dal gateway (rete privata, VPC link), e il gateway deve sovrascrivere gli header di identità a ogni richiesta: un header inviato dal client non deve mai arrivare al servizio.

Lo scope si legge da una lista o da un testo (`"a b"`, `"a,b"`, `"[a b]"`). Le operazioni sono protette quando il contratto ha una `security` globale (lo scaffold la include); senza, sono pubbliche.

Nomi di claim e header si configurano in `kybes.config.json`:

```json
"api": {
  "contract": "schemas/openapi.yaml",
  "generated_contract": "schemas/generated/openapi.yaml",
  "claims": { "subject": "sub", "tenant": "tid", "scopes": ["scp", "roles"] },
  "headers": { "subject": "x-kybes-subject", "tenant": "x-kybes-tenant", "scopes": "x-kybes-scopes" },
  "base_path": ""
}
```

Il tenant dell'identità viene legato alla sessione del modello a ogni operazione: le tabelle con [tenancy](multi-tenant.md) leggono e scrivono solo i dati di quel tenant; senza tenant rispondono 403.

## Accesso ai dati

I controller generati usano `ApiData`, che sa come aprire le sessioni:
- letture con il tenant legato;
- scritture nella [Unit of Work](transazioni.md) (isolamento e retry della tabella) o in una transazione MongoDB.

| Linguaggio | Tabelle SQL | Collection MongoDB |
|---|---|---|
| Python | `ApiData(session_factory=...)` o `sql_for=lambda tenant: ...` | `mongo_client=..., mongo_database=...` o `mongo_database_for=` |
| TypeScript | `new ApiData({ dataSource })` o `sqlFor` | `mongoClient`, `mongoDatabase` o `mongoDatabaseFor` |
| Java | `new ApiData().emf(emf)` o `.sqlFor(tenant -> emf)` | `.mongo(client, database)`, `.mongoDatabaseFor(...)` |
| C# | `new ApiData { SqlFor = tenant => new AppDbContext(options) }` | `MongoClient`, `MongoDatabase`, `MongoDatabaseFor` |

`sql_for` e `mongo_database_for` servono alle tabelle con tenancy `schema` o `database`. In Python e TypeScript `ApiData` accetta anche `levels`, i livelli di isolamento passati alla Unit of Work (ad esempio con SQLite, che conosce solo `SERIALIZABLE`).

## Runtime: Lambda, server HTTP, framework

Lo stesso `Api` gira in tre modi. Il nucleo non cambia: cambiano solo la lettura della richiesta e la scrittura della risposta.

| Linguaggio | AWS Lambda | Server senza framework | Framework |
|---|---|---|---|
| Python | `lambda_handler(api)` | ASGI: `asgi_app(api)` (uvicorn) | FastAPI: `include_api(app, api)` |
| TypeScript | `lambdaHandler(api)` | `node:http`: `createServer(httpHandler(api))` | Fastify: `includeApi(fastify(), api)` |
| Java | `LambdaAdapter.handle(api, event)` (handler POJO a `Map`) | server del JDK: `HttpServerAdapter.handler(api)` | Spring Boot: `@Bean RouterFunction<ServerResponse> SpringAdapter.routes(api)` |
| C# | `LambdaAdapter.HandleAsync(api, stream)` (handler a stream) | — (in .NET il server HTTP è già ASP.NET Core) | ASP.NET Core minimal API: `app.MapKybesApi(api)` |

In tutti gli adattatori un percorso sconosciuto riceve il 404 `ROUTE_NOT_FOUND` del nucleo, con correlationId, e non la pagina di errore del framework.

Gli adattatori Lambda accettano gli eventi di API Gateway HTTP API (v2) e REST API (v1), con corpo anche in base64. Fastify, FastAPI e Spring sono dipendenze facoltative: servono solo a chi usa quell'adattatore.

```typescript
// microservizio su Kubernetes con il solo contesto "vendite"
const api = buildApi(new ApiData({ dataSource }), vendite, ["vendite"]);
createServer(httpHandler(api)).listen(8080);

// function Lambda
export const handler = lambdaHandler(buildApi(new ApiData({ dataSource }), vendite));
```

### Contesti

`build_api(data, custom, contexts)` (o `buildApi`, `KybesApi.build`, `KybesApi.Build`) costruisce l'`Api` con le operazioni dei soli contesti indicati: un microservizio o una function espone il proprio contesto, il gateway instrada per percorso. Senza contesti si ottengono tutte le operazioni. I metodi custom servono solo per i contesti scelti.

## Test generati (ISO 26262-6)

I casi di test delle API entrano nel catalogo di verifica con scope `api`, con requisiti, metodi di derivazione e tracciabilità come quelli del modello ([verifica](verifica.md)).

| Gruppo | Casi |
|---|---|
| per tabella | lista con `limit`, parametri non validi e sconosciuti, lettura (esistente, inesistente, chiave non valida), creazione (valida, campo obbligatorio mancante, campo in più, tipo errato, duplicato), modifica (campo, corpo vuoto, inesistente, chiave nel corpo), eliminazione, query e relazioni, identità assente, scope mancanti, tenant assente o di un altro tenant |
| endpoint custom | chiamata valida con input generato dallo schema, parametro obbligatorio mancante |
| nucleo | validatore, conversione dei parametri, routing, corpo e JSON, traduzione degli errori, identità, ApiData, adattatori Lambda, server HTTP e framework, conversioni |

I test girano sugli stessi database dei test del modello (PostgreSQL, MongoDB con replica set) e `verify.py` applica le soglie di copertura per ASIL anche al codice API: i controller hanno l'ASIL della tabella, i moduli comuni l'ASIL più alto del progetto.

## Limiti

- Niente verifica dei token nel servizio: è compito del gateway.
- Il validatore copre il sottoinsieme indicato sopra; `oneOf`, `anyOf`, `allOf` e gli schemi ricorsivi non sono ammessi nel contratto.
- Parametri solo in path e query; header e cookie restano al gateway.
- Le operazioni CRUD lavorano su un record alla volta; operazioni di massa e transazioni su più tabelle si scrivono come endpoint custom, con la Unit of Work del modello.
