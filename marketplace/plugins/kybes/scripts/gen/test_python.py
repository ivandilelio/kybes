"""Rende il catalogo dei casi di test in pytest per i progetti che usano kybes."""
from __future__ import annotations

from typing import Dict, List

from emit_python import PY_TYPE, _py_value
from naming import header, member, method_name, repo_class
from schema import Table, snake
from verification import METHODS, Catalog, TestCase, table_asil

L = "python"


def _attr(name: str) -> str:
    return member(L, name)


def _sample(t: Table, cn: str) -> str:
    """Espressione Python per un valore valido della colonna (le FK costruiscono il padre)."""
    c = t.col(cn)
    rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == cn), None)
    if rel:
        return f"build_{snake(rel.target)}(session).{_attr(rel_target_pk(rel, t))}"
    if c.type == "string":
        return f"text_value(next_n(), {c.length})"
    return {"uuid": "uuid.uuid4()", "text": "f'testo {next_n()}'",
            "int": "next_n()", "bigint": "next_n()", "decimal": "Decimal(next_n()) + Decimal('0.5')", "bool": "True",
            "date": "date(2026, 1, 1) + timedelta(days=next_n())",
            "datetime": "datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=next_n())", "json": "{'n': next_n()}"}[c.type]


_TABLES: Dict[str, Table] = {}


def rel_target_pk(rel, t: Table) -> str:
    return _TABLES[rel.target].pk.name


def conftest_file() -> str:
    return header(L, "kit") + '''# ruff: noqa
"""Rende disponibili ai test generati le fixture di kybes_fixtures."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kybes_fixtures import engine, isolation_levels, session, session_factory  # noqa: E402,F401
'''


def custom_conftest_file() -> str:
    """Creato una volta in tests/custom/: poi è del progetto."""
    return '''"""Fixture per i test dei metodi custom: le stesse dei test generati (database isolato, builder).

Ogni test custom porta nel docstring l'identificativo del caso (TC-<Tabella>-<CASO>) e il requisito che verifica
(REQ-<Tabella>-<CHIAVE>); il metodo di derivazione segue docs/generated/verification/requirements.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "generated"))

from kybes_fixtures import engine, isolation_levels, session, session_factory  # noqa: E402,F401
'''


def fixtures_file() -> str:
    return header(L, "kit") + '''# ruff: noqa
"""Fixture dei test generati e custom: database isolato per ogni test.

Per default SQLite in memoria; con KYBES_TEST_DATABASE_URL (es. postgresql+psycopg://...) i test girano sul database indicato.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from model.generated import Base  # noqa: E402


@pytest.fixture
def engine():
    url = os.environ.get("KYBES_TEST_DATABASE_URL", "sqlite://")
    if url.startswith(("postgresql://", "postgres://")):  # stesso URL degli altri linguaggi: driver psycopg 3
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    kwargs = {}
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool
        kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    eng = create_engine(url, **kwargs)
    if eng.dialect.name == "sqlite":
        @event.listens_for(eng, "connect")
        def _foreign_keys(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(engine)


@pytest.fixture
def isolation_levels(engine):
    """Nomi dei livelli per il database dei test (SQLite conosce solo SERIALIZABLE)."""
    if engine.dialect.name == "sqlite":
        return {"read_committed": None, "repeatable_read": None, "serializable": "SERIALIZABLE"}
    return None


@pytest.fixture
def session(engine):
    """Sessione legata al tenant di prova A (le tabelle multi-tenant lo richiedono)."""
    from model.generated import bind_tenant
    from kybes_builders import TENANT_A
    with Session(engine) as s:
        bind_tenant(s, TENANT_A)
        yield s
        s.rollback()
'''


_ID_TYPE = ["uuid"]


def _tenant_value(id_type: str, which: str) -> str:
    return f"uuid.UUID('00000000-0000-4000-8000-00000000000{which}')" if id_type == "uuid" else f"'tenant-{which}'"


