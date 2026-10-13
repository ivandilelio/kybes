# Query e indici

L'accesso ai dati abituale si dichiara nello schema, non si scrive a mano. Il generatore produce il metodo in tutti i linguaggi e garantisce che un indice lo copra.

## Dichiarare una query

```yaml
queries:
  - name: ApertiDelCliente
    where:
      - ClienteId                                # = parametro clienteId
      - { column: Stato, op: eq, value: aperto } # costante, non diventa un parametro
    order_by: [{ column: Data, dir: desc }]
  - name: PerNumero
    where:
      - { column: Numero, op: prefix, param: Prefisso }
    order_by: [Numero]
  - name: UltimoDelCliente
    where: [ClienteId]
    order_by: [{ column: Data, dir: desc }]
    returns: one
```

| `returns` | Metodo | Risultato |
|---|---|---|
| `page` (default) | `list<Nome>` (C# `List<Nome>Async`, Python `list_<nome>`) | pagina a cursore con ordinamento fisso |
| `list` | `list<Nome>` | elenco limitato a `max_limit` righe, per insiemi piccoli |
| `one` | `find<Nome>` | primo record secondo `order_by`, oppure nessuno |

Operatori ammessi in `where`:

| Operatore | Significato |
|---|---|
| `eq`, `ne` | uguale, diverso |
| `lt`, `lte`, `gt`, `gte` | confronti |
| `in` | il parametro è un elenco; con elenco vuoto il risultato è vuoto senza interrogare il database |
| `prefix` | `LIKE 'valore%'`, con `%`, `_` e `\` protetti |
| `is_null`, `not_null` | solo su colonne non obbligatorie |

Se una query ha lo stesso nome di un metodo generato (es. `List<Relazione>`, `ListBy<Fk>`) lo schema viene rifiutato.

## Quando scrivere un metodo custom

Solo quando la query non si esprime con condizioni in `AND` sulla tabella stessa: join con altre tabelle, aggregazioni, `OR` complessi, ricerche full-text. Il metodo va nel file `model/<Tabella>` e l'indice va dichiarato a mano in `indexes`.

## Come il generatore sceglie gli indici

Per ogni percorso di accesso calcola l'**indice ideale**: prima le colonne in uguaglianza, poi quelle di ordinamento o di intervallo. I percorsi considerati sono:
- ricerca per colonna univoca;
- lista per chiave esterna;
- ogni ordinamento ammesso;
- ogni query dichiarata.

| Caso | Indice ideale |
|---|---|
| `listByClienteId` con ordine predefinito `Data desc` | `(ClienteId, Data)` |
| query `ClienteId = ? AND Stato = 'aperto' ORDER BY Data DESC` | `(ClienteId, Stato, Data)` |
| ordinamento per `Totale` | `(Totale)` |
| `Numero LIKE 'x%'` su PostgreSQL | `(Numero varchar_pattern_ops)` |

Un indice esistente copre il percorso se inizia con tutte le colonne di uguaglianza, in qualunque ordine, e prosegue con quelle di ordinamento. Se c'è viene riusato, altrimenti viene creato con un nome deterministico. Gli indici di cui un altro indice è un prefisso vengono segnalati come probabilmente superflui.

L'esito è in `db/generated/indexes.md`: una tabella per ogni tabella del modello con accesso, colonne ideali, indice usato e se è stato creato.

Gli indici con operator class per `LIKE` (`px_...`) esistono solo nel DDL. Gli ORM non sanno dichiararli, e su una collation `C` non servono.

## DDL

`db/generated/ddl/postgres/_all.sql` è lo schema completo per PostgreSQL 13+, nell'ordine: tabelle, chiavi esterne, indici. È validato dal parser di PostgreSQL nella suite del kit. I file per tabella servono per la revisione.

È la base consigliata per le migrazioni: confrontalo con lo schema di produzione (ad esempio con `migra` o con lo strumento di migrazione del tuo stack) invece di affidarti alla sincronizzazione automatica degli ORM.
