#!/usr/bin/env bash
# Wrapper: l'installer vive dentro il plugin, così funziona anche quando il plugin è installato dal marketplace.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/marketplace/plugins/kybes/install.sh" "$@"