def builders_file(tables: Dict[str, Table]) -> str:
    _TABLES.clear()
    _TABLES.update(tables)
    o = [header(L, "kit") + "# ruff: noqa", '"""Costruttori di dati validi per i test generati: un record per chiamata, valori deterministici."""',
         "import itertools", "import uuid", "from datetime import date, datetime, timedelta, timezone", "from decimal import Decimal", "",
         "# tenant di prova: la fixture session è legata a TENANT_A",
         f"TENANT_A = {_tenant_value(_ID_TYPE[0], 'a')}", f"TENANT_B = {_tenant_value(_ID_TYPE[0], 'b')}", ""]
    for n in tables:
        o.append(f"from model.{n} import {n}, {repo_class(L, n)}")
    o += ["", "_seq = itertools.count(1)", "", "",
          "def next_n() -> int:", "    return next(_seq)", "", "",
          "def text_value(n: int, length: int) -> str:", '    return f"v{n}"[:length]', "", "",
          "def different(value, length: int = 0):",
          '    """Un valore dello stesso tipo, sicuramente diverso."""',
          "    if isinstance(value, bool):", "        return not value",
          "    if isinstance(value, uuid.UUID):", "        return uuid.uuid4()",
          "    if isinstance(value, (int, Decimal)):", "        return value + 1000003",
          "    if isinstance(value, datetime):", "        return value + timedelta(days=401)",
          "    if isinstance(value, date):", "        return value + timedelta(days=401)",
          "    if isinstance(value, str):",
          '        s = "x" + value',
          "        return s[:length] if length and len(s) > length else (s if s != value else s[:-1] + 'y')",
          "    raise TypeError(type(value))", "", "",
          "def greater(value):",
          "    if isinstance(value, uuid.UUID):", "        return uuid.UUID(int=(1 << 128) - 1)",
          "    if isinstance(value, (int, Decimal)):", "        return value + 1",
          "    if isinstance(value, (date, datetime)):", "        return value + timedelta(days=1)",
          "    if isinstance(value, str):", '        return value + "~"',
          "    raise TypeError(type(value))", "", "",
          "def smaller(value):",
          "    if isinstance(value, uuid.UUID):", "        return uuid.UUID(int=0)",
          "    if isinstance(value, (int, Decimal)):", "        return value - 1",
          "    if isinstance(value, (date, datetime)):", "        return value - timedelta(days=1)",
          "    if isinstance(value, str):", '        return ""',
          "    raise TypeError(type(value))", ""]
    for n, t in tables.items():
        o += ["", f"def build_{snake(n)}(session, **over):", f'    """Inserisce un {n} valido; over sostituisce i valori."""', "    data = {}"]
        for c in t.columns:
            if (c.primary_key and c.auto) or c.generated or c.default is not None or c.tenant:
                continue
            a = _attr(c.name)
            rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == c.name), None)
            if rel:
                if c.required:
                    tpk = _attr(tables[rel.target].pk.name)
                    o.append(f'    if "{a}" not in over:')
                    o.append(f"        data[\"{a}\"] = build_{snake(rel.target)}(session).{tpk}")
                continue
            o.append(f'    data["{a}"] = {_sample(t, c.name)}')
        o += ["    data.update(over)", f"    return {repo_class(L, n)}(session).create({n}(**data))", ""]
    return "\n".join(o).rstrip() + "\n"


def _missing_pk(t: Table) -> str:
    return {"uuid": "uuid.uuid4()", "int": "987654321", "bigint": "987654321", "string": "'kybes-non-esiste'"}[t.pk.type]


def _new_value(t: Table, cn: str) -> str:
    c = t.col(cn)
    if c.type == "string":
        return f"'u' + text_value(next_n(), {max(c.length - 1, 1)})"
    return {"text": "'testo aggiornato'", "int": "next_n() + 500", "bigint": "next_n() + 500", "decimal": "Decimal('99.25')"}[c.type]


def _py_new(t: Table, cn: str) -> str:
    c = t.col(cn)
    if c.type == "string":
        return f"'u' + text_value(next_n(), {max(c.length - 1, 1)})"
    return {"text": "'testo aggiornato'", "int": "next_n() + 500", "bigint": "next_n() + 500", "decimal": "Decimal('99.25')"}[c.type]


def _sort_arg(tc: TestCase) -> str:
    sort = tc.args.get("sort")
    if not sort:
        return ""
    return ", sort='" + ",".join(("-" if x.startswith("-") else "") + member("typescript", x.lstrip("-")) for x in sort) + "'"


def _query_case(t: Table, tc: TestCase, tables: Dict[str, Table]) -> List[str]:
    q = next(x for x in t.queries if x.name == tc.args["query"])
    flip = tc.args.get("flip")
    empty = tc.args.get("empty")
    repo = repo_class(L, t.name)
    lines, over, params, checks, noise = [], [], [], [], []
    for i, c in enumerate(q.where):
        col = t.col(c.column)
        a = _attr(c.column)
        flipped = i == flip
        rel = next((r for r in t.relations if r.kind == "many_to_one" and r.foreign_key == c.column), None)
        if c.has_value:
            lit = _py_value(col, c.value)
            outside, inside = f"{a}=different({lit}, {col.length or 0})", f"{a}={lit}"
            if c.op == "ne":
                outside, inside = inside, outside
            over.append(outside if flipped else inside)
            noise.append(outside)
            checks.append(_py_check(a, c.op, lit))
            continue
        if c.op in ("is_null", "not_null"):
            want_null = (c.op == "is_null") != flipped
            over.append(f"{a}=None" if want_null else f"{a}={_sample(t, c.column)}")
            noise.append(f"{a}=None" if c.op == "not_null" else f"{a}={_sample(t, c.column)}")
            checks.append(_py_check(a, c.op, None))
            continue
        if col.nullable:
            over.append(f"{a}={_sample(t, c.column)}")
        pn = snake(c.param)
        v = f"e.{a}"
        if c.op == "eq":
            expr = f"different({v}, {col.length or 0})" if flipped else v
        elif c.op == "ne":
            expr = v if flipped else f"different({v}, {col.length or 0})"
        elif c.op == "gte":
            expr = f"greater({v})" if flipped else v
        elif c.op == "lte":
            expr = f"smaller({v})" if flipped else v
        elif c.op == "gt":
            expr = v if flipped else f"smaller({v})"
        elif c.op == "lt":
            expr = v if flipped else f"greater({v})"
        elif c.op == "in":
            expr = f"[different({v}, {col.length or 0})]" if flipped else f"[{v}]"
        else:  # prefix
            expr = '"zz"' if flipped else f"{v}[:1]"
        params.append((pn, "[]" if i == empty else expr))
        checks.append(_py_check(a, c.op, pn))
    lines.append(f"    e = build_{snake(t.name)}(session{', ' + ', '.join(over) if over else ''})")
    if flip is None and empty is None and noise:
        lines.append(f"    build_{snake(t.name)}(session, {', '.join(noise)})  # fuori dalla classe: non deve comparire")
    for pn, expr in params:
        lines.append(f"    {pn} = {expr}")
    call_args = ", ".join(pn for pn, _ in params)
    meth = method_name(L, {"page": "query_page", "list": "query_list", "one": "query_one"}[q.returns] + ":" + q.name)
    if q.returns == "page":
        lines.append(f"    rows = {repo}(session).{meth}({call_args + ', ' if call_args else ''}PageRequest(limit={t.pagination.max_limit})).items")
    elif q.returns == "list":
        lines.append(f"    rows = {repo}(session).{meth}({call_args})")
    else:
        lines.append(f"    one = {repo}(session).{meth}({call_args})")
        lines.append("    rows = [one] if one is not None else []")
    pk = _attr(t.pk.name)
    if empty is not None:
        lines.append("    assert list(rows) == []")
    elif flip is None:
        lines.append(f"    assert any(x.{pk} == e.{pk} for x in rows), 'il record che soddisfa le condizioni manca dal risultato'")
        cond = " and ".join(checks)
        lines.append(f"    assert all({cond} for x in rows), 'un record restituito non soddisfa le condizioni'")
    else:
        lines.append(f"    assert all(x.{pk} != e.{pk} for x in rows), 'la condizione {flip + 1} non determina il risultato'")
    return lines


