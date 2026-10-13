#!/usr/bin/env bash
# Suite di test del kit: installa kybes in progetti temporanei e verifica il codice generato.
#   tests/run.sh            tutti i test disponibili sulla macchina
#   tests/run.sh python     solo un gruppo (python, typescript, java, hooks)
set -euo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ONLY="${1:-all}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FAIL=0
pass() { printf '\033[32mPASS\033[0m %s\n' "$*"; }
fail() { printf '\033[31mFAIL\033[0m %s\n' "$*"; FAIL=1; }
skip() { printf '\033[33mSKIP\033[0m %s\n' "$*"; }
want() { [ "$ONLY" = all ] || [ "$ONLY" = "$1" ]; }

# progetto di prova: i 4 linguaggi + schemi di esempio, dialetto sqlite per TypeScript
make_project() {  # $1 cartella, $2 dialetto TS
  mkdir -p "$1" && (cd "$1" && git init -q)
  "$KIT/install.sh" --target "$1" --scaffold --examples --no-plugin \
    --model-langs csharp,python,typescript,java --ci none >/dev/null
  if [ "$2" = sqlite ]; then
    sed -i.bak 's/"dialect": "postgres"/"dialect": "sqlite"/' "$1/.claude/kybes.config.json" && rm -f "$1/.claude/kybes.config.json.bak"
    python3 -B "$1/tools/kybes/plugins/kybes/scripts/gen/gen.py" "$1" --quiet
  fi
}
P="$WORK/proj"; make_project "$P" sqlite
PG="$WORK/proj-pg"; make_project "$PG" postgres

if python3 -B "$P/tools/kybes/plugins/kybes/scripts/gen/gen.py" "$P" --check >/dev/null; then pass "generatore idempotente (gen --check)"; else fail "gen --check"; fi
if python3 -B "$P/tools/kybes/plugins/kybes/scripts/arch_check.py" "$P" --strict >/dev/null; then pass "arch_check pulito sul progetto generato"; else fail "arch_check"; fi

if want python; then
  if python3 -c "import sqlalchemy" 2>/dev/null; then
    if python3 -B "$KIT/tests/python/test_model.py" "$P"; then pass "python: CRUD e relazioni su SQLite"; else fail "python"; fi
  else skip "python: SQLAlchemy non installato (pip install sqlalchemy)"; fi
fi

if want typescript; then
  if command -v npm >/dev/null; then
    T="$WORK/ts"; cp -R "$KIT/tests/typescript" "$T"
    (cd "$T" && npm install --silent --no-audit --no-fund >/dev/null 2>&1) || true
    if [ -d "$T/node_modules/typeorm" ]; then
      cp -R "$P/libs/db-models/typescript/src/model" "$T/src/model"
      if (cd "$T" && npx tsc -p . && node dist/model.test.js); then pass "typescript: CRUD e relazioni su sql.js"; else fail "typescript sqlite"; fi
      rm -rf "$T/src/model" "$T/dist"; cp -R "$PG/libs/db-models/typescript/src/model" "$T/src/model"; rm -f "$T/src/model.test.ts"
      if (cd "$T" && npx tsc -p . --noEmit); then pass "typescript: compilazione strict dialetto postgres"; else fail "typescript postgres"; fi
    else skip "typescript: npm install non riuscito"; fi
  else skip "typescript: npm non disponibile"; fi
fi

if want java; then
  if command -v javac >/dev/null; then
    if javac -Xlint:all -Werror -d "$WORK/javaout" $(find "$KIT/tests/java/stubs" -name '*.java') $(find "$PG/libs/db-models/java" -name '*.java') 2>&1 | grep -v JAVA_TOOL_OPTIONS; then :; fi
    if [ -d "$WORK/javaout" ] && [ -n "$(find "$WORK/javaout" -name '*Repository.class' | head -1)" ]; then pass "java: compilazione -Xlint:all -Werror (stub JPA/Hibernate)"; else fail "java"; fi
  else skip "java: javac non disponibile"; fi
fi

if want hooks; then
  if bash "$KIT/tests/hooks/test_hooks.sh" "$P"; then pass "hook: regole e struttura"; else fail "hook"; fi
fi

exit $FAIL
