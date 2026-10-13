---
paths:
  - "jobs/**"
---

# Regole per i Job

- Tutto ciò che parte da schedule, coda o evento, o è batch, è un Job.
- Job su evento/coda: `ScaledJob` KEDA con lo scaler della sorgente, scale-to-zero.
- Job a calendario: trigger cron KEDA o `CronJob`.
- Ogni Job è idempotente, ha timeout esplicito, retry limitati e dead-letter queue.
- Per gli eventi in uscita usa il pattern outbox tramite DB-Models.
- Resource requests/limits obbligatori.
