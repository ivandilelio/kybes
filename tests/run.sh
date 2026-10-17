#!/usr/bin/env bash
# Suite di test del kit: installa kybes in progetti temporanei e verifica il codice generato.
#   tests/run.sh            tutti i test disponibili sulla macchina
#   tests/run.sh python     solo un gruppo (python, jobs, typescript, java, csharp, sql, hooks)
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
# progetto con tabelle per schema e per database (tests/fixtures/tenancy), Python e TypeScript su SQLite
FIX="$WORK/fix"; mkdir -p "$FIX" && (cd "$FIX" && git init -q)
"$KIT/install.sh" --target "$FIX" --scaffold --no-plugin --model-langs python,typescript --tenant-id string --ci none >/dev/null
cp "$KIT"/tests/fixtures/tenancy/*.yaml "$FIX/schemas/db/"
sed -i.bak 's/"dialect": "postgres"/"dialect": "sqlite"/' "$FIX/.claude/kybes.config.json" && rm -f "$FIX/.claude/kybes.config.json.bak"
python3 -B "$FIX/tools/kybes/plugins/kybes/scripts/gen/gen.py" "$FIX" --quiet
VERIFY="$P/tools/kybes/plugins/kybes/scripts/verify.py"
PG="$WORK/proj-pg"; make_project "$PG" postgres
# progetto con collection MongoDB (tests/fixtures/mongo): 4 linguaggi, una tabella SQL accanto alle collection
MG="$WORK/mongo"; mkdir -p "$MG" && (cd "$MG" && git init -q)
"$KIT/install.sh" --target "$MG" --scaffold --no-plugin --model-langs csharp,python,typescript,java --ci none >/dev/null
cp "$KIT"/tests/fixtures/mongo/*.yaml "$MG/schemas/db/"
python3 -B "$MG/tools/kybes/plugins/kybes/scripts/gen/gen.py" "$MG" --quiet
# progetto con sole collection MongoDB: niente moduli SQL generati
MO="$WORK/mongo-only"; mkdir -p "$MO" && (cd "$MO" && git init -q)
"$KIT/install.sh" --target "$MO" --scaffold --no-plugin --model-langs csharp,python,typescript,java --ci none >/dev/null
cp "$KIT"/tests/fixtures/mongo/*.yaml "$MO/schemas/db/" && rm "$MO/schemas/db/Reparti.yaml"
python3 -B "$MO/tools/kybes/plugins/kybes/scripts/gen/gen.py" "$MO" --quiet

if python3 -B "$P/tools/kybes/plugins/kybes/scripts/gen/gen.py" "$P" --check >/dev/null; then pass "generatore idempotente (gen --check)"; else fail "gen --check"; fi
if python3 -B "$P/tools/kybes/plugins/kybes/scripts/arch_check.py" "$P" --strict >/dev/null; then pass "arch_check pulito sul progetto generato"; else fail "arch_check"; fi
if python3 -B "$MG/tools/kybes/plugins/kybes/scripts/gen/gen.py" "$MG" --check >/dev/null && python3 -B "$MG/tools/kybes/plugins/kybes/scripts/arch_check.py" "$MG" --strict >/dev/null; then
  pass "collection MongoDB: generatore idempotente e arch_check pulito"; else fail "mongo gen --check / arch_check"; fi
# il lettore YAML di riserva (senza PyYAML) deve dare lo stesso risultato di PyYAML sugli schemi di esempio
if python3 -B - "$KIT/marketplace/plugins/kybes/scripts/gen" "$KIT/marketplace/plugins/kybes/templates" "$KIT/tests/fixtures" <<'PY'
import datetime, glob, sys
sys.path.insert(0, sys.argv[1])
import miniyaml
try:
    import yaml
except ImportError:
    yaml = None
def norm(v):
    if isinstance(v, dict): return {k: norm(x) for k, x in v.items()}
    if isinstance(v, list): return [norm(x) for x in v]
    return v.isoformat() if isinstance(v, datetime.date) else v
for f in sorted(p for d in sys.argv[2:] for p in glob.glob(d + "/**/*.yaml", recursive=True)):
    text = open(f, encoding="utf-8").read()
    mine = miniyaml.loads(text)
    assert mine, f
    if yaml is not None:
        assert norm(yaml.safe_load(text)) == mine, f
