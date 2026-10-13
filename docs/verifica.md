# Verifica di unità (ISO 26262-6)

kybes genera nei progetti i test di unità del modello dati, li esegue e controlla la copertura strutturale contro le soglie dell'ASIL di ogni tabella. Sono requisiti del software prodotto con kybes, non del plugin.

## Cosa viene generato

Dallo schema `schemas/db/<T>.yaml` il generatore ricava requisiti e casi di test, poi li scrive come test eseguibili e come documentazione.

| Prodotto | Percorso | Di chi |
|---|---|---|
| requisiti di ogni tabella e dei moduli comuni | `docs/generated/verification/requirements.md` | generato |
| specifica dei test di una tabella | `docs/generated/verification/<T>.md` | generato |
| specifica dei test dei moduli comuni (paginazione, Unit of Work, API) | `docs/generated/verification/kybes-runtime.md` | generato |
| matrice requisito → test → file | `docs/generated/verification/traceability.md` | generato |
| soglie di copertura per ASIL e limiti noti | `docs/generated/verification/coverage.md` | generato |
| test Python (pytest) | `libs/db-models/python/tests/generated/` | generato |
| test TypeScript (node:test) | `libs/db-models/typescript/tests/generated/` | generato |
| test dei metodi custom | `libs/db-models/<lingua>/tests/custom/` | tuo |
| report di copertura (Cobertura) | `coverage/<lingua>.cobertura.xml` | prodotto da `verify.py` |

I test Java (JUnit 5) e C# (xUnit) seguiranno lo stesso catalogo. Oggi, per quei linguaggi, `verify.py --gate-only` controlla le soglie su report Cobertura prodotti dalla CI (coverlet per C#, JaCoCo convertito per Java).

## Identificativi

| Elemento | Formato | Esempio |
|---|---|---|
| requisito di tabella | `REQ-<Tabella>-<CHIAVE>` | `REQ-Clienti-Email-UNIQUE` |
| requisito dei moduli comuni | `REQ-KYBES-<CHIAVE>` | `REQ-KYBES-UOW-RETRY` |
| caso di test | `TC-<Tabella>-<CASO>` | `TC-Ordini-Q-ApertiDelCliente-MCDC-2` |

Ogni test generato porta l'identificativo nel nome (Python), o nel titolo e nel docstring (TypeScript), insieme ai requisiti che verifica e al metodo con cui è stato derivato. Gli identificativi sono stabili: dipendono dai nomi nello schema, non dall'ordine.

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

## Soglie di copertura

| ASIL | Statement | Branch | MC/DC |
|---|---|---|---|
| QM | — | — | — |
| A | 90% | — | — |
| B | 95% | 90% | — |
| C | 100% | 95% | casi generati |
| D | 100% | 100% | casi generati |

Le soglie sono una politica del progetto ispirata a ISO 26262-6, tabella 9, e si cambiano in `verification.thresholds`. L'ASIL di un file del modello è quello della sua tabella. I moduli comuni (`_paging`, `_uow`, `_base`, l'indice) prendono l'ASIL più alto del progetto.

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

Il requisito di un metodo custom si scrive nel commento del metodo con lo stesso formato (`REQ-<Tabella>-<CHIAVE>`), così la tabella e il codice restano collegati.

## Esecuzione

```bash
python3 -B tools/kybes/plugins/kybes/scripts/verify.py .                    # tutti i linguaggi
python3 -B tools/kybes/plugins/kybes/scripts/verify.py . --lang=python      # uno solo
python3 -B tools/kybes/plugins/kybes/scripts/verify.py . --gate-only        # solo soglie, su report esistenti
```

| Linguaggio | Esegue | Serve |
|---|---|---|
| Python | `pytest` con `pytest-cov` nella cartella del pacchetto | `pip install -e "libs/db-models/python[test]"` |
| TypeScript | `tsc`, poi `c8` con `node --test` | `npm install` in `libs/db-models/typescript` (tsconfig con `sourceMap: true`) |

I test girano su SQLite in memoria (Python) o su sql.js (TypeScript, dialetto `sqlite`). Con `KYBES_TEST_DATABASE_URL` girano sul database indicato, per esempio un PostgreSQL di CI.

`verify.py` esce con 1 se un test fallisce o una soglia non è raggiunta. Un linguaggio senza strumenti installati viene segnalato e saltato. L'installer lo mette in `stop_gate.commands`, quindi Claude non chiude un lavoro con test rotti o copertura insufficiente. Lo aggiunge anche al workflow di CI, che conserva report e specifiche come artefatto `verification-evidence`.

## Limiti

- La conformità a ISO 26262 riguarda il processo dell'organizzazione: safety plan, analisi dei rischi, revisioni indipendenti. kybes produce le evidenze della verifica di unità, non la certificazione.
- Generatore, verify.py e strumenti di copertura vanno qualificati secondo ISO 26262-8, clausola 11, se le loro uscite sostituiscono una verifica manuale.
- La copertura MC/DC non è misurata da uno strumento: è garantita dal disegno dei casi.
