# Paginazione

Tutte le liste di kybes sono paginate a cursore (keyset), con lo stesso contratto dalla UI al database:
- `list_page`;
- `list_by_<fk>`;
- i figli di una relazione;
- le query dichiarate con `returns: page`.

## Perché a cursore e non con OFFSET

| | OFFSET / LIMIT | Cursore (keyset) |
|---|---|---|
| Costo della pagina 10.000 | il database legge e scarta 10.000 × limite righe | uguale alla prima pagina: parte da un indice |
| Inserimenti durante la navigazione | righe saltate o ripetute | nessun salto, nessun duplicato |
| Indice usato | spesso no, oltre le prime pagine | sì, sempre (lo garantisce il generatore) |
| Salto a pagina N | possibile | non previsto: si va avanti con il cursore |

Se una UI ha davvero bisogno del numero totale, lo chiede a parte con `count`, che è un metodo generato.

## Il contratto

**Richiesta**, come parametri di query dell'API:

| Parametro | Esempio | Regole |
|---|---|---|
| `limit` | `50` | da 1 a `pagination.max_limit` della tabella; se manca vale `default_limit` |
| `cursor` | `eyJzIjoiLWRhdGEsaWQi…` | il `nextCursor` della pagina precedente; assente per la prima pagina |
| `sort` | `-data,numero` | solo colonne in `pagination.sortable` (nomi JSON); `-` davanti per l'ordine discendente |

**Risposta**:

```json
{ "items": [ ... ], "nextCursor": "eyJzIjoiLWRhdGEsaWQi…", "limit": 50 }
```

`nextCursor` è `null` all'ultima pagina. Il contratto è anche in `schemas/generated/json/_page.schema.json`, da usare nella validazione di API Gateway.

**Errori**: un `sort` su una colonna non ammessa, un `limit` fuori intervallo o un cursore manomesso sollevano l'errore di validazione del model con il campo interessato (`sort`, `limit`, `cursor`). L'API lo restituisce come 400.

## Il cursore

Il cursore è opaco per la UI: va solo ripassato com'è. Internamente è il base64url, senza padding, di:

```json
{ "s": "-data,id", "v": ["2026-01-02", "00000000-0000-0000-0000-000000000002"] }
```

- `s` è l'ordinamento con cui è stato prodotto. Un cursore usato con un ordinamento diverso viene rifiutato.
- `v` contiene i valori dell'ultima riga, uno per colonna di ordinamento. Gli `int` sono numeri, tutto il resto stringhe (date in ISO 8601).

Il formato è identico in C#, Python, TypeScript e Java: un cursore prodotto da un servizio è valido per gli altri. La suite del kit lo verifica.

## Ordine stabile

All'ordinamento richiesto viene sempre aggiunta in coda la chiave primaria. È ciò che rende la pagina esatta anche quando molte righe hanno lo stesso valore, ad esempio venti ordini nella stessa data.

Per lo stesso motivo le colonne ordinabili devono essere obbligatorie (`required`): con i valori `NULL` il confronto `(a, b) > (x, y)` non è definito. Il generatore rifiuta colonne ordinabili non obbligatorie, `bool`, `text` e `json`.

## Uso nei linguaggi

```python
page = repo.list_page(PageRequest(limit=50, sort="-data"))
next = repo.list_page(PageRequest(limit=50, sort="-data", cursor=page.next_cursor))
```

```typescript
const page = await repo.listPage({ limit: 50, sort: "-data" });
const next = await repo.listPage({ limit: 50, sort: "-data", cursor: page.nextCursor });
```

```csharp
var page = await repo.ListPageAsync(new PageRequest(Limit: 50, Sort: "-data"));
var next = await repo.ListPageAsync(new PageRequest(50, page.NextCursor, "-data"));
```

```java
Paging.Page<Ordini> page = repo.listPage(new Paging.PageRequest(50, null, "-data"));
Paging.Page<Ordini> next = repo.listPage(new Paging.PageRequest(50, page.nextCursor(), "-data"));
```

## Nella UI

Il contratto si presta a due schemi di interfaccia:

| Schema | Come |
|---|---|
| scorrimento infinito o "carica altri" | si conserva `nextCursor` e lo si invia alla richiesta successiva; si ferma quando è `null` |
| tabella con avanti/indietro | si tiene una pila dei cursori già visti: "avanti" usa `nextCursor`, "indietro" il cursore precedente nella pila |

Cambiare ordinamento o filtri riparte sempre dalla prima pagina, senza cursore. Le colonne su cui la UI può ordinare sono esattamente quelle di `pagination.sortable`: è utile mostrarle come uniche colonne cliccabili.
