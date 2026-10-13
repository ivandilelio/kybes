#!/usr/bin/env bash
# Installer di kybes: regole, agenti e controlli automatici di Claude Code per gestionali cloud.
#
# Uso:
#   ./install.sh [--target DIR] [--fn-lang LANG] [--ms-lang LANG] [--model-langs L1,L2,...]
#                [--namespace App.Model] [--java-package app.model] [--asil QM|A|B|C|D] [--scaffold] [--examples]
#                [--ci github|none] [--scope local|project|user] [--no-plugin] [--force] [--uninstall]
#   LANG: python, typescript, csharp, java
#
# Rilanciarlo è sicuro: aggiorna il kit, rigenera il blocco in CLAUDE.md e non sovrascrive
# configurazione, regole o file di scaffold esistenti (salvo --force).
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # cartella del plugin
# repo: lanciato dal clone di kybes; marketplace: lanciato dalla copia installata da Claude Code
if [ -f "$KIT_DIR/../../../.claude-plugin/marketplace.json" ]; then MODE=repo; else MODE=marketplace; fi
TARGET="."
FN_LANG="python"
MS_LANG="typescript"
MODEL_LANGS=""
NAMESPACE="App.Model"
JAVA_PACKAGE="app.model"
ASIL="B"
EXAMPLES=0
SCAFFOLD=0
CI="github"
SCOPE="local"
NO_PLUGIN=0
FORCE=0
UNINSTALL=0
MARKETPLACE="kybes"
PLUGIN="kybes"
KIT_REL="tools/kybes"

die()  { printf '\033[31mErrore:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[36m•\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --target)   TARGET="${2:?manca la cartella}"; shift 2 ;;
    --fn-lang)  FN_LANG="${2:?}"; shift 2 ;;
    --ms-lang)  MS_LANG="${2:?}"; shift 2 ;;
    --model-langs) MODEL_LANGS="${2:?}"; shift 2 ;;
    --namespace) NAMESPACE="${2:?}"; shift 2 ;;
    --java-package) JAVA_PACKAGE="${2:?}"; shift 2 ;;
    --asil)     ASIL="${2:?}"; shift 2 ;;
    --examples) EXAMPLES=1; shift ;;
    --scaffold) SCAFFOLD=1; shift ;;
    --ci)       CI="${2:?}"; shift 2 ;;
    --scope)    SCOPE="${2:?}"; shift 2 ;;
    --no-plugin) NO_PLUGIN=1; shift ;;
    --force)    FORCE=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help)  usage ;;
    *) die "opzione sconosciuta: $1 (vedi --help)" ;;
  esac
done

case "$FN_LANG" in python|typescript|csharp|java) ;; *) die "--fn-lang: python, typescript, csharp o java" ;; esac
case "$MS_LANG" in python|typescript|csharp|java) ;; *) die "--ms-lang: python, typescript, csharp o java" ;; esac
if [ -z "$MODEL_LANGS" ]; then
  MODEL_LANGS="$FN_LANG"; [ "$MS_LANG" = "$FN_LANG" ] || MODEL_LANGS="$FN_LANG,$MS_LANG"
fi
for l in $(echo "$MODEL_LANGS" | tr ',' ' '); do
  case "$l" in python|typescript|csharp|java) ;; *) die "--model-langs: valore non valido '$l'" ;; esac
done
case "$ASIL" in QM|A|B|C|D) ;; *) die "--asil: QM, A, B, C o D" ;; esac
echo "$NAMESPACE" | grep -Eq '^[A-Z][A-Za-z0-9]*(\.[A-Z][A-Za-z0-9]*)*$' || die "--namespace non valido: $NAMESPACE"
echo "$JAVA_PACKAGE" | grep -Eq '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' || die "--java-package non valido: $JAVA_PACKAGE"
case "$SCOPE" in project|local|user) ;; *) die "--scope deve essere project, local o user" ;; esac
case "$CI" in github|none) ;; *) die "--ci deve essere github o none" ;; esac

command -v python3 >/dev/null || die "serve python3 (usato dagli hook di controllo)"
[ -d "$TARGET" ] || die "la cartella $TARGET non esiste"
TARGET="$(cd "$TARGET" && pwd)"
[ "$TARGET" != "$KIT_DIR" ] || die "indica con --target il repository del gestionale, non la cartella del kit"

HAVE_CLAUDE=0
command -v claude >/dev/null && HAVE_CLAUDE=1