def _py_check(a: str, op: str, val) -> str:
    x = f"x.{a}"
    return {"eq": f"{x} == {val}", "ne": f"{x} != {val}", "lt": f"{x} < {val}", "lte": f"{x} <= {val}", "gt": f"{x} > {val}",
            "gte": f"{x} >= {val}", "in": f"{x} in {val}", "prefix": f"{x}.startswith({val})",
            "is_null": f"{x} is None", "not_null": f"{x} is not None"}[op]


def test_file(t: Table, cat: Catalog, tables: Dict[str, Table], default_asil: str) -> str:
    _TABLES.clear()
    _TABLES.update(tables)
    n = t.name
    repo = repo_class(L, n)
    pk = _attr(t.pk.name)
    tcs = cat.for_table(n)
    o = [header(L, f"schemas/db/{n}.yaml") + "# ruff: noqa",
         f'"""Test di unità generati per {n} (ASIL {table_asil(t, default_asil)}).',
         "", f"Specifica e tracciabilità: docs/generated/verification/{n}.md. I test dei metodi custom vanno in tests/custom/.", '"""',
         "import uuid", "from datetime import date, datetime, timedelta, timezone", "from decimal import Decimal", "",
         "import pytest", "from sqlalchemy.exc import IntegrityError", "",
         "from model.generated import ModelValidationError, PageRequest, TenantError, bind_tenant"]
    others = sorted({r.target for r in t.relations} | {n})
    for o_n in others:
        o.append(f"from model.{o_n} import {o_n}, {repo_class(L, o_n)}")
    o.append("from kybes_builders import (build_" + ", build_".join(snake(x) for x in others) +
             ", different, greater, next_n, smaller, text_value, TENANT_A, TENANT_B)")
    compare = [_attr(c.name) for c in t.columns if c.type not in ("datetime",) and not c.generated]
    for tc in tcs:
        o += ["", "", f"def test_{tc.slug}(session, session_factory):",
              f'    r"""{tc.id} · {", ".join(tc.reqs)} · {METHODS[tc.method]}: {tc.title}. Atteso: {tc.expected}."""']
        k = tc.kind
        if k == "create_valid":
            o += [f"    e = build_{snake(n)}(session)", f"    before = {{a: getattr(e, a) for a in {compare!r}}}",
                  "    session.expire_all()", f"    got = {repo}(session).get_by_id(before['{pk}'])", "    assert got is not None",
                  "    assert {a: getattr(got, a) for a in before} == before"]
        elif k == "read_existing":
            o += [f"    e = build_{snake(n)}(session)", f"    repo = {repo}(session)", f"    assert repo.get_by_id(e.{pk}) is e",
                  f"    assert repo.exists(e.{pk})", "    assert repo.count() >= 1", f"    assert repr(e{'.' + pk if False else ''}).startswith('<{n} ')"]
        elif k == "read_missing":
            o += [f"    repo = {repo}(session)", f"    missing = {_missing_pk(t)}", "    assert repo.get_by_id(missing) is None",
                  "    assert not repo.exists(missing)"]
        elif k == "update_allowed":
            a = _attr(tc.args["column"])
            o += [f"    e = build_{snake(n)}(session)", f"    value = {_new_value(t, tc.args['column'])}",
                  f"    {repo}(session).update(e.{pk}, {{'{a}': value}})", "    session.expire_all()",
                  f"    assert {repo}(session).get_by_id(e.{pk}).{a} == value"]
        elif k == "update_missing":
            o += [f"    assert {repo}(session).update({_missing_pk(t)}, {{}}) is None"]
        elif k == "find_by":
            a = _attr(tc.args["column"])
            meth = method_name(L, "find_by:" + tc.args["column"])
            o += [f"    e = build_{snake(n)}(session)", f"    repo = {repo}(session)", f"    assert repo.{meth}(e.{a}) is e",
                  f"    assert repo.{meth}(different(e.{a}, {t.col(tc.args['column']).length or 0})) is None"]
        elif k == "update_key":
            o += [f"    e = build_{snake(n)}(session)", "    with pytest.raises(ModelValidationError) as err:",
                  f"        {repo}(session).update(e.{pk}, {{'{pk}': {_missing_pk(t)}}})", f"    assert '{pk}' in err.value.fields"]
        elif k == "delete":
            o += [f"    e = build_{snake(n)}(session)", f"    repo = {repo}(session)", f"    assert repo.delete(e.{pk}) is True",
                  f"    assert repo.get_by_id(e.{pk}) is None", f"    assert repo.delete(e.{pk}) is False"]
        elif k == "required_null":
            cn = tc.args["column"]
            o += ["    with pytest.raises(ModelValidationError) as err:", f"        build_{snake(n)}(session, {_attr(cn)}=None)",
                  f"    assert err.value.fields.get('{cn}') == 'obbligatorio'"]
        elif k == "maxlen_at":
            cn, ln = tc.args["column"], tc.args["length"]
            o += [f"    e = build_{snake(n)}(session, {_attr(cn)}='a' * {ln})", f"    assert len(e.{_attr(cn)}) == {ln}"]
        elif k == "maxlen_over":
            cn, ln = tc.args["column"], tc.args["length"]
            o += ["    with pytest.raises(ModelValidationError) as err:", f"        build_{snake(n)}(session, {_attr(cn)}='a' * {ln + 1})",
                  f"    assert '{cn}' in err.value.fields"]
        elif k == "unique_duplicate":
            a = _attr(tc.args["column"])
            o += [f"    e = build_{snake(n)}(session)", "    with pytest.raises(IntegrityError):",
                  f"        build_{snake(n)}(session, {a}=e.{a})", "    session.rollback()"]
        elif k == "default_value":
            c = t.col(tc.args["column"])
            o += [f"    e = build_{snake(n)}(session)", "    session.expire_all()",
                  f"    assert {repo}(session).get_by_id(e.{pk}).{_attr(c.name)} == {_py_value(c, c.default)}"]
        elif k in ("rel_parent", "list_by"):
            r = next(x for x in t.relations if x.name == tc.args["relation"])
            fk = _attr(r.foreign_key)
            tpk = _attr(tables[r.target].pk.name)
            o += [f"    parent = build_{snake(r.target)}(session)", f"    child = build_{snake(n)}(session, {fk}=parent.{tpk})"]
            if k == "rel_parent":
                o += [f"    got = {repo}(session).{method_name(L, 'get_rel:' + r.name)}(child.{pk})",
                      f"    assert got is not None and got.{tpk} == parent.{tpk}",
                      f"    assert {repo}(session).{method_name(L, 'get_rel:' + r.name)}({_missing_pk(t)}) is None"]
            else:
                o += [f"    page = {repo}(session).{method_name(L, 'list_by:' + r.foreign_key)}(parent.{tpk}, PageRequest(limit={t.pagination.max_limit}))",
                      f"    assert any(x.{pk} == child.{pk} for x in page.items)",
                      f"    assert all(x.{fk} == parent.{tpk} for x in page.items)"]
        elif k == "rel_children":
            r = next(x for x in t.relations if x.name == tc.args["relation"])
            ct = tables[r.target]
            fk = _attr(r.foreign_key)
            cpk = _attr(ct.pk.name)
            o += [f"    parent = build_{snake(n)}(session)", f"    child = build_{snake(r.target)}(session, {fk}=parent.{pk})",
                  f"    page = {repo}(session).{method_name(L, 'list_rel:' + r.name)}(parent.{pk}, PageRequest(limit={ct.pagination.max_limit}))",
                  f"    assert any(x.{cpk} == child.{cpk} for x in page.items)", f"    assert all(x.{fk} == parent.{pk} for x in page.items)"]
        elif k == "page_walk":
            o += [f"    built = {{build_{snake(n)}(session).{pk} for _ in range(3)}}", f"    repo = {repo}(session)",
                  "    seen, cursor = [], None", "    for _ in range(100):",
                  "        page = repo.list_page(PageRequest(limit=1, cursor=cursor" + _sort_arg(tc) + "))",
                  f"        seen += [x.{pk} for x in page.items]", "        if not page.has_more:", "            break",
                  "        cursor = page.next_cursor", "    assert built <= set(seen)", "    assert len(seen) == len(set(seen))"]
        elif k == "generated_values":
            cols, upd = tc.args["columns"], tc.args["update"]
            o += [f"    e = build_{snake(n)}(session)", "    session.flush()",
                  "    before = {" + ", ".join(f"'{cn}': e.{_attr(cn)}" for cn, _ in cols) + "}",
                  "    assert all(v is not None for v in before.values()), before"]
            if upd:
                o += [f"    {repo}(session).update(e.{pk}, {{'{_attr(upd)}': {_py_new(t, upd)}}})", "    session.flush()"]
                for cn, g in cols:
                    o.append(f"    assert e.{_attr(cn)} {'==' if g == 'on_create' else '>='} before['{cn}']")
        elif k == "tenant_required":
            o += ["    with session_factory() as unbound:", "        with pytest.raises(TenantError):", f"            {repo}(unbound)"]
        elif k == "tenant_isolation":
            o += [f"    e = build_{snake(n)}(session)", f"    repo = {repo}(session)"]
            kids = [r for r in t.relations if r.kind == "one_to_many" and tables[r.target].tenancy == "column"]
            for r in kids:
                o.append(f"    build_{snake(r.target)}(session, {_attr(r.foreign_key)}=e.{pk})")
            o += ["    bind_tenant(session, TENANT_B)", f"    assert repo.get_by_id(e.{pk}) is None", f"    assert not repo.exists(e.{pk})",
                  "    assert repo.count() == 0", f"    assert e.{pk} not in [x.{pk} for x in repo.list_page().items]",
                  f"    assert repo.update(e.{pk}, {{}}) is None", f"    assert repo.delete(e.{pk}) is False"]
            for c in t.columns:
                if c.unique and not c.primary_key:
                    o.append(f"    assert repo.{method_name(L, 'find_by:' + c.name)}(e.{_attr(c.name)}) is None")
            for r in kids:
                o.append(f"    assert repo.{method_name(L, 'list_rel:' + r.name)}(e.{pk}).items == []")
            o += ["    bind_tenant(session, TENANT_A)", f"    assert repo.get_by_id(e.{pk}) is e"]
        elif k == "tenant_assign":
            tm = _attr(next(c for c in t.columns if c.tenant).name)
            o += [f"    e = build_{snake(n)}(session)", f"    assert e.{tm} == TENANT_A",
                  "    with pytest.raises(ModelValidationError) as err:", f"        build_{snake(n)}(session, {tm}=TENANT_B)",
                  "    assert 'TenantId' in err.value.fields"]
        elif k == "tenant_unique":
            a = _attr(tc.args["column"])
            o += [f"    e = build_{snake(n)}(session)", "    bind_tenant(session, TENANT_B)",
                  f"    other = build_{snake(n)}(session, {a}=e.{a})", f"    assert other.{a} == e.{a} and other.{pk} != e.{pk}"]
        elif k == "tenant_parent":
            r = next(x for x in t.relations if x.name == tc.args["relation"])
            o += ["    bind_tenant(session, TENANT_B)", f"    parent = build_{snake(r.target)}(session)", "    bind_tenant(session, TENANT_A)",
                  "    with pytest.raises(ModelValidationError) as err:",
                  f"        build_{snake(n)}(session, {_attr(r.foreign_key)}=parent.{_attr(tables[r.target].pk.name)})",
                  f"    assert err.value.fields.get('{r.foreign_key}') == 'non trovato'"]
        elif k == "optional_null":
            a = _attr(tc.args["column"])
            o += [f"    e = build_{snake(n)}(session, {a}=None)", "    session.expire_all()",
                  f"    assert {repo}(session).get_by_id(e.{pk}).{a} is None"]
        elif k == "rel_parent_object":
            r = next(x for x in t.relations if x.name == tc.args["relation"])
            fk, rn, tpk = _attr(r.foreign_key), _attr(r.name), _attr(tables[r.target].pk.name)
            o += [f"    parent = build_{snake(r.target)}(session)", f"    child = build_{snake(n)}(session, {fk}=None, {rn}=parent)",
                  f"    assert child.{fk} == parent.{tpk}", "    session.expire_all()",
                  f"    assert {repo}(session).get_by_id(child.{pk}).{fk} == parent.{tpk}"]
        elif k == "page_default":
            o += [f"    e = build_{snake(n)}(session)", f"    repo = {repo}(session)",
                  f"    assert repo.list_page().limit == {t.pagination.default_limit}"]
            for r in t.relations:
                tt = tables[r.target]
                if r.kind == "many_to_one":
                    val = f"e.{_attr(r.foreign_key)}" if t.col(r.foreign_key).required else f"build_{snake(r.target)}(session).{_attr(tt.pk.name)}"
                    o.append(f"    assert repo.{method_name(L, 'list_by:' + r.foreign_key)}({val}).limit == {t.pagination.default_limit}")
                else:
                    o.append(f"    assert repo.{method_name(L, 'list_rel:' + r.name)}(e.{pk}).limit == {tt.pagination.default_limit}")
        elif k == "page_sort_each":
            sorts = [(("-" if x.startswith("-") else "") + member("typescript", x.lstrip("-")), _attr(x.lstrip("-"))) for x in tc.args["sorts"]]
            o += [f"    for _ in range(3):", f"        build_{snake(n)}(session)", f"    repo = {repo}(session)", "    total = repo.count()",
                  f"    for sort, attr in {sorts!r}:",
                  "        seen, values, cursor = [], [], None", "        for _ in range(100):",
                  "            page = repo.list_page(PageRequest(limit=1, cursor=cursor, sort=sort))",
                  f"            seen += [x.{pk} for x in page.items]", "            values += [getattr(x, attr) for x in page.items]",
                  "            if not page.has_more:", "                break", "            cursor = page.next_cursor",
                  "        assert len(seen) == len(set(seen)) == total, sort",
                  "        pairs = list(zip(values, values[1:]))",
                  "        assert all(a >= b for a, b in pairs) if sort.startswith('-') else all(a <= b for a, b in pairs), sort"]
        elif k == "page_limit":
            o += ["    with pytest.raises(ModelValidationError) as err:",
                  f"        {repo}(session).list_page(PageRequest(limit={tc.args['limit']}))", "    assert 'limit' in err.value.fields"]
        elif k == "page_limit_ok":
            o += [f"    build_{snake(n)}(session)", f"    page = {repo}(session).list_page(PageRequest(limit={tc.args['limit']}))",
                  f"    assert page.limit == {tc.args['limit']} and len(page.items) >= 1"]
        elif k == "page_sort_invalid":
            o += ["    with pytest.raises(ModelValidationError) as err:",
                  f"        {repo}(session).list_page(PageRequest(sort='kybesNonOrdinabile'))", "    assert 'sort' in err.value.fields"]
        elif k == "page_cursor_invalid":
            o += ["    with pytest.raises(ModelValidationError) as err:",
                  f"        {repo}(session).list_page(PageRequest(cursor='kybes-non-valido'))", "    assert 'cursor' in err.value.fields"]
        elif k in ("query_match", "query_mcdc", "query_empty_in"):
            o += _query_case(t, tc, tables)
        else:
            raise ValueError(k)
    return "\n".join(o) + "\n"


