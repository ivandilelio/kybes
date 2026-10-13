#!/usr/bin/env bash
# Test degli hook su un progetto generato: ogni caso dichiara l'esito atteso (deny/allow).
#   tests/hooks/test_hooks.sh <cartella_progetto>
set -uo pipefail
P="$(cd "$1" && pwd)"
SC="$P/tools/kybes/plugins/kybes/scripts"
M="libs/db-models/python/src/model"
FAIL=0

decision() {  # stdin: evento JSON; stampa deny|allow
  local out
  out="$(CLAUDE_PROJECT_DIR="$P" python3 -B "$SC/pre_write.py")"
  if echo "$out" | grep -q '"permissionDecision": "deny"'; then echo deny; else echo allow; fi
}

expect() {  # $1 descrizione, $2 atteso, $3 tool, $4 file, $5 testo
  local ev got
  ev=$(python3 -c 'import json,sys; t,f,x=sys.argv[1:4]; ti={"file_path":f}; ti.update({"content":x} if t=="Write" else {"old_string":"x","new_string":x}); print(json.dumps({"tool_name":t,"cwd":sys.argv[4],"tool_input":ti}))' "$3" "$P/$4" "$5" "$P")
  got=$(echo "$ev" | decision)
  if [ "$got" = "$2" ]; then echo "  ok   $1"; else echo "  ERR  $1 (atteso $2, ottenuto $got)"; FAIL=1; fi
}

echo "pre_write:"
expect "file generato" deny Edit "$M/generated/Clienti.py" "x = 1"
expect "MODEL_INDEX.md" deny Write "MODEL_INDEX.md" "x"
expect "JSON Schema generato" deny Write "schemas/generated/json/Clienti.schema.json" "{}"
expect "DDL generato" deny Write "db/generated/ddl/postgres/Clienti.sql" "DROP TABLE x;"
expect "job generato" deny Write "jobs/generated/ordini-archive/config.json" "{}"
expect "job applicativo" allow Write "jobs/fatture-mensili/main.py" "print(1)"
expect "metodo custom con nome CRUD (Python)" deny Edit "$M/Clienti.py" $'    def get_by_id(self, id):\n        return None\n'
expect "metodo custom nuovo (Python)" allow Edit "$M/Clienti.py" $'    def list_con_email(self):\n        return []\n'
expect "metodo custom con nome CRUD (C#)" deny Edit "libs/db-models/csharp/src/model/Ordini.cs" $'    public async Task<Ordini?> GetByIdAsync(Guid id, CancellationToken ct = default) => null;\n'
expect "metodo custom con nome CRUD (Java)" deny Edit "libs/db-models/java/src/main/java/app/model/OrdiniRepository.java" $'    public List<Ordini> listByClienteId(UUID v, int o, int l) { return null; }\n'
expect "metodo custom con nome CRUD (TypeScript)" deny Edit "libs/db-models/typescript/src/model/Ordini.ts" $'  async getCliente(id: string) {\n    return null;\n  }\n'
expect "file model senza schema" deny Write "$M/Fornitori.py" "x = 1"
expect "sottocartella nel model" deny Write "$M/helpers/util.py" "x = 1"
expect "nome file Java non conforme" deny Write "libs/db-models/java/src/main/java/app/model/ClientiDao.java" "class X {}"
expect "EF Core fuori dal model" deny Write "services/ordini/ms/OrdiniService.cs" $'using Microsoft.EntityFrameworkCore;\nclass S {}'
expect "JDBC fuori dal model" deny Write "services/ordini/ms/OrdiniService.java" $'import java.sql.Connection;\nclass S {}'
expect "SQLAlchemy fuori dal model" deny Write "services/ordini/functions/get.py" "from sqlalchemy import select"
expect "segreto AWS" deny Write "infra/main.tf" 'access_key = "AKIAIOSFODNN7EXAMPLQ"'
expect "configurazione del kit" deny Edit ".claude/kybes.config.json" '"off"'
expect "service pulito" allow Write "services/ordini/functions/get.py" "from model.Ordini import OrdiniRepository"