PY
then pass "lettore YAML senza PyYAML equivalente a PyYAML (schemi di esempio, contratti OpenAPI, fixture)"; else fail "miniyaml"; fi
# contratto OpenAPI generato (CRUD dai blocchi api + endpoint custom): valido per OpenAPI 3.0
if python3 -c "import openapi_spec_validator" 2>/dev/null; then
  if python3 -B - "$P/schemas/generated/openapi.yaml" "$MG/schemas/generated/openapi.yaml" <<'PY'
import sys, yaml
from openapi_spec_validator import validate
for f in sys.argv[1:]:
    doc = yaml.safe_load(open(f, encoding="utf-8"))
    assert doc["paths"], f
    validate(doc)
PY
  then pass "api: contratto OpenAPI 3.0 generato valido (esempi e collection MongoDB)"; else fail "api: contratto OpenAPI generato"; fi
else skip "api: contratto non validato (pip install openapi-spec-validator)"; fi

if want python; then
  if python3 -c "import sqlalchemy" 2>/dev/null; then
    if python3 -B "$KIT/tests/python/test_model.py" "$P"; then pass "python: CRUD e relazioni su SQLite"; else fail "python"; fi
    if python3 -B "$KIT/tests/python/test_access.py" "$P"; then pass "python: paginazione keyset, query dichiarate, Unit of Work"; else fail "python access"; fi
    if python3 -c "import pytest, pytest_cov" 2>/dev/null; then
      if python3 -B "$VERIFY" "$P" --lang=python --quiet; then pass "python: test ISO 26262-6 generati nel progetto, copertura entro le soglie ASIL"; else fail "python: test generati o copertura"; fi
      if python3 -B "$VERIFY" "$FIX" --lang=python --quiet; then pass "python: test generati con tabelle per schema e per database"; else fail "python: progetto tenancy"; fi
      if python3 -c "import pymongo, mongomock" 2>/dev/null; then
        if KYBES_TEST_MONGO_URL=mongodb://finto PYTHONPATH="$KIT/tests/mongo" PYTEST_ADDOPTS="-p fake_mongo" python3 -B "$VERIFY" "$MG" --lang=python --quiet; then
          pass "python: test generati delle collection MongoDB (mongomock), copertura entro le soglie ASIL"; else fail "python: collection MongoDB"; fi
        if KYBES_TEST_MONGO_URL=mongodb://finto PYTHONPATH="$KIT/tests/mongo" PYTEST_ADDOPTS="-p fake_mongo" python3 -B "$VERIFY" "$MO" --lang=python --quiet; then
          pass "python: progetto con sole collection MongoDB, senza moduli SQL"; else fail "python: sole collection MongoDB"; fi
      else skip "python: collection MongoDB non verificate (pip install pymongo mongomock)"; fi
    else skip "python: test generati non eseguiti (pip install pytest pytest-cov)"; fi
  else skip "python: SQLAlchemy non installato (pip install sqlalchemy)"; fi
fi

