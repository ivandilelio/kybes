---
paths:
  - "services/*/functions/**"
---

# Regole per le function (Lambda)

- Solo endpoint sincroni, stateless, che terminano entro 10 s. Se no: microservizio K8s o Job.
- Un handler = un'operazione del bounded context della cartella. Nessun import da altri `services/*`.
- Struttura dell'handler: middleware di validazione → chiamata a DB-Models / evento → risposta. Niente logica di persistenza nell'handler.
- Connessioni DB tramite il pool/proxy fornito da DB-Models, inizializzato fuori dall'handler.
- Scritture idempotenti con `Idempotency-Key` **legata all'identità** (`(subject, key)` o `(tenant, key)`): mai lookup solo per chiave.
- Errori: solo `libs/errors`, che produce codice + messaggio generico + `correlationId`.
- Configurazione e segreti da variabili d'ambiente iniettate dall'IaC o da Secrets Manager.
