# Transazioni

I metodi del model non aprono né chiudono transazioni. È il service a decidere quali operazioni sono atomiche, con la Unit of Work generata in ogni linguaggio.

## Livello di isolamento

Ogni tabella dichiara il livello con cui va scritta:

```yaml
transactions:
  isolation: serializable    # read_committed (default) | repeatable_read | serializable
```

Quando una Unit of Work scrive su più tabelle, usa il livello più severo tra quelle indicate. La tabella generata `ISOLATION` (una per linguaggio) contiene i livelli di tutte le tabelle.

| Livello | Quando serve |
|---|---|
| `read_committed` | la maggior parte delle tabelle |
| `repeatable_read` | letture ripetute nella stessa transazione che devono restare coerenti |
| `serializable` | regole che dipendono da altre righe: giacenze, numerazioni, saldi |

## Retry

Con `serializable` o in caso di deadlock il database può annullare la transazione (SQLSTATE `40001` e `40P01`). La Unit of Work la ripete da capo, al massimo 3 volte con attesa crescente.

Per questo il lavoro passato alla Unit of Work deve essere ripetibile: niente effetti esterni (email, chiamate ad altri servizi) dentro la transazione. Vanno dopo il commit, o tramite outbox.

## Uso

```python
from model.generated import run_in_transaction

def registra(session):
    ordine = OrdiniRepository(session).create(Ordini(...))
    RigheOrdineRepository(session).create(RigheOrdine(ordine_id=ordine.id, ...))
    return ordine.id

ordine_id = run_in_transaction(SessionFactory, registra, tables=["Ordini", "RigheOrdine"])
```

```typescript
const id = await runInTransaction(dataSource, async (em) => {
  const ordine = await new OrdiniRepository(em).create({ ... });
  await new RigheOrdineRepository(em).create({ ordineId: ordine.id, ... });
  return ordine.id;
}, { tables: ["Ordini", "RigheOrdine"] });
```

```csharp
var id = await UnitOfWork.RunAsync(db, async (ctx, ct) =>
{
    var ordine = await new OrdiniRepository(ctx).CreateAsync(new Ordini { ... }, ct);
    await new RigheOrdineRepository(ctx).CreateAsync(new RigheOrdine { OrdineId = ordine.Id, ... }, ct);
    return ordine.Id;
}, new[] { "Ordini", "RigheOrdine" });
```

```java
UUID id = UnitOfWork.run(emf, em -> {
    Ordini ordine = new OrdiniRepository(em).create(nuovoOrdine);
    ...
    return ordine.getId();
}, List.of("Ordini", "RigheOrdine"));
```

## Note per linguaggio

| Linguaggio | Comportamento |
|---|---|
| Python | `transaction()` per un blocco `with`; `run_in_transaction()` con retry. Con SQLite passa `levels` (SQLite conosce solo `SERIALIZABLE`) |
| TypeScript | usa `dataSource.transaction(livello, ...)`; l'`EntityManager` ricevuto va passato ai repository |
| C# | gira dentro la execution strategy del `DbContext`, quindi funziona anche con `EnableRetryOnFailure`. In quel caso i retry si sommano a quelli della strategy, per cui conviene tenerne uno solo attivo. Al nuovo tentativo il change tracker viene svuotato |
| Java | imposta l'isolamento con `SET TRANSACTION` via JDBC come prima istruzione (PostgreSQL). Con Spring si può usare in alternativa `@Transactional(isolation = ...)` sul service |