if want jobs; then
  if python3 -c "import pyarrow, sqlalchemy, pytest, pytest_cov" 2>/dev/null; then
    ENG="$KIT/marketplace/plugins/kybes/scripts/gen/engine"
    if (cd "$ENG" && python3 -m pytest -q -p no:cacheprovider tests >/dev/null); then pass "jobs: test del motore nel kit"; else fail "jobs: motore nel kit"; fi
    if python3 -B "$VERIFY" "$P" --lang=jobs --quiet; then pass "jobs: test del motore e dei job generati nel progetto, copertura entro le soglie ASIL"; else fail "jobs: progetto"; fi
    if python3 -B "$VERIFY" "$FIX" --lang=jobs --quiet; then pass "jobs: archivio con tabelle per schema e per database di tenant"; else fail "jobs: progetto tenancy"; fi
    if python3 -B "$KIT/tests/python/test_archive.py" "$P" "$KIT"; then pass "jobs: validazione, formato, job reale, read-through, layout Hive, S3, manifest"; else fail "jobs: archivio end-to-end"; fi
  else skip "jobs: dipendenze del motore non installate (pip install pyarrow sqlalchemy pytest pytest-cov)"; fi
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
      ln -s "$T/node_modules" "$P/node_modules"
      if python3 -B "$VERIFY" "$P" --lang=typescript --quiet; then pass "typescript: test ISO 26262-6 generati nel progetto, copertura entro le soglie ASIL"; else fail "typescript: test generati o copertura"; fi
      rm -f "$P/libs/db-models/typescript/node_modules" "$P/node_modules"
      ln -s "$T/node_modules" "$FIX/libs/db-models/typescript/node_modules"
      ln -s "$T/node_modules" "$FIX/node_modules"
      if python3 -B "$VERIFY" "$FIX" --lang=typescript --quiet; then pass "typescript: test generati con tabelle per schema e per database"; else fail "typescript: progetto tenancy"; fi
      rm -f "$FIX/libs/db-models/typescript/node_modules" "$FIX/node_modules"
      ln -s "$T/node_modules" "$PG/libs/db-models/typescript/node_modules"
      ln -s "$T/node_modules" "$PG/node_modules"
      if (cd "$PG/libs/db-models/typescript" && "$T/node_modules/.bin/tsc" -p . --noEmit); then pass "typescript: compilazione strict dialetto postgres (model e test generati)"; else fail "typescript postgres"; fi
      rm -f "$PG/libs/db-models/typescript/node_modules" "$PG/node_modules"
      ln -s "$T/node_modules" "$MG/libs/db-models/typescript/node_modules"
      ln -s "$T/node_modules" "$MG/node_modules"
      if (cd "$MG/libs/db-models/typescript" && "$T/node_modules/.bin/tsc" -p . --noEmit); then pass "typescript: compilazione strict con collection MongoDB (model e test generati)"; else fail "typescript mongo"; fi
      rm -f "$MG/libs/db-models/typescript/node_modules" "$MG/node_modules"
      ln -s "$T/node_modules" "$MO/libs/db-models/typescript/node_modules"
      ln -s "$T/node_modules" "$MO/node_modules"
      if (cd "$MO/libs/db-models/typescript" && "$T/node_modules/.bin/tsc" -p . --noEmit); then pass "typescript: compilazione strict con sole collection MongoDB"; else fail "typescript sole collection"; fi
      rm -f "$MO/libs/db-models/typescript/node_modules" "$MO/node_modules"
    else skip "typescript: npm install non riuscito"; fi
  else skip "typescript: npm non disponibile"; fi
fi

