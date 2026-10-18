---
paths:
  - "**"
---

# Regole di sicurezza

## Segreti e configurazione

- Mai hardcodare segreti (API key, JWT secret, password DB, token) nel codice o nei file di configurazione versionati: il hook `hardcoded_secrets` lo blocca.
- Le credenziali vanno in Secrets Manager, Parameter Store o variabili d'ambiente iniettate dall'IaC.
- Se il servizio verifica JWT localmente (es. in sviluppo senza API Gateway), `JWT_SECRET` DEVE essere una variabile d'ambiente di almeno 32 caratteri; l'applicazione **deve rifiutare l'avvio** se manca o è troppo corta. Nessun valore di fallback:
  ```python
  secret = os.environ["JWT_SECRET"]
  if len(secret) < 32:
      raise SystemExit("JWT_SECRET troppo corto (min 32 caratteri)")
  ```
- `docker-compose.yml` usa la sintassi `${VAR:?messaggio}` per le credenziali obbligatorie, mai valori predefiniti in chiaro.

## Hashing delle password (se l'applicazione gestisce credenziali)

- Algoritmo preferito: **Argon2id** (memoria ≥ 19 MiB, iterazioni ≥ 2, parallelismo ≥ 1). Fallback accettabile: PBKDF2 con **minimo 600.000 iterazioni** e HMAC-SHA256 (OWASP 2023).
- Confronto: usare sempre `hmac.compare_digest` o la funzione di verifica della libreria, **mai** `==`.
- Login con utente inesistente: eseguire comunque un hash fittizio (`dummy_hash`) per evitare oracoli di temporizzazione:
  ```python
  user = repo.find_by_email(email)
  if user is None:
      hasher.verify(DUMMY_HASH, password)  # tempo costante
      raise AuthError("INVALID_CREDENTIALS")
  if not hasher.verify(user.password_hash, password):
      raise AuthError("INVALID_CREDENTIALS")
  ```

## Idempotenza

- Le chiavi di idempotenza (`Idempotency-Key`) devono essere sempre **legate all'identità** (subject o tenant): la lookup nel registro delle chiavi filtra per `(identity, key)`, mai solo per `key`. Un utente non deve poter riusare o indovinare la chiave di un altro.

## Docker

- Le porte dei servizi infrastrutturali (PostgreSQL, MongoDB, Redis) si espongono solo su `127.0.0.1` nel docker-compose di sviluppo; il hook `docker_insecure` blocca `0.0.0.0`.
- Il Dockerfile di ogni servizio dichiara un `USER` non-root; il hook `docker_insecure` blocca i Dockerfile senza `USER`.
- Il repository contiene un `.dockerignore` che esclude `.git`, `.env`, `node_modules`, test e documentazione.
