---
paths:
  - "services/*/ms/**"
---

# Regole per i microservizi Kubernetes

- Solo per carichi oltre 10 s, asincroni di lunga durata, WebSocket/streaming o connessioni persistenti.
- Espongono un solo bounded context verso l'API Gateway (VPC link / ingress); niente accesso generico al DB.
- Accesso ai dati solo tramite DB-Models nella versione pinnata.
- Endpoint `/health` e `/ready`, shutdown graceful su SIGTERM.
- Deployment con resource requests/limits, HPA, PodDisruptionBudget.
- Log JSON con `correlationId` letto dall'header in ingresso e propagato nelle chiamate in uscita.
- Stesso middleware di validazione e stesso modulo errori delle function.
