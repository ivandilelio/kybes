# Struttura del progetto

| Cartella | Contenuto |
|---|---|
| `infra/` | IaC (Terraform o CDK): API Gateway, Lambda, EKS, KEDA, CDN, segreti |
| `schemas/` | OpenAPI + JSON Schema, sorgente di verità per validazione e modelli |
| `libs/db-models/<lingua>/src/model` | DB-Models: un file per tabella, codice generato in `generated/` |
| `libs/db-models/<lingua>/tests/generated` | test di unità generati dagli schemi (ISO 26262-6), da non modificare |
| `libs/db-models/<lingua>/tests/custom` | test dei metodi custom, scritti a mano con id `TC-<Tabella>-<CASO>` |
| `docs/generated/verification` | requisiti, specifiche dei test, tracciabilità, soglie di copertura |
| `libs/utils/` | funzioni pure condivise |
| `libs/errors/` | modulo errori e middleware di validazione |
| `services/<contesto>/functions` | Lambda del bounded context |
| `services/<contesto>/ms` | microservizio Kubernetes del bounded context |
| `jobs/<nome>` | Job KEDA / cron |
| `frontend/` | SPA statica servita da CDN |
| `tools/kybes/` | kit di regole e controlli (gestito dall'installer) |

I controlli architetturali girano in automatico durante il lavoro di Claude e in CI:

```
python3 tools/kybes/plugins/kybes/scripts/arch_check.py .
```

Test di unità del modello e copertura per ASIL (gli stessi controlli girano a fine lavoro e in CI):

```
python3 -B tools/kybes/plugins/kybes/scripts/verify.py .
```
