#!/usr/bin/env bash
# Suite di test del kit: installa kybes in progetti temporanei e verifica il codice generato.
#   tests/run.sh            tutti i test disponibili sulla macchina
#   tests/run.sh python     solo un gruppo (python, typescript, java, csharp, sql, hooks)
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
VERIFY="$P/tools/kybes/plugins/kybes/scripts/verify.py"
PG="$WORK/proj-pg"; make_project "$PG" postgres

if python3 -B "$P/tools/kybes/plugins/kybes/scripts/gen/gen.py" "$P" --check >/dev/null; then pass "generatore idempotente (gen --check)"; else fail "gen --check"; fi
if python3 -B "$P/tools/kybes/plugins/kybes/scripts/arch_check.py" "$P" --strict >/dev/null; then pass "arch_check pulito sul progetto generato"; else fail "arch_check"; fi

if want python; then
  if python3 -c "import sqlalchemy" 2>/dev/null; then
    if python3 -B "$KIT/tests/python/test_model.py" "$P"; then pass "python: CRUD e relazioni su SQLite"; else fail "python"; fi
    if python3 -B "$KIT/tests/python/test_access.py" "$P"; then pass "python: paginazione keyset, query dichiarate, Unit of Work"; else fail "python access"; fi
    if python3 -c "import pytest, pytest_cov" 2>/dev/null; then
      if python3 -B "$VERIFY" "$P" --lang=python --quiet; then pass "python: test ISO 26262-6 generati nel progetto, copertura entro le soglie ASIL"; else fail "python: test generati o copertura"; fi
    else skip "python: test generati non eseguiti (pip install pytest pytest-cov)"; fi
  else skip "python: SQLAlchemy non installato (pip install sqlalchemy)"; fi
fi

if want typescript; then
  if command -v npm >/dev/null; then
    T="$WORK/ts"; cp -R "$KIT/tests/typescript" "$T"
    (cd "$T" && npm install --silent --no-audit --no-fund >/dev/null 2>&1) || true
    if [ -d "$T/node_modules/typeorm" ]; then
      cp -R "$P/libs/db-models/typescript/src/model" "$T/src/model"
      if (cd "$T" && npx tsc -p . && node dist/model.test.js); then pass "typescript: CRUD e relazioni su sql.js"; else fail "typescript sqlite"; fi
      if (cd "$T" && node dist/access.test.js); then pass "typescript: paginazione keyset, query dichiarate, Unit of Work"; else fail "typescript access"; fi
      # cursore prodotto da TypeScript letto da Python
      TSCUR=$(cd "$T" && node -e 'const {encodeCursor}=require("./dist/model/generated/_paging");const {PAGING_ORDINI}=require("./dist/model/generated/Ordini");console.log(encodeCursor(PAGING_ORDINI.defaultOrder,{data:"2026-01-02",id:"00000000-0000-0000-0000-000000000002"}))')
      if (cd "$P" && python3 -B -c "import sys; sys.path.insert(0,'libs/db-models/python/src'); from model.generated._paging import decode_cursor; from model.generated import PAGING_ORDINI as S; v=decode_cursor(S,S.default_order,sys.argv[1]); assert str(v[0])=='2026-01-02' and str(v[1]).endswith('2')" "$TSCUR"); then pass "cursore compatibile TypeScript → Python"; else fail "cursore TS→Python"; fi
      # test generati nel progetto: stesso pacchetto e stessi strumenti di un progetto reale (tsc, c8, node --test)
      ln -s "$T/node_modules" "$P/libs/db-models/typescript/node_modules"
      if python3 -B "$VERIFY" "$P" --lang=typescript --quiet; then pass "typescript: test ISO 26262-6 generati nel progetto, copertura entro le soglie ASIL"; else fail "typescript: test generati o copertura"; fi
      rm -f "$P/libs/db-models/typescript/node_modules"
      ln -s "$T/node_modules" "$PG/libs/db-models/typescript/node_modules"
      if (cd "$PG/libs/db-models/typescript" && "$T/node_modules/.bin/tsc" -p . --noEmit); then pass "typescript: compilazione strict dialetto postgres (model e test generati)"; else fail "typescript postgres"; fi
      rm -f "$PG/libs/db-models/typescript/node_modules"
    else skip "typescript: npm install non riuscito"; fi
  else skip "typescript: npm non disponibile"; fi
