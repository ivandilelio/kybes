#!/usr/bin/env bash
# Registra il plugin kybes nel Claude Code di questa macchina.
# Da eseguire una volta dopo aver clonato il repository:  tools/kybes/setup.sh
set -euo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$KIT/../.." && pwd)"
SCOPE="${1:-local}"
command -v claude >/dev/null || { echo "Installa prima Claude Code (comando 'claude')." >&2; exit 1; }
cd "$REPO"
if claude plugin marketplace list 2>/dev/null | grep -q "kybes"; then
  claude plugin marketplace update kybes >/dev/null 2>&1 || true
else
  claude plugin marketplace add "$KIT" --scope "$SCOPE" >/dev/null
fi
claude plugin install kybes@kybes --scope "$SCOPE" >/dev/null 2>&1 \
  || claude plugin update kybes@kybes >/dev/null 2>&1 || true
claude plugin list 2>/dev/null | grep -A3 "kybes@kybes" || { echo "Registrazione non riuscita" >&2; exit 1; }
echo "Plugin kybes attivo per questo repository (scope $SCOPE). Riavvia Claude Code."
