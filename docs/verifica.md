# Verifica di unità (ISO 26262-6)

kybes genera nei progetti i test di unità del modello dati, li esegue e controlla la copertura strutturale contro le soglie dell'ASIL di ogni tabella. Sono requisiti del software prodotto con kybes, non del plugin.

## Cosa viene generato

Dallo schema `schemas/db/<T>.yaml` il generatore ricava requisiti e casi di test, poi li scrive come test eseguibili e come documentazione.

| Prodotto | Percorso | Di chi |
|---|---|---|
| requisiti di ogni tabella e dei moduli comuni | `docs/generated/verification/requirements.md` | generato |
| specifica dei test di una tabella | `docs/generated/verification/<T>.md` | generato |
| specifica dei test dei moduli comuni (paginazione, Unit of Work, archivio, API) | `docs/generated/verification/kybes-runtime.md` | generato |
| specifica dei test del motore dei job (archivio e conservazione) | `docs/generated/verification/kybes-jobs.md` | generato |
| matrice requisito → test → file | `docs/generated/verification/traceability.md` | generato |
| soglie di copertura per ASIL e limiti noti | `docs/generated/verification/coverage.md` | generato |
| test Python (pytest) | `libs/db-models/python/tests/generated/` | generato |
| test TypeScript (node:test) | `libs/db-models/typescript/tests/generated/` | generato |
| test Java (JUnit 5, Hibernate) | `libs/db-models/java/src/test/java/<package>/generated/` | generato |
| test C# (xUnit, EF Core) | `libs/db-models/csharp/tests/generated/` | generato |
| test del motore dei job e dei job di ogni tabella (pytest) | `jobs/generated/_engine/tests/` | generato |
| test dei metodi custom | `libs/db-models/<lingua>/tests/custom/` (Java: `src/test/java/<package>/custom/`) | tuo |
| report di copertura | `coverage/<lingua>.cobertura.xml`, `coverage/java.jacoco.xml`, `coverage/jobs.cobertura.xml` | prodotto da `verify.py` |

I quattro linguaggi rendono lo stesso catalogo: stessi identificativi, stessi casi, adattati all'API del linguaggio. Per esempio, l'aggiornamento di un record inesistente in Python e TypeScript non restituisce nulla, in Java e C# solleva un errore «record inesistente»; la specifica di ogni caso lo dice.

## Identificativi

| Elemento | Formato | Esempio |
|---|---|---|
| requisito di tabella | `REQ-<Tabella>-<CHIAVE>` | `REQ-Clienti-Email-UNIQUE` |
| requisito dei moduli comuni | `REQ-KYBES-<CHIAVE>` | `REQ-KYBES-UOW-RETRY` |
| caso di test | `TC-<Tabella>-<CASO>` | `TC-Ordini-Q-ApertiDelCliente-MCDC-2` |

Ogni test generato porta l'identificativo nel nome (Python), nel titolo (TypeScript), in `@DisplayName` (Java) o in `DisplayName` di `[Fact]` (C#), insieme ai requisiti che verifica e al metodo con cui è stato derivato. Gli identificativi sono stabili: dipendono dai nomi nello schema, non dall'ordine.

## Metodi di derivazione

ISO 26262-6, tabella 8, elenca i metodi per derivare i casi di test di unità. kybes li applica così:

| Metodo | Sigla | Casi generati |
|---|---|---|
| analisi dei requisiti | `req` | lettura, aggiornamento, cancellazione, relazioni, ricerca per colonna univoca, scorrimento delle pagine, query |
| classi di equivalenza | `eq` | inserimento valido, campo obbligatorio assente, chiave non modificabile, ordinamento non ammesso, record fuori dalla classe di una query |
| valori limite | `bv` | lunghezza massima e massima + 1, limite di pagina 0, massimo e massimo + 1, elenco vuoto in una condizione `in` |
| stima degli errori | `eg` | record inesistente, valore duplicato, cursore manomesso, errori non ritentabili |
| MC/DC | `mcdc` | per le tabelle ASIL C e D: ogni condizione di ogni query viene resa falsa da sola, e il record deve uscire dal risultato |

Ogni test di query costruisce anche un record fuori dalla classe (le condizioni a valore fisso e quelle su `null` invertite): una query che perde una condizione restituisce quel record e il test fallisce, a qualsiasi ASIL.

## Multi-tenant