fi

if want java; then
  if command -v javac >/dev/null; then
    if javac -Xlint:all -Werror -d "$WORK/javaout" $(find "$KIT/tests/java/stubs" -name '*.java') $(find "$PG/libs/db-models/java" -name '*.java') 2>&1 | grep -v JAVA_TOOL_OPTIONS; then :; fi
    if [ -d "$WORK/javaout" ] && [ -n "$(find "$WORK/javaout" -name '*Repository.class' | head -1)" ]; then pass "java: compilazione -Xlint:all -Werror (stub JPA/Hibernate)"; else fail "java"; fi
    if javac -d "$WORK/javaout" -cp "$WORK/javaout" "$KIT/tests/java/runtime/PagingTest.java" 2>&1 | grep -v JAVA_TOOL_OPTIONS; then :; fi
    PYCUR=$(cd "$P" && python3 -B -c "import sys,uuid,datetime as dt; sys.path.insert(0,'libs/db-models/python/src'); from model.generated._paging import encode_cursor; from model.generated import PAGING_ORDINI as S
class R: data=dt.date(2026,1,2); id=uuid.UUID('00000000-0000-0000-0000-000000000002')
print(encode_cursor(S.default_order, R()))" 2>/dev/null || true)
    JOUT=$(java -cp "$WORK/javaout" PagingTest $PYCUR 2>&1 | grep -v JAVA_TOOL_OPTIONS || true)
    if echo "$JOUT" | grep -q "JAVA PAGING OK"; then pass "java: logica di paginazione e Unit of Work eseguite (EntityManager finto)"; else echo "$JOUT"; fail "java runtime"; fi
    if [ -n "$PYCUR" ]; then
      JCUR=$(echo "$JOUT" | sed -n 's/^CURSOR //p')
      if (cd "$P" && python3 -B -c "import sys; sys.path.insert(0,'libs/db-models/python/src'); from model.generated._paging import decode_cursor; from model.generated import PAGING_ORDINI as S; decode_cursor(S,S.default_order,sys.argv[1])" "$JCUR"); then pass "cursore compatibile Python ↔ Java"; else fail "cursore Python↔Java"; fi
    fi
  else skip "java: javac non disponibile"; fi
fi

if want csharp; then
  if python3 -c "import tree_sitter_c_sharp" 2>/dev/null; then
    if python3 "$KIT/tests/csharp/syntax_check.py" "$PG/libs/db-models/csharp" >/dev/null; then pass "csharp: sintassi del codice generato (tree-sitter)"; else python3 "$KIT/tests/csharp/syntax_check.py" "$PG/libs/db-models/csharp"; fail "csharp sintassi"; fi
  else skip "csharp: tree-sitter-c-sharp non installato (pip install tree-sitter tree-sitter-c-sharp)"; fi
  if command -v dotnet >/dev/null; then skip "csharp: compilazione non ancora automatizzata nella suite"; fi
fi

if want sql; then
  if python3 -c "import pglast" 2>/dev/null; then
    if python3 -c "import pglast,sys; pglast.parse_sql(open(sys.argv[1]).read())" "$PG/db/generated/ddl/postgres/_all.sql"; then pass "sql: DDL PostgreSQL valido (parser di PostgreSQL)"; else fail "sql DDL"; fi
  else skip "sql: pglast non installato (pip install pglast)"; fi
fi

if want hooks; then
  if bash "$KIT/tests/hooks/test_hooks.sh" "$P"; then pass "hook: regole e struttura"; else fail "hook"; fi
fi

exit $FAIL