# --------------------------------------------------------------- disinstallazione
if [ "$UNINSTALL" = 1 ]; then
  if [ "$HAVE_CLAUDE" = 1 ]; then
    (cd "$TARGET" && claude plugin uninstall "$PLUGIN@$MARKETPLACE" --scope "$SCOPE" >/dev/null 2>&1) && ok "plugin disinstallato" || warn "plugin non trovato nello scope $SCOPE"
    (cd "$TARGET" && claude plugin marketplace remove "$MARKETPLACE" >/dev/null 2>&1) && ok "marketplace rimosso" || true
  fi
  rm -rf "$TARGET/$KIT_REL" "$TARGET/.claude/rules/kybes"
  if [ -f "$TARGET/CLAUDE.md" ]; then
    python3 - "$TARGET/CLAUDE.md" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1]); t = p.read_text(encoding="utf-8")
t = re.sub(r"\n*<!-- kybes:start.*?<!-- kybes:end -->\n?", "\n", t, flags=re.S).strip()
p.write_text((t + "\n") if t else "", encoding="utf-8")
PY
  fi
  ok "rimossi kit, regole e blocco in CLAUDE.md (configurazione e scaffold lasciati al loro posto)"
  exit 0
fi

echo
info "Installo kybes in $TARGET (function: $FN_LANG, microservizi: $MS_LANG, model: $MODEL_LANGS, scope: $SCOPE)"

# --------------------------------------------------------------- 1. kit nel repository
mkdir -p "$TARGET/tools"
rm -rf "$TARGET/$KIT_REL"
mkdir -p "$TARGET/$KIT_REL/.claude-plugin" "$TARGET/$KIT_REL/plugins"
cp -R "$KIT_DIR" "$TARGET/$KIT_REL/plugins/$PLUGIN"
rm -rf "$TARGET/$KIT_REL/plugins/$PLUGIN/templates/esempi-schemi/.git" 2>/dev/null || true
cp "$KIT_DIR/templates/setup.sh" "$TARGET/$KIT_REL/setup.sh"
cat > "$TARGET/$KIT_REL/.claude-plugin/marketplace.json" <<JSON
{
  "name": "$MARKETPLACE",
  "owner": { "name": "kybes" },
  "description": "Copia di kybes versionata con il progetto (hook, generatore e controlli usati anche dalla CI).",
  "plugins": [ { "name": "$PLUGIN", "source": "./plugins/$PLUGIN", "description": "kybes" } ]
}
JSON
find "$TARGET/$KIT_REL" -name '__pycache__' -type d -prune -exec rm -rf {} +
chmod +x "$TARGET/$KIT_REL"/plugins/$PLUGIN/scripts/*.py "$TARGET/$KIT_REL/setup.sh"
ok "kit copiato in $KIT_REL (versionato con il repo, usato anche dalla CI)"

# --------------------------------------------------------------- 2. configurazione
mkdir -p "$TARGET/.claude/rules/kybes"
CFG="$TARGET/.claude/kybes.config.json"
if [ ! -f "$CFG" ] || [ "$FORCE" = 1 ]; then
  python3 - "$CFG" "$FN_LANG" "$MS_LANG" "$KIT_REL" "$MODEL_LANGS" "$NAMESPACE" "$JAVA_PACKAGE" "$ASIL" <<'PY'
import json, sys
cfg_path, fn_lang, ms_lang, kit, model_langs, namespace, java_pkg, asil = sys.argv[1:9]
langs = [l for l in model_langs.split(",") if l]
used = set(langs) | {fn_lang, ms_lang}
lint = {}
if "python" in used:
    lint["**/*.py"] = ["ruff check --quiet {file}"]
if "typescript" in used:
    lint["**/*.{ts,tsx}"] = ["node_modules/.bin/eslint {file}"]
targets = []
for l in langs:
    if l == "python":
        targets.append({"lang": "python", "dir": "libs/db-models/python/src/model"})
    elif l == "typescript":
        targets.append({"lang": "typescript", "dir": "libs/db-models/typescript/src/model", "dialect": "postgres"})
    elif l == "csharp":
        targets.append({"lang": "csharp", "dir": "libs/db-models/csharp/src/model", "namespace": namespace, "dialect": "postgres"})
    elif l == "java":
        targets.append({"lang": "java", "dir": "libs/db-models/java/src/main/java/" + java_pkg.replace(".", "/"),
                        "package": java_pkg, "dialect": "postgres"})