Le tabelle con `tenancy` diversa da `none` hanno il requisito `REQ-<Tabella>-TENANT` e i casi di isolamento (tenant obbligatorio, isolamento tra tenant, assegnazione del tenant, univocità per tenant, padre di un altro tenant): l'elenco è in [multi-tenant](multi-tenant.md). La sessione dei test generati è legata al tenant di prova `TENANT_A`, definito nei builder.

## Archivio e conservazione

Le tabelle con `archive` o `retention` hanno i requisiti `REQ-<Tabella>-ARCHIVE`, `REQ-<Tabella>-RETENTION` e, con `read_through`, `REQ-<Tabella>-ARCHIVE-READ`. I casi di lettura dall'archivio (`TC-<Tabella>-ARCHIVE-READ`, `-READ-MISS`, `-HOT-FIRST`, `-READ-TENANT`) stanno nei test del modello dei quattro linguaggi; quelli del job (`TC-<Tabella>-JOB-*`) e del motore (`TC-KYBES-JOB-*`, requisiti `REQ-KYBES-JOB-*`) in `jobs/generated/_engine/tests/`. L'elenco è in [archivio](archivio.md#test-generati).

## Soglie di copertura

| ASIL | Statement | Branch | MC/DC |
|---|---|---|---|
| QM | — | — | — |
| A | 90% | — | — |
| B | 95% | 90% | — |
| C | 100% | 95% | casi generati |
| D | 100% | 100% | casi generati |

Le soglie sono una politica del progetto ispirata a ISO 26262-6, tabella 9, e si cambiano in `verification.thresholds`. L'ASIL di un file del modello è quello della sua tabella. I moduli comuni (`_paging`, `_uow`, `_tenant`, `_archive`, `_base`, l'indice) e il motore dei job prendono l'ASIL più alto del progetto.

Gli strumenti di copertura diffusi (coverage.py, c8, coverlet, JaCoCo) non misurano la MC/DC. Per ASIL C e D la MC/DC è ottenuta dal disegno dei test: per ogni condizione c'è un caso che la rende determinante. `coverage.md` lo dichiara, perché l'auditor lo deve sapere.

## Metodi custom

I metodi generati hanno i test generati. Quelli scritti a mano in `model/<T>` richiedono test scritti a mano in `tests/custom/`, con gli stessi identificativi. La regola `custom_tests` (livello `block`) ferma la chiusura del lavoro e la CI se un metodo custom non compare in un file di `tests/custom/` che contenga anche un identificativo `TC-<Tabella>-`.

Python: le fixture dei test generati (`session`, `session_factory`, `engine`, `isolation_levels`) e i builder sono disponibili anche in `tests/custom/` grazie a `tests/custom/conftest.py`, creato una volta dal generatore.

```python
"""TC-Clienti-CONTA-ATTIVI · REQ-Clienti-CONTA · analisi dei requisiti: conteggio dei clienti attivi"""
from kybes_builders import build_clienti
from model.Clienti import ClientiRepository


def test_conta_attivi(session):
    build_clienti(session, attivo=True)
    build_clienti(session, attivo=False)
    assert ClientiRepository(session).conta_attivi() == 1
```

TypeScript: si importano `withDb` e i builder dalla cartella dei test generati.

```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { ClientiRepository } from "../../src/model/Clienti";
import { withDb } from "../generated/_db";
import { buildClienti } from "../generated/kybes_builders";

test("TC-Clienti-CONTA-ATTIVI · REQ-Clienti-CONTA · analisi dei requisiti: conteggio dei clienti attivi", () =>
  withDb(async (em) => {
    await buildClienti(em, { attivo: true });
    await buildClienti(em, { attivo: false });
    assert.equal(await new ClientiRepository(em).contaAttivi(), 1);
  }));
```

Java: `KybesDb.open()` dà un `EntityManager` con le tabelle vuote e una transazione annullata alla fine; i builder sono in `KybesBuilders`.

```java
package app.model.custom;

import static app.model.generated.KybesBuilders.*;
import static org.junit.jupiter.api.Assertions.assertEquals;

import app.model.ClientiRepository;
import app.model.generated.KybesDb;
import jakarta.persistence.EntityManager;
import org.junit.jupiter.api.*;

class ClientiCustomTest {
    private EntityManager em;

    @BeforeEach void open() { em = KybesDb.open(); }
    @AfterEach void close() { KybesDb.close(em); }

    @Test
    @DisplayName("TC-Clienti-CONTA-ATTIVI · REQ-Clienti-CONTA · analisi dei requisiti: conteggio dei clienti attivi")
    void contaAttivi() {
        buildClienti(em, x -> x.setAttivo(true));
        buildClienti(em, x -> x.setAttivo(false));
        assertEquals(1, new ClientiRepository(em).contaAttivi());
    }
}
```

