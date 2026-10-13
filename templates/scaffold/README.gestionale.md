# Struttura del progetto

| Cartella | Contenuto |
|---|---|
| `infra/` | IaC (Terraform o CDK): API Gateway, Lambda, EKS, KEDA, CDN, segreti |
| `schemas/` | OpenAPI + JSON Schema, sorgente di verità per validazione e modelli |
| `libs/db-models/python` | DB-Models per le function |
| `libs/db-models/typescript` | DB-Models per i microservizi |
| `libs/utils/` | funzioni pure condivise |
| `libs/errors/` | modulo errori e middleware di validazione |
| `services/<contesto>/functions` | Lambda del bounded context |
| `services/<contesto>/ms` | microservizio Kubernetes del bounded context |
| `jobs/<nome>` | Job KEDA / cron |
| `frontend/` | SPA statica servita da CDN |
| `tools/claude-gestionale/` | kit di regole e controlli (gestito dall'installer) |

I controlli architetturali girano in automatico durante il lavoro di Claude e in CI:

```
python3 tools/claude-gestionale/plugins/gestionale-cloud/scripts/arch_check.py .
```