if want java; then
  if command -v javac >/dev/null; then
    if javac -Xlint:all -Werror -d "$WORK/javaout" $(find "$KIT/tests/java/stubs" -name '*.java') $(find "$PG/libs/db-models/java" "$PG/api" "$PG/controllers" -name '*.java' 2>/dev/null) 2>&1 | grep -v JAVA_TOOL_OPTIONS; then :; fi
    if [ -d "$WORK/javaout" ] && [ -n "$(find "$WORK/javaout" -name '*Repository.class' | head -1)" ]; then pass "java: compilazione -Xlint:all -Werror (stub JPA/Hibernate)"; else fail "java"; fi
    if javac -Xlint:all -Werror -d "$WORK/javamongo" $(find "$KIT/tests/java/stubs" -name '*.java') $(find "$MG/libs/db-models/java" "$MG/api" "$MG/controllers" -name '*.java' 2>/dev/null) 2>&1 | grep -v JAVA_TOOL_OPTIONS; then :; fi
    if [ -n "$(find "$WORK/javamongo" -name 'MongoSession.class' 2>/dev/null | head -1)" ]; then pass "java: compilazione -Xlint:all -Werror con collection MongoDB (stub del driver)"; else fail "java mongo"; fi
    if javac -Xlint:all -Werror -d "$WORK/javamongoonly" $(find "$KIT/tests/java/stubs" -name '*.java') $(find "$MO/libs/db-models/java" "$MO/api" "$MO/controllers" -name '*.java' 2>/dev/null) 2>&1 | grep -v JAVA_TOOL_OPTIONS; then :; fi
    if [ -n "$(find "$WORK/javamongoonly" -name 'KybesRuntimeTest.class' 2>/dev/null | head -1)" ] && [ -z "$(find "$WORK/javamongoonly" -name 'UnitOfWork*.class' | head -1)" ]; then
      pass "java: compilazione con sole collection MongoDB, senza moduli SQL"; else fail "java sole collection"; fi
    # API REST: nucleo solo JDK (JSON, validazione, router, Lambda, server del JDK) eseguito senza JUnit né database
    javac -d "$WORK/javaout" -cp "$WORK/javaout" "$KIT/tests/java/runtime/RunTests.java" 2>&1 | grep -v JAVA_TOOL_OPTIONS || true
    if java -cp "$WORK/javaout" RunTests "$(sed -n 's/^package \(.*\);/\1/p' "$(find "$PG/libs/db-models/java" -name KybesApiRuntimeTest.java)").KybesApiRuntimeTest" rt_api_framework rt_api_custom >"$WORK/javaapi.log" 2>&1; then
      pass "java: test dei moduli comuni delle API eseguiti (nucleo JDK, Lambda, server HTTP del JDK)"; else cat "$WORK/javaapi.log"; fail "java api"; fi
    if javac -d "$WORK/javamongo" -cp "$WORK/javamongo" "$KIT/tests/java/runtime/RunTests.java" 2>&1 | grep -v JAVA_TOOL_OPTIONS; then :; fi
    if java -cp "$WORK/javamongo" RunTests "$(sed -n 's/^package \(.*\);/\1/p' "$(find "$MG/libs/db-models/java" -name KybesApiRuntimeTest.java)").KybesApiRuntimeTest" rt_api_framework rt_api_custom >"$WORK/javaapimongo.log" 2>&1; then
      pass "java: test dei moduli comuni delle API con collection MongoDB"; else cat "$WORK/javaapimongo.log"; fail "java api mongo"; fi
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
    if python3 "$KIT/tests/csharp/syntax_check.py" "$MG/libs/db-models/csharp" >/dev/null; then pass "csharp: sintassi con collection MongoDB (tree-sitter)"; else python3 "$KIT/tests/csharp/syntax_check.py" "$MG/libs/db-models/csharp"; fail "csharp mongo sintassi"; fi
    if python3 "$KIT/tests/csharp/syntax_check.py" "$MO/libs/db-models/csharp" >/dev/null && [ ! -e "$MO/libs/db-models/csharp/src/model/generated/AppDbContext.cs" ]; then pass "csharp: sintassi con sole collection MongoDB, senza DbContext"; else fail "csharp sole collection"; fi
  else skip "csharp: tree-sitter-c-sharp non installato (pip install tree-sitter tree-sitter-c-sharp)"; fi
  if command -v dotnet >/dev/null; then skip "csharp: compilazione non ancora automatizzata nella suite"; fi
fi

if want sql; then
  if python3 -c "import pglast" 2>/dev/null; then
    if python3 -c "import pglast,sys; pglast.parse_sql(open(sys.argv[1]).read())" "$PG/db/generated/ddl/postgres/_all.sql"; then pass "sql: DDL PostgreSQL valido (parser di PostgreSQL)"; else fail "sql DDL"; fi
    if python3 -c "import pglast,sys; [pglast.parse_sql(open(f).read()) for f in sys.argv[1:]]" "$PG"/db/generated/tenancy/*.sql "$FIX"/db/generated/tenancy/*.sql "$FIX/db/generated/ddl/postgres/_all.sql"; then pass "sql: row-level security, schema e database per tenant validi (parser di PostgreSQL)"; else fail "sql tenancy"; fi
  else skip "sql: pglast non installato (pip install pglast)"; fi
fi

if want hooks; then
  if bash "$KIT/tests/hooks/test_hooks.sh" "$P"; then pass "hook: regole e struttura"; else fail "hook"; fi
fi

exit $FAIL