def runtime_file(cat: Catalog, tables: Dict[str, Table]) -> str:
    first = next(iter(tables.values()))
    bad = "non-un-uuid" if cat.tenant_id_type == "uuid" else "x" * 65
    extra_names = [] if cat.tenant_id_type == "uuid" else [
        "    assert tenant_key('Tenant-A') == 'tenant_a'", "    with pytest.raises(TenantError):", "        tenant_key('nome non valido')"]
    n, repo = first.name, repo_class(L, first.name)
    spec = f"PAGING_{snake(n).upper()}"
    names = list(tables)
    bodies = {
        "rt_exports": ["    import importlib", "    api = importlib.import_module('model.generated')",
                       "    for k in api.__all__:", "        assert getattr(api, k) is not None, k",
                       f"    for n in {names!r}:", "        m = importlib.import_module(f'model.{n}')",
                       "        for k in m.__all__:", "            assert getattr(m, k) is not None, f'{n}.{k}'",
                       "        assert isinstance(getattr(m, n), type) and isinstance(getattr(m, f'{n}Repository'), type)"],
        "rt_sort_key": [f"    order = resolve_order({spec}, '-{member('typescript', first.pk.name)}')",
                        f"    assert order == [('{_attr(first.pk.name)}', '{member('typescript', first.pk.name)}', '{first.pk.type}', True)]"],
        "rt_sort_plus": ["    order = resolve_order(SPEC, '+numero')",
                         "    assert order[0][3] is False and order[-1][0] == 'id'"],
        "rt_cursor_roundtrip": ["    class Row:", "        id = uuid.UUID('00000000-0000-0000-0000-00000000000a')", "        numero = 'A-1'",
                                "        quantita = 7", "        grande = 12345678901", "        prezzo = Decimal('3.25')",
                                "        giorno = date(2026, 2, 3)", "        istante = datetime(2026, 2, 3, 4, 5, 6, tzinfo=timezone.utc)",
                                "    cursor = encode_cursor(ALL, Row())",
                                "    assert decode_cursor(SPEC, ALL, cursor) == [getattr(Row, a) for a, _, _, _ in ALL]"],
        "rt_cursor_types": ["    for bad in ([1, 'x', 1, '1', '1', '2026-01-01', '2026-01-01T00:00:00+00:00'],",
                            "                ['00000000-0000-0000-0000-00000000000a', 'x', 'uno', '1', '1', '2026-01-01', '2026-01-01T00:00:00+00:00'],",
                            "                ['00000000-0000-0000-0000-00000000000a', 'x', 1, 'uno', '1', '2026-01-01', '2026-01-01T00:00:00+00:00'],",
                            "                ['00000000-0000-0000-0000-00000000000a', 'x', 1, '1', 'uno', '2026-01-01', '2026-01-01T00:00:00+00:00'],",
                            "                ['00000000-0000-0000-0000-00000000000a', 'x', 1, '1', '1', '2026-13-01', '2026-01-01T00:00:00+00:00'],",
                            "                ['00000000-0000-0000-0000-00000000000a', 'x', 1, '1', '1', '2026-01-01', 'ieri'],",
                            "                ['00000000-0000-0000-0000-00000000000a', 7, 1, '1', '1', '2026-01-01', '2026-01-01T00:00:00+00:00'],",
                            "                ['00000000-0000-0000-0000-00000000000a', 'x', True, '1', '1', '2026-01-01', '2026-01-01T00:00:00+00:00']):",
                            "        with pytest.raises(ModelValidationError) as err:",
                            "            decode_cursor(SPEC, ALL, raw_cursor(ALL, bad))",
                            "        assert 'cursor' in err.value.fields"],
        "rt_cursor_signature": ["    other = resolve_order(SPEC, '-numero')", "    cursor = raw_cursor(other, ['x', '00000000-0000-0000-0000-00000000000a'])",
                                "    with pytest.raises(ModelValidationError) as err:", "        decode_cursor(SPEC, resolve_order(SPEC, 'numero'), cursor)",
                                "    assert 'cursor' in err.value.fields"],
        "rt_like": ["    assert like_prefix('a%_\\\\') == 'a\\\\%\\\\_\\\\\\\\%'"],
        "rt_fixed_sort": ["    with pytest.raises(ModelValidationError) as err:",
                          f"        run_page(session, select({n}), {spec}, PageRequest(sort='x'), fixed_order=list({spec}.default_order))",
                          "    assert 'sort' in err.value.fields"],
        "rt_empty_page": [f"    page = {repo}(session).list_page(PageRequest(limit=5))", "    assert page.items == [] and page.next_cursor is None"],
        "rt_isolation": ["    assert isolation_for([]) == 'read_committed'", "    assert isolation_for(['kybesSconosciuta']) == 'read_committed'",
                         "    best = max(ISOLATION.values(), key=['read_committed', 'repeatable_read', 'serializable'].index)",
                         "    assert isolation_for(list(ISOLATION)) == best"],
        "rt_isolation_applied": ["    calls = []", "", "    class FakeSession:",
                                 "        def __enter__(self):", "            return self", "",
                                 "        def __exit__(self, *exc):", "            return False", "",
                                 "        def connection(self, execution_options=None):", "            calls.append(execution_options['isolation_level'])", "",
                                 "        def commit(self):", "            pass", "",
                                 "        def rollback(self):", "            pass", "",
                                 "    assert run_in_transaction(FakeSession, lambda s: 1, isolation='serializable') == 1",
                                 "    run_in_transaction(FakeSession, lambda s: 2, isolation='serializable', levels={'serializable': None})",
                                 "    assert calls == ['SERIALIZABLE']"],
        "rt_tenant_bind": ["    with session_factory() as s:", "        with pytest.raises(TenantError):", "            tenant_of(s)",
                           "        bind_tenant(s, TENANT_A)", "        assert tenant_of(s) == TENANT_A",
                           "        bind_tenant(s, str(TENANT_B))", "        assert tenant_of(s) == TENANT_B",
                           "        bind_tenant(s, None)", "        with pytest.raises(TenantError):", "            tenant_of(s)",
                           "        with pytest.raises(TenantError):", f"            bind_tenant(s, {bad!r})",
                           "        with pytest.raises(TenantError):", "            coerce_tenant(None)"],
        "rt_tenant_names": ["    key = tenant_key(TENANT_A)", "    assert key == str(TENANT_A).lower().replace('-', '_')",
                            "    assert schema_for(TENANT_A) == 'tenant_' + key",
                            "    assert search_path_for(TENANT_A) == '\"tenant_' + key + '\", public'",
                            "    assert database_url_for('postgresql://h/app_{tenant}', TENANT_A) == 'postgresql://h/app_' + key",
                            "    with pytest.raises(TenantError):", "        database_url_for('postgresql://h/app', TENANT_A)"] + extra_names,
        "rt_tenant_uow": ["    got = run_in_transaction(session_factory, tenant_of, tenant=TENANT_A, levels=isolation_levels)",
                          "    assert got == TENANT_A",
                          "    pg = run_in_transaction(session_factory, lambda s: s.get_bind().dialect.name != 'postgresql' or",
                          "                            s.scalar(text(\"select current_setting('app.tenant_id', true)\")) == str(TENANT_A),",
                          "                            tenant=TENANT_A, levels=isolation_levels)",
                          "    assert pg",
                          "    # su PostgreSQL app.tenant_id: verificato anche con una sessione finta, qualunque sia il database dei test",
                          "    calls = []", "", "    class Dialect:", "        name = 'postgresql'", "",
                          "    class Bind:", "        dialect = Dialect()", "",
                          "    class FakePg:", "        info = {}", "", "        def get_bind(self):", "            return Bind()", "",
                          "        def execute(self, stmt, params):", "            calls.append(params)", "",
                          "    fake = FakePg()", "    bind_tenant(fake, TENANT_A)", "    apply_tenant_setting(fake)",
                          "    assert calls == [{'tenant': str(TENANT_A)}]"],
        "rt_commit": [f"    key = run_in_transaction(session_factory, lambda s: build_{snake(n)}(s).{_attr(first.pk.name)}, tables=['{n}'], levels=isolation_levels, tenant=TENANT_A)",
                      f"    assert {repo}(session).get_by_id(key) is not None",
                      f"    key = run_in_transaction(session_factory, lambda s: build_{snake(n)}(s).{_attr(first.pk.name)}, isolation='serializable', levels=isolation_levels, tenant=TENANT_A)",
                      f"    assert {repo}(session).get_by_id(key) is not None"],
        "rt_rollback": ["    def work(s):", f"        build_{snake(n)}(s)", "        raise RuntimeError('errore applicativo')",
                        "    with pytest.raises(RuntimeError):", f"        run_in_transaction(session_factory, work, tables=['{n}'], levels=isolation_levels, tenant=TENANT_A)",
                        f"    assert {repo}(session).count() == 0",
                        "    with pytest.raises(RuntimeError):", f"        with transaction(session_factory, ['{n}'], levels=isolation_levels, tenant=TENANT_A) as s:",
                        f"            build_{snake(n)}(s)", "            raise RuntimeError('errore applicativo')",
                        f"    assert {repo}(session).count() == 0"],
        "rt_retry": ["    calls = []", "    def work(s):", "        calls.append(1)", f"        build_{snake(n)}(s)",
                     "        if len(calls) < 3:", "            raise Conflict('40001')", "        return len(calls)",
                     f"    assert run_in_transaction(session_factory, work, tables=['{n}'], levels=isolation_levels, tenant=TENANT_A, backoff_s=0) == 3",
                     f"    assert {repo}(session).count() == 1"],
        "rt_retry_limit": ["    calls = []", "    def work(s):", "        calls.append(1)", "        raise Wrapped(Conflict('40P01'))",
                           "    with pytest.raises(Wrapped):",
                           "        run_in_transaction(session_factory, work, levels=isolation_levels, tenant=TENANT_A, max_retries=2, backoff_s=0)",
                           "    assert len(calls) == 3"],
        "rt_retry_other": ["    calls = []", "    def work(s):", "        calls.append(1)", "        raise Conflict('23505')",
                           "    with pytest.raises(Conflict):", "        run_in_transaction(session_factory, work, levels=isolation_levels, tenant=TENANT_A, backoff_s=0)",
                           "    assert len(calls) == 1"],
    }
    o = [header(L, "kit") + "# ruff: noqa", '"""Test di unità generati per i moduli comuni: paginazione (_paging) e Unit of Work (_uow)."""',
         "import base64", "import json", "import uuid", "from datetime import date, datetime, timezone", "from decimal import Decimal", "",
         "import pytest", "from sqlalchemy import select", "",
         "from model.generated import ModelValidationError, PageRequest",
         "from model.generated._paging import PagingSpec, decode_cursor, encode_cursor, like_prefix, resolve_order, run_page",
         "from model.generated._uow import ISOLATION, isolation_for, run_in_transaction, transaction",
         "from model.generated._tenant import (KEY, TenantError, apply_tenant_setting, bind_tenant, coerce_tenant, database_url_for,",
         "                                     schema_for, search_path_for, tenant_key, tenant_of)",
         "from sqlalchemy import text",
         f"from model.generated.{n} import {n}, {spec}", f"from model.{n} import {repo}", f"from kybes_builders import build_{snake(n)}, TENANT_A, TENANT_B", "",
         "ALL = [('numero', 'numero', 'string', False), ('quantita', 'quantita', 'int', False), ('grande', 'grande', 'bigint', False),",
         "       ('prezzo', 'prezzo', 'decimal', True), ('giorno', 'giorno', 'date', False), ('istante', 'istante', 'datetime', True),",
         "       ('id', 'id', 'uuid', False)]",
         "ALL = [ALL[-1]] + ALL[:-1]",
         "SPEC = PagingSpec(table='Prova', entity=None, pk=('id', 'id', 'uuid'), sortable={'numero': ('numero', 'string')},",
         "                  default_order=[('id', 'id', 'uuid', False)])", "", "",
         "def raw_cursor(order, values):",
         '    sig = ",".join(("-" if d else "") + j for _, j, _, d in order)',
         '    raw = json.dumps({"s": sig, "v": values}).encode()',
         '    return base64.urlsafe_b64encode(raw).decode().rstrip("=")', "", "",
         "class Conflict(Exception):", "    def __init__(self, code):", "        super().__init__(code)", "        self.sqlstate = code", "", "",
         "class Wrapped(Exception):", '    """Errore del driver avvolto, come fa SQLAlchemy (orig)."""', "    def __init__(self, orig):",
         "        super().__init__(str(orig))", "        self.orig = orig"]
    for tc in cat.for_table("_runtime"):
        o += ["", "", f"def test_{tc.slug}(session, session_factory, isolation_levels):",
              f'    r"""{tc.id} · {", ".join(tc.reqs)} · {METHODS[tc.method]}: {tc.title}. Atteso: {tc.expected}."""']
        o += bodies[tc.kind]
    return "\n".join(o) + "\n"


CUSTOM_ONCE = {"custom/conftest.py": custom_conftest_file}


def emit(cat: Catalog, tables: Dict[str, Table], default_asil: str) -> Dict[str, str]:
    """File relativi alla cartella dei test del pacchetto Python (es. libs/db-models/python/tests)."""
    _ID_TYPE[0] = cat.tenant_id_type
    files = {"generated/conftest.py": conftest_file(), "generated/kybes_fixtures.py": fixtures_file(),
             "generated/kybes_builders.py": builders_file(tables)}
    for n, t in tables.items():
        files[f"generated/test_{snake(n)}.py"] = test_file(t, cat, tables, default_asil)
    files["generated/test_kybes_runtime.py"] = runtime_file(cat, tables)
    return files