echo "post_edit (rigenerazione automatica):"
cp "$P/schemas/db/Clienti.yaml" "$P/schemas/db/Clienti.yaml.orig"
python3 - "$P/schemas/db/Clienti.yaml" <<'PY'
import sys; p = sys.argv[1]; t = open(p).read()
open(p, "w").write(t.replace("  - name: Attivo\n", "  - name: Telefono\n    type: string\n    length: 30\n  - name: Attivo\n"))
PY
out=$(echo "{\"tool_name\":\"Edit\",\"cwd\":\"$P\",\"tool_input\":{\"file_path\":\"$P/schemas/db/Clienti.yaml\"}}" | CLAUDE_PROJECT_DIR="$P" python3 -B "$SC/post_edit.py")
if echo "$out" | grep -q "Generatore eseguito" && grep -q "telefono" "$P/$M/generated/Clienti.py"; then echo "  ok   schema modificato → model rigenerato"; else echo "  ERR  rigenerazione"; FAIL=1; fi
mv "$P/schemas/db/Clienti.yaml.orig" "$P/schemas/db/Clienti.yaml"; python3 -B "$SC/gen/gen.py" "$P" --quiet

echo "arch_check (duplicati):"
mkdir -p "$P/services/a/functions" "$P/services/b/functions"
BODY=$'def calcola(righe):\n    totale = 0\n    for r in righe:\n        imponibile = r["quantita"] * r["prezzo"]\n        sconto = imponibile * r.get("sconto", 0) / 100\n        netto = imponibile - sconto\n        iva = netto * 0.22\n        totale += netto + iva\n    arrotondato = round(totale, 2)\n    return arrotondato\n'
printf '%s' "$BODY" > "$P/services/a/functions/x.py"; printf 'import json\n\n%s' "$BODY" > "$P/services/b/functions/y.py"
dup_out=$(python3 -B "$SC/arch_check.py" "$P" || true)
if echo "$dup_out" | grep -q duplicate_code; then echo "  ok   blocco duplicato rilevato"; else echo "  ERR  duplicati"; FAIL=1; fi
rm -rf "$P/services/a" "$P/services/b"

echo "arch_check (test dei metodi custom):"
cp "$P/$M/Clienti.py" "$P/$M/Clienti.py.orig"
printf '\n    def conta_attivi(self) -> int:\n        return self.count()\n' >> "$P/$M/Clienti.py"
out=$(python3 -B "$SC/arch_check.py" "$P" || true)
if echo "$out" | grep -q "custom_tests.*conta_attivi"; then echo "  ok   metodo custom senza test rilevato"; else echo "  ERR  custom_tests"; FAIL=1; fi
CT="$P/libs/db-models/python/tests/custom/test_clienti_custom.py"
printf '"""TC-Clienti-CONTA-ATTIVI · REQ-Clienti-CONTA"""\nfrom model.Clienti import ClientiRepository\n\n\ndef test_conta_attivi(session):\n    assert ClientiRepository(session).conta_attivi() == 0\n' > "$CT"
out=$(python3 -B "$SC/arch_check.py" "$P" || true)
if echo "$out" | grep -q "custom_tests"; then echo "  ERR  test custom non riconosciuto"; FAIL=1; else echo "  ok   test custom con id TC riconosciuto"; fi
rm -f "$CT"; mv "$P/$M/Clienti.py.orig" "$P/$M/Clienti.py"

echo "stop_gate (file generato manomesso):"
echo "# manomesso" >> "$P/$M/generated/Ordini.py"
out=$(echo "{\"hook_event_name\":\"Stop\",\"session_id\":\"kittest$$\",\"cwd\":\"$P\"}" | CLAUDE_PROJECT_DIR="$P" python3 -B "$SC/stop_gate.py")
if echo "$out" | grep -q '"decision": "block"'; then echo "  ok   chiusura bloccata"; else echo "  ERR  stop gate"; FAIL=1; fi
python3 -B "$SC/gen/gen.py" "$P" --quiet; rm -f "${TMPDIR:-/tmp}"/kybes-stop-kittest$$-*.count

exit $FAIL
