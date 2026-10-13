---
paths:
  - "frontend/**"
  - "infra/**"
---

# Regole per frontend e infrastruttura

## frontend
- SPA buildata in file statici, servita da CDN (S3 + CloudFront, origin privato).
- Login SSO aziendale con OIDC Authorization Code + PKCE; nessun segreto nel bundle.
- Asset con hash e cache lunga, `index.html` senza cache.

## infra
- Ogni risorsa in IaC. API Gateway con authorizer JWT e validazione richieste da `schemas/`.
- Lambda: timeout massimo 10 s per gli endpoint sincroni, accesso DB tramite RDS Proxy.
- EKS: autoscaling dei nodi (Karpenter o Cluster Autoscaler) e KEDA installato.
- Segreti in Secrets Manager / Parameter Store, mai valori in chiaro nei file.