cfg = {
    "version": 1,
    "cloud": "aws",
    "languages": {"functions": fn_lang, "microservices": ms_lang},
    "paths": {
        "db_models": ["libs/db-models/**"],
        "functions": ["services/*/functions/**"],
        "microservices": ["services/*/ms/**"],
        "jobs": ["jobs/**"],
        "utils": ["libs/utils/**"],
        "errors": ["libs/errors/**"],
        "frontend": ["frontend/**"],
        "infra": ["infra/**"],
    },
    "rules": {
        "orm_outside_db_models": "block",
        "hardcoded_secrets": "block",
        "protected_paths": "block",
        "raw_sql_outside_db_models": "warn",
        "error_leak": "warn",
        "utils_impure": "warn",
        "function_long_running": "warn",
        "generated_files": "block",
        "model_layout": "block",
        "custom_method_collision": "block",
        "custom_tests": "block",
        "duplicate_code": "block",
    },
    "model": {
        "schema_dir": "schemas/db",
        "json_schema_dir": "schemas/generated/json",
        "index_file": "MODEL_INDEX.md",
        "targets": targets,
    },
    "verification": {
        "asil": asil,
        "generate_tests": True,
        "docs_dir": "docs/generated/verification",
        "coverage_reports": ["coverage/*.cobertura.xml", "coverage/*.jacoco.xml"],
        "thresholds": {"QM": {}, "A": {"statement": 90}, "B": {"statement": 95, "branch": 90},
                       "C": {"statement": 100, "branch": 95}, "D": {"statement": 100, "branch": 100}},
    },
    "duplicates": {"min_lines": 8, "include_tests": False, "ignore": []},
    "extra_forbidden_modules": [],
    "post_edit_commands": lint,
    "stop_gate": {
        "enabled": True,
        "only_if_changes": True,
        "max_blocks": 3,
        "commands": [f"python3 -B {kit}/plugins/kybes/scripts/verify.py . --quiet"],
    },
    "arch_check_command": f"python3 {kit}/plugins/kybes/scripts/arch_check.py .",
    "_note": {
        "rules": "valori ammessi: block, warn, off",
        "extra_forbidden_modules": "moduli DB aggiuntivi da vietare fuori da DB-Models; prefisso js: per i pacchetti npm",
        "stop_gate.commands": "verify.py esegue i test del modello e controlla la copertura per ASIL; aggiungi gli altri test del progetto",
        "verification": "asil di default delle tabelle (ogni schema può alzarlo con verification.asil); soglie di copertura in percentuale",
        "paths": "si aggiungono ai default: ignore e protected restano attivi",
        "model.targets": "una voce per linguaggio; dialect: postgres (default) o sqlite; il generatore scrive in <dir>/generated",
        "duplicates": "blocchi di min_lines righe significative ripetuti; ignore: glob da escludere",
    },
}
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY
  ok "configurazione scritta in .claude/kybes.config.json"
else
  info "configurazione esistente lasciata invariata (usa --force per rigenerarla)"
fi

# --------------------------------------------------------------- 3. regole per percorso
for f in "$KIT_DIR"/templates/rules/*.md; do
  dest="$TARGET/.claude/rules/kybes/$(basename "$f")"
  if [ ! -f "$dest" ] || [ "$FORCE" = 1 ]; then cp "$f" "$dest"; fi
done
ok "regole per percorso in .claude/rules/kybes/"

# --------------------------------------------------------------- 4. blocco in CLAUDE.md
python3 - "$TARGET/CLAUDE.md" "$KIT_DIR/templates/CLAUDE.kybes.md" <<'PY'
import re, sys, pathlib
target, block_file = map(pathlib.Path, sys.argv[1:3])
block = block_file.read_text(encoding="utf-8").strip()
text = target.read_text(encoding="utf-8") if target.exists() else ""
rx = re.compile(r"<!-- kybes:start.*?<!-- kybes:end -->", re.S)
text = rx.sub(lambda _: block, text) if rx.search(text) else (text.rstrip() + "\n\n" + block if text.strip() else block)
target.write_text(text.rstrip() + "\n", encoding="utf-8")
PY
ok "blocco regole aggiornato in CLAUDE.md"

# --------------------------------------------------------------- 5. scaffold (opzionale)
if [ "$SCAFFOLD" = 1 ]; then
  (cd "$KIT_DIR/templates/scaffold" && find . -type f) | while read -r rel; do
    rel="${rel#./}"
    case "$rel" in
      libs/errors/python/*)     [ "$FN_LANG" = python ] || [ "$MS_LANG" = python ] || continue ;;
      libs/errors/typescript/*) [ "$FN_LANG" = typescript ] || [ "$MS_LANG" = typescript ] || continue ;;
      libs/db-models/*/*)       case ",$MODEL_LANGS," in *",$(echo "$rel" | cut -d/ -f3),"*) ;; *) continue ;; esac ;;
    esac
    dest="$TARGET/$rel"
    if [ ! -f "$dest" ] || [ "$FORCE" = 1 ]; then
      mkdir -p "$(dirname "$dest")"; cp "$KIT_DIR/templates/scaffold/$rel" "$dest"
    fi
  done
  for d in infra schemas libs/utils \
           services jobs frontend; do
    mkdir -p "$TARGET/$d"
    [ -n "$(ls -A "$TARGET/$d" 2>/dev/null)" ] || touch "$TARGET/$d/.gitkeep"
  done
  ok "struttura del progetto creata (file esistenti non toccati)"