C#: `KybesDb.Open()` dà un contesto con le tabelle vuote; i builder sono in `KybesBuilders`.

```csharp
using App.Model;
using App.Model.Tests;
using Xunit;
using static App.Model.Tests.KybesBuilders;

public sealed class ClientiCustomTests : IDisposable
{
    private readonly AppDbContext db = KybesDb.Open();
    public void Dispose() => db.Dispose();

    [Fact(DisplayName = "TC-Clienti-CONTA-ATTIVI · REQ-Clienti-CONTA · analisi dei requisiti: conteggio dei clienti attivi")]
    public async Task ContaAttivi()
    {
        await BuildClienti(db, x => x.Attivo = true);
        await BuildClienti(db, x => x.Attivo = false);
        Assert.Equal(1, await new ClientiRepository(db).ContaAttiviAsync());
    }
}
```

Il requisito di un metodo custom si scrive nel commento del metodo con lo stesso formato (`REQ-<Tabella>-<CHIAVE>`), così la tabella e il codice restano collegati.

## Esecuzione

```bash
python3 -B tools/kybes/plugins/kybes/scripts/verify.py .                    # tutti i linguaggi
python3 -B tools/kybes/plugins/kybes/scripts/verify.py . --lang=python      # uno solo
python3 -B tools/kybes/plugins/kybes/scripts/verify.py . --lang=jobs        # solo il motore dei job
python3 -B tools/kybes/plugins/kybes/scripts/verify.py . --gate-only        # solo soglie, su report esistenti
```

| Linguaggio | Esegue | Serve |
|---|---|---|
| Python | `pytest` con `pytest-cov` nella cartella del pacchetto | `pip install -e "libs/db-models/python[test]"` (con `[test,postgres]` per PostgreSQL) |
| TypeScript | `tsc`, poi `c8` con `node --test`, un file alla volta | `npm install` in `libs/db-models/typescript` (tsconfig con `sourceMap: true`) |
| Java | `mvn test` con JaCoCo | Maven, `libs/db-models/java/pom.xml`, PostgreSQL |
| C# | `dotnet test` con coverlet | .NET 8 SDK, `libs/db-models/csharp/tests/*.csproj`, PostgreSQL |
| motore dei job | `pytest` con `pytest-cov` in `jobs/generated/_engine` | `pip install -e "jobs/generated/_engine[test]"` (SQLite, oppure PostgreSQL con `KYBES_TEST_DATABASE_URL`) |

L'installer con `--scaffold` crea i file dei pacchetti (`pyproject.toml`, `package.json` e `tsconfig.json`, `pom.xml`, i due `.csproj`) per i linguaggi del modello.

Il database dei test è `KYBES_TEST_DATABASE_URL`, nello stesso formato per tutti i linguaggi: `postgresql://utente:password@host:5432/database`. Java e C# lo richiedono: lo schema viene creato da Hibernate o da EF Core e le tabelle svuotate prima di ogni test. Python e TypeScript, se la variabile manca, usano SQLite in memoria e sql.js (dialetto `sqlite`). In locale basta un container:

```bash
docker run -d --name kybes-pg -e POSTGRES_USER=kybes -e POSTGRES_PASSWORD=kybes -e POSTGRES_DB=kybes -p 5432:5432 postgres:16
export KYBES_TEST_DATABASE_URL=postgresql://kybes:kybes@localhost:5432/kybes
```

Quando una soglia non è raggiunta, `verify.py` indica il file, la soglia dell'ASIL e le righe non eseguite o con rami non percorsi: si aggiunge il test che le esercita.

`verify.py` esce con 1 se un test fallisce o una soglia non è raggiunta. Un linguaggio senza strumenti installati viene segnalato e saltato. L'installer lo mette in `stop_gate.commands`, quindi Claude non chiude un lavoro con test rotti o copertura insufficiente. Lo aggiunge anche al workflow di CI, che conserva report e specifiche come artefatto `verification-evidence`.

## Limiti

- La conformità a ISO 26262 riguarda il processo dell'organizzazione: safety plan, analisi dei rischi, revisioni indipendenti. kybes produce le evidenze della verifica di unità, non la certificazione.
- Generatore, verify.py e strumenti di copertura vanno qualificati secondo ISO 26262-8, clausola 11, se le loro uscite sostituiscono una verifica manuale.
- La copertura MC/DC non è misurata da uno strumento: è garantita dal disegno dei casi.
