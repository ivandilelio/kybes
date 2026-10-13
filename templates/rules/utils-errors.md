---
paths:
  - "libs/utils/**"
  - "libs/errors/**"
---

# Regole per Utils ed Errors

## libs/utils
- Solo funzioni pure di trasformazione dati, riusate in almeno due punti.
- Niente DB, rete, SDK cloud, variabili d'ambiente; nessuna dipendenza da DB-Models.

## libs/errors
- Classi minime: VALIDATION, AUTH, NOT_FOUND, CONFLICT, TRANSIENT, INTERNAL.
- Ogni errore verso l'esterno: codice applicativo, messaggio generico, `correlationId`. Il dettaglio va solo nei log.
- TRANSIENT attiva l'accodamento per il riprocessamento; le operazioni multi-step fanno rollback o compensazione.
- Il middleware di validazione vive qui ed è lo stesso per function e microservizi.