fi

# --------------------------------------------------------------- 5a. .gitignore
GI="$TARGET/.gitignore"
touch "$GI"
for pat in "__pycache__/" "*.pyc" "coverage/" "node_modules/" "libs/db-models/typescript/dist/" ".coverage" "libs/db-models/java/target/" "libs/db-models/csharp/**/bin/" "libs/db-models/csharp/**/obj/"; do
  grep -qxF "$pat" "$GI" || echo "$pat" >> "$GI"
done

# --------------------------------------------------------------- 5b. schemi e generazione
mkdir -p "$TARGET/schemas/db"
if [ "$EXAMPLES" = 1 ]; then
  for f in "$KIT_DIR"/templates/esempi-schemi/*.yaml; do
    dest="$TARGET/schemas/db/$(basename "$f")"
    [ -f "$dest" ] && [ "$FORCE" = 0 ] || cp "$f" "$dest"
  done
  ok "schemi di esempio in schemas/db (Clienti, Ordini, RigheOrdine, Prodotti, Categorie)"
fi
if ls "$TARGET"/schemas/db/*.yaml >/dev/null 2>&1; then
  if python3 -B "$TARGET/$KIT_REL/plugins/$PLUGIN/scripts/gen/gen.py" "$TARGET" --quiet; then
    ok "modello generato dagli schemi (indice in MODEL_INDEX.md)"
  else
    warn "generazione non riuscita: correggi gli schemi in schemas/db e rilancia"
  fi
else
  info "nessuno schema ancora: crea schemas/db/<Tabella>.yaml (o rilancia con --examples)"
fi

# --------------------------------------------------------------- 6. CI
if [ "$CI" = github ]; then
  wf="$TARGET/.github/workflows/architecture-check.yml"
  if [ ! -f "$wf" ] || [ "$FORCE" = 1 ]; then
    mkdir -p "$(dirname "$wf")"; cp "$KIT_DIR/templates/ci/architecture-check.yml" "$wf"
    ok "workflow CI in .github/workflows/architecture-check.yml"
  else
    info "workflow CI già presente"
  fi
fi

# --------------------------------------------------------------- 7. registrazione in Claude Code
if [ "$NO_PLUGIN" = 1 ]; then
  info "registrazione del plugin saltata (--no-plugin)"
elif [ "$MODE" = marketplace ]; then
  info "plugin già installato dal marketplace: la copia in $KIT_REL serve alla CI e ai colleghi senza il plugin"
elif [ "$HAVE_CLAUDE" = 0 ]; then
  warn "comando 'claude' non trovato: installa Claude Code e rilancia, oppure esegui nella cartella del repo:"
  echo "    claude plugin marketplace add ./$KIT_REL --scope $SCOPE"
  echo "    claude plugin install $PLUGIN@$MARKETPLACE --scope $SCOPE"
else
  if bash "$TARGET/$KIT_REL/setup.sh" "$SCOPE" >/dev/null; then
    ok "plugin $PLUGIN attivo in Claude Code (scope $SCOPE)"
  else
    warn "registrazione del plugin non riuscita: esegui $KIT_REL/setup.sh nella cartella del repo"
  fi
  if [ "$SCOPE" = project ]; then
    warn "scope project: .claude/settings.json contiene il percorso assoluto del kit su questa macchina; i colleghi eseguano comunque $KIT_REL/setup.sh"
  fi
fi

# --------------------------------------------------------------- 8. verifica
echo
info "Controllo architetturale iniziale:"
python3 -B "$TARGET/$KIT_REL/plugins/$PLUGIN/scripts/arch_check.py" "$TARGET" || warn "ci sono violazioni da sistemare (vedi sopra)"

cat <<EOF

Fatto. Prossimi passi:
  1. Rivedi .claude/kybes.config.json (cartelle, linter, comandi di test in stop_gate.commands).
  2. Fai commit di tools/kybes, .claude/ e CLAUDE.md. Ogni collega, dopo il clone, esegue:
       tools/kybes/setup.sh
  3. Riavvia Claude Code nel repo e chiedi un piano: verrà usato l'agente kybes:architect.
EOF
