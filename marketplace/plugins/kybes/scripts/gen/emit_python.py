"""Emettitore Python: SQLAlchemy 2.0 (Declarative + Mapped)."""
from __future__ import annotations

from typing import Dict, List, Tuple

import runtime_archive
import runtime_mongo
import runtime_python
import runtime_tenant
from naming import GEN_DIR, base_class, custom_file, header, member, method_name, repo_class
from schema import Table, index_specs, methods_of, snake, tenant_column

L = "python"

PY_TYPE = {"uuid": "uuid.UUID", "string": "str", "text": "str", "int": "int", "bigint": "int",
           "decimal": "Decimal", "bool": "bool", "date": "date", "datetime": "datetime", "json": "Any"}


def _sa_type(c) -> str:
    return {"uuid": "Uuid", "string": f"String({c.length})", "text": "Text", "int": "Integer",
            "bigint": "BigInteger", "decimal": f"Numeric({c.precision}, {c.scale})", "bool": "Boolean",
            "date": "Date", "datetime": "DateTime(timezone=True)", "json": "JSON"}[c.type]


def _lit(v) -> str:
    return repr(v)


def _table_file(t: Table, tables: Dict[str, Table], schema_rel: str) -> str:
    m = {c.name: member(L, c.name) for c in t.columns}
    pk = t.pk
    pkm, pkt = m[pk.name], PY_TYPE[pk.type]
    fks = {r.foreign_key: r for r in t.relations if r.kind == "many_to_one"}
    targets = sorted({r.target for r in t.relations if r.target != t.name})
    L_ = []
    w = L_.append
    w(header(L, schema_rel) + "# ruff: noqa")
    w(f'"""{t.name}: entità, CRUD e relazioni (tabella {t.db_name}).{(" " + t.description) if t.description else ""}"""')
    w("from __future__ import annotations\n")
    w("import uuid")
    w("from datetime import date, datetime, timezone")
    w("from decimal import Decimal")
    w("from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence\n")
    w("from sqlalchemy import (JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric,")
    w("                        String, Text, UniqueConstraint, Uuid, func, select)")
    w("from sqlalchemy.orm import Mapped, Session, mapped_column, relationship\n")
    w("from ._base import Base, ModelValidationError")
    w("from ._paging import Page, PageRequest, PagingSpec, like_prefix, order_rows, run_page")
    tc = tenant_column(t)
    tm = m[tc.name] if tc else None
    if t.tenancy != "none":
        w("from ._tenant import tenant_of")
    rt = bool(t.archive and t.archive.read_through)
    if rt:
        decs = sorted({runtime_archive.PY_DECODE[c.type] for c in t.columns if c.type in runtime_archive.PY_DECODE})
        w("from ._archive import " + ", ".join(decs + ["read_archived"]))
    if targets:
        w("\nif TYPE_CHECKING:")
        for tg in targets:
            w(f"    from .{tg} import {tg}")
    w("\n")
    w(f"class {t.name}(Base):")
    w(f'    __tablename__ = "{t.db_name}"')
    ix = []
    for s in index_specs(t):
        cols = ", ".join(repr(t.col(c).db_name) for c in s.columns)
        ix.append(f'UniqueConstraint({cols}, name="{s.name}")' if s.unique else f'Index("{s.name}", {cols})')
    if ix:
        w(f"    __table_args__ = ({', '.join(ix)},)")
    w("")
    for c in t.columns:
        sa_t = _sa_type(c)
        if c.primary_key and c.auto and c.type == "bigint":
            sa_t = 'BigInteger().with_variant(Integer, "sqlite")'  # SQLite autoincrementa solo INTEGER
        args = [f'"{c.db_name}"', sa_t]
        if c.name in fks:
            r = fks[c.name]
            tg = tables[r.target]
            od = {"restrict": "RESTRICT", "cascade": "CASCADE", "set_null": "SET NULL"}[r.on_delete]
            args.append(f'ForeignKey("{tg.db_name}.{tg.pk.db_name}", ondelete="{od}")')
        if c.primary_key:
            args.append("primary_key=True")
            if c.auto and c.type == "uuid":
                args.append("default=uuid.uuid4")
            elif c.auto:
                args.append("autoincrement=True")
            elif c.type in ("int", "bigint"):
                args.append("autoincrement=False")
        args.append(f"nullable={c.nullable}")
        if c.default is not None:
            args.append(f"default={_lit(c.default)}")
        if c.generated == "on_create":
            args.append("default=lambda: datetime.now(timezone.utc)")
        if c.generated == "on_update":
            args.append("default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)")
        typ = PY_TYPE[c.type] if not c.nullable else f"Optional[{PY_TYPE[c.type]}]"
        w(f"    {m[c.name]}: Mapped[{typ}] = mapped_column({', '.join(args)})")
    for r in t.relations:
        rn = member(L, r.name)
        if r.kind == "many_to_one":
            fkc = t.col(r.foreign_key)
            typ = f'"{r.target}"' if fkc.required else f'Optional["{r.target}"]'
            bp = f', back_populates="{member(L, r.inverse)}"' if r.inverse else ""
            rs = f", remote_side=[{pkm}]" if r.target == t.name else ""
            w(f'    {rn}: Mapped[{typ}] = relationship("{r.target}", foreign_keys=[{m[r.foreign_key]}]{rs}{bp})')
        else:
            casc = ', cascade="all, delete-orphan", passive_deletes=True' if r.on_delete == "cascade" else ""
            fkx = f'foreign_keys="{r.target}.{member(L, r.foreign_key)}"'
            w(f'    {rn}: Mapped[List["{r.target}"]] = relationship("{r.target}", {fkx}, back_populates="{member(L, r.inverse)}"{casc})')
    w("")
    w(f"    def __repr__(self) -> str:")
    w(f'        return f"<{t.name} {pkm}={{self.{pkm}!r}}>"')
    w("\n")

    L_ += _validation_lines(t, m) + _paging_lines(t, m)

    # ---- repository
    cols_updatable = [m[c.name] for c in t.columns if not c.primary_key and not c.generated and not c.tenant]
    T = t.name

    def scoped(expr: str) -> str:
        """Con tenancy: column ogni lettura filtra per il tenant della sessione."""
        return f"self._scoped({expr})" if tc else expr

    hot_get = f"self.session.scalars(self._scoped(select({T}).where({T}.{pkm} == id))).first()" if tc else f"self.session.get({T}, id)"
    get_entity = hot_get  # aggiornamento e cancellazione lavorano solo sulla tabella hot
    parents = [r for r in t.relations if r.kind == "many_to_one" and tables[r.target].tenancy == "column"] if tc else []
    w(f"class {base_class(L, t.name)}:")
    w(f'    """CRUD, relazioni e query di {t.name}. La transazione la gestisce il chiamante (vedi _uow.py)."""\n')
    w(f"    UPDATABLE = frozenset({{{', '.join(repr(x) for x in cols_updatable)}}})")
    w(f"    PAGING = PAGING_{snake(t.name).upper()}\n")
    w("    def __init__(self, session: Session) -> None:")
    w("        self.session = session")
    if t.tenancy != "none":
        w(f"        tenant_of(session)  # tenancy: {t.tenancy}: senza un tenant legato alla sessione il repository non lavora")
    w("")
    if tc:
        w("    def _scoped(self, stmt):")
        w(f"        return stmt.where({T}.{tm} == tenant_of(self.session))\n")
        w("    def _check_tenant(self, entity) -> None:")
        w('        """Il record appartiene al tenant della sessione; i record collegati anche."""')
        w("        tenant = tenant_of(self.session)")
        w(f"        if entity.{tm} is not None and entity.{tm} != tenant:")
        w(f'            raise ModelValidationError("{T}", {{"{tc.name}": "tenant diverso da quello della sessione"}})')
        w(f"        entity.{tm} = tenant")
        if parents:
            w("        errors: Dict[str, str] = {}")
            w("        with self.session.no_autoflush:  # il record non è ancora nella sessione")
            for r in parents:
                tg = tables[r.target]
                fk = m[r.foreign_key]
                imp = "" if r.target == T else f"        from .{r.target} import {r.target}\n"
                if imp:
                    w("    " + imp.rstrip("\n"))
                tpk, ttm = member(L, tg.pk.name), member(L, tenant_column(tg).name)
                w(f"            if entity.{fk} is not None and self.session.scalar(select({r.target}.{tpk}).where({r.target}.{tpk} == entity.{fk}, {r.target}.{ttm} == tenant)) is None:")
                w(f'                errors["{r.foreign_key}"] = "non trovato"')
            w("        if errors:")
            w(f'            raise ModelValidationError("{T}", errors)')
        w("")
    for meth in methods_of(t):
        k, _, arg = meth.key.partition(":")
        name = method_name(L, meth.key)
        w(f"    # {meth.summary}")
        if k == "get_by_id":
            w(f"    def {name}(self, id: {pkt}) -> Optional[{t.name}]:")
            if rt:
                w(f"        found = {hot_get}")
                w("        return found if found is not None else self._from_archive(id)\n")
                ten = "tenant_of(self.session)" if t.tenancy != "none" else "None"
                w(f"    def _from_archive(self, id: {pkt}) -> Optional[{t.name}]:")
                w('        """Record archiviato (archive.read_through): oggetto non collegato alla sessione, in sola lettura."""')
                w(f'        doc = read_archived(self.session, "{t.db_name}", {ten}, id)')
                w("        if doc is None:")
                w("            return None")
                args = []
                for c in t.columns:
                    dec = runtime_archive.PY_DECODE.get(c.type)
                    v = f'doc.get("{c.name}")'
                    args.append(f"{m[c.name]}={dec}({v})" if dec else f"{m[c.name]}={v}")
                w(f"        return {T}(")
                for i, a in enumerate(args):
                    w(f"            {a}" + ("," if i < len(args) - 1 else ")\n"))
            else:
                w(f"        return {hot_get}\n")
        elif k == "list_page":
            w(f"    def {name}(self, page: PageRequest = PageRequest()) -> Page[{t.name}]:")
            w(f"        return run_page(self.session, {scoped(f'select({T})')}, self.PAGING, page)\n")
        elif k == "count":
            w(f"    def {name}(self) -> int:")
            w(f"        return int(self.session.scalar({scoped(f'select(func.count()).select_from({T})')}) or 0)\n")
        elif k == "exists":
            w(f"    def {name}(self, id: {pkt}) -> bool:")
            w(f"        return self.session.scalar({scoped(f'select({T}.{pkm}).where({T}.{pkm} == id)')}) is not None\n")
        elif k == "create":
            w(f"    def {name}(self, entity: {t.name}) -> {t.name}:")
            for r in t.relations:
                if r.kind == "many_to_one":
                    rn, fk = member(L, r.name), m[r.foreign_key]
                    tpk = member(L, tables[r.target].pk.name)
                    w(f"        if entity.{rn} is not None:  # collegato come oggetto: la chiave segue l'oggetto")
                    w(f"            entity.{fk} = entity.{rn}.{tpk}")
            if tc:
                w("        self._check_tenant(entity)")
            w(f"        validate_{snake(t.name)}(entity)")
            w("        self.session.add(entity)")
            w("        self.session.flush()")
            w("        return entity\n")
        elif k == "update":
            w(f"    def {name}(self, id: {pkt}, changes: Dict[str, Any]) -> Optional[{t.name}]:")
            w("        unknown = set(changes) - self.UPDATABLE")
            w("        if unknown:")
            w(f'            raise ModelValidationError("{t.name}", {{k: "campo non modificabile" for k in sorted(unknown)}})')
            w(f"        entity = {get_entity}")
            w("        if entity is None:")
            w("            return None")
            w("        for key, value in changes.items():")
            w("            setattr(entity, key, value)")
            if tc:
                w("        self._check_tenant(entity)")
            w(f"        validate_{snake(t.name)}(entity)")
            w("        self.session.flush()")
            w("        return entity\n")
        elif k == "delete":
            w(f"    def {name}(self, id: {pkt}) -> bool:")
            w(f"        entity = {get_entity}")
            w("        if entity is None:")
            w("            return False")
            w("        self.session.delete(entity)")
            w("        self.session.flush()")
            w("        return True\n")
        elif k == "find_by":
            c = t.col(arg)
            w(f"    def {name}(self, value: {PY_TYPE[c.type]}) -> Optional[{t.name}]:")
            w(f"        return self.session.scalars({scoped(f'select({T}).where({T}.{m[arg]} == value)')}).first()\n")
        elif k == "list_by":
            c = t.col(arg)
            w(f"    def {name}(self, value: {PY_TYPE[c.type]}, page: PageRequest = PageRequest()) -> Page[{t.name}]:")
            w(f"        return run_page(self.session, {scoped(f'select({T}).where({T}.{m[arg]} == value)')}, self.PAGING, page)\n")
        elif k == "get_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f'    def {name}(self, id: {pkt}) -> "Optional[{r.target}]":')
            w(f"        entity = {get_entity}")
            w(f"        return entity.{member(L, r.name)} if entity is not None else None\n")
        elif k == "list_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f'    def {name}(self, id: {pkt}, page: PageRequest = PageRequest()) -> "Page[{r.target}]":')
            if r.target != t.name:
                w(f"        from .{r.target} import {r.target}, PAGING_{snake(r.target).upper()}")
            w(f"        stmt = select({r.target}).where({r.target}.{member(L, r.foreign_key)} == id)")
            ctc = tenant_column(tables[r.target])
            if ctc:
                w(f"        stmt = stmt.where({r.target}.{member(L, ctc.name)} == tenant_of(self.session))")
            w(f"        return run_page(self.session, stmt, PAGING_{snake(r.target).upper()}, page)\n")
        elif k in ("query_page", "query_list", "query_one"):
            q = next(x for x in t.queries if x.name == arg)
            params = []
            conds = []
            for c in q.where:
                col = t.col(c.column)
                attr = f"{t.name}.{m[c.column]}"
                if c.param:
                    pn = snake(c.param)
                    pt = f"Sequence[{PY_TYPE[col.type]}]" if c.op == "in" else PY_TYPE[col.type]
                    params.append(f"{pn}: {pt}")
                    val = pn
                else:
                    val = _py_value(col, c.value) if c.has_value else None
                conds.append(_py_cond(attr, c.op, val))
            sig = ", ".join(["self"] + params)
            where = ", ".join(conds)
            order = [(m[cn], member("typescript", cn), t.col(cn).type, d) for cn, d in t.order(q.order_by or None)]
            order_lit = "[" + ", ".join(f'("{a}", "{j}", "{ty}", {d})' for a, j, ty, d in order) + "]"
            if k == "query_page":
                w(f"    def {name}({sig}, page: PageRequest = PageRequest()) -> Page[{t.name}]:")
                w(f"        stmt = {scoped(f'select({T}).where({where})')}")
                w(f"        return run_page(self.session, stmt, self.PAGING, page, fixed_order={order_lit})\n")
            elif k == "query_list":
                w(f"    def {name}({sig}) -> List[{t.name}]:")
                w(f"        stmt = {scoped(f'select({T}).where({where})')}")
                w(f"        stmt = order_rows(stmt, self.PAGING, {order_lit}).limit(self.PAGING.max_limit)")
                w("        return list(self.session.scalars(stmt))\n")
            else:
                w(f"    def {name}({sig}) -> Optional[{t.name}]:")
                w(f"        stmt = {scoped(f'select({T}).where({where})')}")
                w(f"        return self.session.scalars(order_rows(stmt, self.PAGING, {order_lit}).limit(1)).first()\n")
    return "\n".join(L_).rstrip() + "\n"


def _validation_lines(t: Table, m: Dict[str, str]) -> List[str]:
    L_: List[str] = []
    w = L_.append
    pk = t.pk
    pkm = m[pk.name]
    # ---- validazione
    w(f"def validate_{snake(t.name)}(e: {t.name}) -> None:")
    w(f'    """Validazione di modello prima della persistenza (lo schema JSON valida a monte la API)."""')
    w("    errors: Dict[str, str] = {}")
    for c in t.columns:
        mm = m[c.name]
        if c.tenant:
            continue  # impostata dal repository con il tenant della sessione
        if c.required and not (c.primary_key and c.auto) and not c.generated and c.default is None:
            w(f"    if e.{mm} is None:")
            w(f'        errors["{c.name}"] = "obbligatorio"')
        elif c.required and not c.generated and c.default is not None:
            # assente: vale il default all'inserimento; None esplicito: rifiutato
            w(f'    if "{mm}" in vars(e) and e.{mm} is None:')
            w(f'        errors["{c.name}"] = "obbligatorio"')
        if c.type == "string":
            w(f"    if e.{mm} is not None and len(e.{mm}) > {c.length}:")
            w(f'        errors["{c.name}"] = "lunghezza massima {c.length}"')
    w("    if errors:")
    w(f'        raise ModelValidationError("{t.name}", errors)')
    w("\n")

    return L_


def _paging_lines(t: Table, m: Dict[str, str]) -> List[str]:
    L_: List[str] = []
    w = L_.append
    pk = t.pk
    pkm = m[pk.name]
    # ---- paginazione
    w(f"PAGING_{snake(t.name).upper()} = PagingSpec(")
    w(f'    table="{t.name}",')
    w(f'    entity={t.name},')
    w(f'    pk=("{pkm}", "{member("typescript", pk.name)}", "{pk.type}"),')
    sortable = ", ".join(f'"{member("typescript", cn)}": ("{m[cn]}", "{t.col(cn).type}")' for cn in t.pagination.sortable)
    w(f"    sortable={{{sortable}}},")
    order = ", ".join(f'("{m[cn]}", "{member("typescript", cn)}", "{t.col(cn).type}", {d})' for cn, d in t.order())
    w(f"    default_order=[{order}],")
    w(f"    default_limit={t.pagination.default_limit},")
    w(f"    max_limit={t.pagination.max_limit},")
    w(")\n\n")

    return L_


def _py_value(col, v) -> str:
    if v is None:
        return "None"
    if col.type == "uuid":
        return f"uuid.UUID({str(v)!r})"
    if col.type == "decimal":
        return f"Decimal({str(v)!r})"
    if col.type == "date":
        return f"date.fromisoformat({str(v)!r})"
    if col.type == "datetime":
        return f"datetime.fromisoformat({str(v)!r})"
    if isinstance(v, list):
        return "[" + ", ".join(_py_value(col, x) for x in v) + "]"
    return repr(v)


def _py_cond(attr: str, op: str, val) -> str:
    return {"eq": f"{attr} == {val}", "ne": f"{attr} != {val}", "lt": f"{attr} < {val}", "lte": f"{attr} <= {val}",
            "gt": f"{attr} > {val}", "gte": f"{attr} >= {val}", "in": f"{attr}.in_({val})",
            "prefix": f"{attr}.like(like_prefix({val}), escape=\"\\\\\")",
            "is_null": f"{attr}.is_(None)", "not_null": f"{attr}.is_not(None)"}[op]


def _base_file() -> str:
    return (header(L, "kit") + "# ruff: noqa\n" +
            '"""Base dichiarativa comune ed errore di validazione dei modelli."""\n'
            "from __future__ import annotations\n\n"
            "from typing import Dict\n\n"
            "from sqlalchemy.orm import DeclarativeBase\n\n\n"
            "class Base(DeclarativeBase):\n"
            "    pass\n\n\n"
            "class ModelValidationError(ValueError):\n"
            '    """Dati non validi per la tabella: fields contiene campo -> regola violata (mai valori)."""\n\n'
            "    def __init__(self, table: str, fields: Dict[str, str]) -> None:\n"
            '        super().__init__(f"{table}: dati non validi ({\', \'.join(sorted(fields))})")\n'
            "        self.table = table\n"
            "        self.fields = fields\n")


def _init_file(tables: Dict[str, Table]) -> str:
    lines = [header(L, "kit") + "# ruff: noqa\n" + '"""Registra tutti i modelli generati (necessario per le relazioni)."""',
             "from ._base import Base, ModelValidationError",
             "from ._paging import Page, PageRequest",
             "from ._uow import isolation_for, run_in_transaction, transaction",
             "from ._tenant import TenantError, bind_tenant, database_url_for, schema_for, search_path_for, tenant_of",
             "from ._archive import ArchiveReader, FileArchiveReader, archive_of, archive_path, bind_archive"]
    for n in tables:
        lines.append(f"from .{n} import {n}, {base_class(L, n)}, validate_{snake(n)}, PAGING_{snake(n).upper()}")
    names = ["Base", "ModelValidationError", "Page", "PageRequest", "isolation_for", "run_in_transaction", "transaction",
             "TenantError", "bind_tenant", "database_url_for", "schema_for", "search_path_for", "tenant_of",
             "ArchiveReader", "FileArchiveReader", "archive_of", "archive_path", "bind_archive"] + \
        [x for n in tables for x in (n, base_class(L, n), f"validate_{snake(n)}", f"PAGING_{snake(n).upper()}")]
    mongo = [n for n, t in tables.items() if t.mongo]
    if mongo:
        lines.append("from ._mongo import MongoSession, mongo_session, run_in_mongo_transaction")
        for n in mongo:
            lines.append(f"from .{n} import ensure_indexes_{snake(n)}")
        names += ["MongoSession", "mongo_session", "run_in_mongo_transaction", "ensure_mongo_indexes"]
        lines += ["", "", "def ensure_mongo_indexes(db) -> None:",
                  '    """Crea gli indici di tutte le collection MongoDB del modello (idempotente)."""']
        lines += [f"    ensure_indexes_{snake(n)}(db)" for n in mongo]
    lines.append("\n__all__ = [" + ", ".join(repr(x) for x in names) + "]")
    return "\n".join(lines) + "\n"


def custom_stub(t: Table) -> str:
    return ("# ruff: noqa: N999  (nome del modulo = nome della tabella, per convenzione del kit)\n"
            f'"""{t.name}: punto d\'ingresso per l\'accesso ai dati della tabella {t.db_name}.\n\n'
            f"CRUD e relazioni sono ereditati da generated/{t.name}.py (vedi MODEL_INDEX.md).\n"
            f'Qui vanno SOLO i metodi custom di questa tabella, con nomi diversi da quelli generati.\n"""\n'
            "from __future__ import annotations\n\n"
            f"from .generated.{t.name} import {t.name}, {base_class(L, t.name)}\n\n"
            f'__all__ = ["{t.name}", "{repo_class(L, t.name)}"]\n\n\n'
            f"class {repo_class(L, t.name)}({base_class(L, t.name)}):\n"
            f'    """Metodi custom di {t.name}."""\n')


def emit(tables: Dict[str, Table], schema_rel: Dict[str, str], opts: Dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Restituisce (file generati, file custom da creare se mancano) con percorsi relativi alla cartella model."""
    gen = {f"{GEN_DIR}/_base.py": _base_file(), f"{GEN_DIR}/__init__.py": _init_file(tables),
           f"{GEN_DIR}/_paging.py": runtime_python.paging_file(), f"{GEN_DIR}/_uow.py": runtime_python.uow_file(tables),
           f"{GEN_DIR}/_tenant.py": runtime_tenant.python_file(opts.get("tenant_id_type", "uuid")),
           f"{GEN_DIR}/_archive.py": runtime_archive.python_file()}
    for n, t in tables.items():
        gen[f"{GEN_DIR}/{n}.py"] = (_mongo_table_file if t.mongo else _table_file)(t, tables, schema_rel[n])
    if any(t.mongo for t in tables.values()):
        gen[f"{GEN_DIR}/_mongo.py"] = runtime_mongo.python_file()
    custom = {custom_file(L, n): custom_stub(t) for n, t in tables.items()}
    custom["__init__.py"] = '"""Modelli e repository: un file per tabella (vedi MODEL_INDEX.md)."""\n'
    return gen, custom


# ------------------------------------------------------------------------------------------- MongoDB

def _mongo_cond(t: Table, c, val: str) -> str:
    """Condizione di una query dichiarata come filtro MongoDB (valori già convertiti con to_bson)."""
    import mongo_plan
    f = repr(mongo_plan.field_name(t, t.col(c.column)))
    return {"eq": f"{{{f}: {val}}}", "ne": f"{{{f}: {{'$nin': [{val}, None]}}}}", "lt": f"{{{f}: {{'$lt': {val}}}}}",
            "lte": f"{{{f}: {{'$lte': {val}}}}}", "gt": f"{{{f}: {{'$gt': {val}}}}}", "gte": f"{{{f}: {{'$gte': {val}}}}}",
            "in": f"{{{f}: {{'$in': {val}}}}}", "prefix": f"{{{f}: prefix({val})}}",
            "is_null": f"{{{f}: None}}", "not_null": f"{{{f}: {{'$ne': None}}}}"}[c.op]


def _mongo_table_file(t: Table, tables: Dict[str, Table], schema_rel: str) -> str:
    import mongo_plan
    m = {c.name: member(L, c.name) for c in t.columns}
    pk = t.pk
    pkm, pkt = m[pk.name], PY_TYPE[pk.type]
    T = t.name
    tc = tenant_column(t)
    fields = {m[c.name]: mongo_plan.field_name(t, c) for c in t.columns}
    L_: List[str] = []
    w = L_.append
    w(header(L, schema_rel) + "# ruff: noqa")
    w(f'"""{T}: entità e repository della collection MongoDB {t.db_name}.{(" " + t.description) if t.description else ""}"""')
    w("from __future__ import annotations\n")
    w("import uuid")
    w("from datetime import date, datetime, timezone")
    w("from decimal import Decimal")
    w("from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence\n")
    w("from ._base import ModelValidationError")
    w("from ._mongo import MongoSession, find_sorted, from_bson, next_id, now_ms, prefix, run_mongo_page, to_bson")
    w("from ._paging import Page, PageRequest, PagingSpec")
    if t.tenancy != "none":
        w("from ._tenant import tenant_of")
    targets = sorted({r.target for r in t.relations if r.target != T})
    if targets:
        w("\nif TYPE_CHECKING:")
        for tg in targets:
            w(f"    from .{tg} import {tg}")
    w("\n")
    # ---- entità
    w(f"class {T}:")
    w(f'    """Documento della collection {t.db_name}. I valori non indicati valgono il default dello schema o None."""\n')
    for c in t.columns:
        typ = PY_TYPE[c.type] if not c.nullable else f"Optional[{PY_TYPE[c.type]}]"
        w(f"    {m[c.name]}: {typ} = {_lit(c.default) if c.default is not None else 'None'}")
    w("")
    w("    def __init__(self, **values: Any) -> None:")
    w("        for key, value in values.items():")
    w(f"            FIELDS_{snake(T).upper()}[key]  # KeyError per un campo che la collection non ha")
    w("            setattr(self, key, value)\n")
    w("    def __repr__(self) -> str:")
    w(f'        return f"<{T} {pkm}={{self.{pkm}!r}}>"')
    w("\n")
    L_ += _validation_lines(t, m) + _paging_lines(t, m)
    w(f"FIELDS_{snake(T).upper()} = {{" + ", ".join(f'"{a}": "{f}"' for a, f in fields.items()) + "}\n\n")
    w(f"def to_document(e: {T}) -> Dict[str, Any]:")
    w('    """Documento MongoDB del record: le colonne vuote non compaiono."""')
    w("    doc = {" + ", ".join(f'"{fields[m[c.name]]}": to_bson(e.{m[c.name]}, "{c.type}")' for c in t.columns) + "}")
    w("    return {k: v for k, v in doc.items() if v is not None}\n\n")
    w(f"def from_document(d: Dict[str, Any]) -> {T}:")
    w(f"    return {T}(" + ", ".join(f'{m[c.name]}=from_bson(d.get("{fields[m[c.name]]}"), "{c.type}")' for c in t.columns) + ")\n\n")
    w(f"def ensure_indexes_{snake(T)}(db: Any) -> None:")
    w(f'    """Indici della collection (stessi nomi del DDL SQL); idempotente: si chiama all\'avvio o nel deploy."""')
    w(f'    col = db["{t.db_name}"]')
    ixs = mongo_plan.indexes(t)
    if not ixs:
        w("    del col  # nessun indice oltre a _id")
    for ix in ixs:
        args = [f'name="{ix.name}"']
        if ix.unique:
            args.append("unique=True")
        if ix.partial:
            args.append("partialFilterExpression={" + ", ".join(f'"{f}": {{"$exists": True}}' for f in ix.partial) + "}")
        if ix.ttl is not None:
            args.append(f"expireAfterSeconds={ix.ttl}")
        keys = "[" + ", ".join(f'("{f}", 1)' for f in ix.fields) + "]"
        w(f"    col.create_index({keys}, {', '.join(args)})")
    w("\n")

    # ---- repository
    updatable = [m[c.name] for c in t.columns if not c.primary_key and not c.generated and not c.tenant]
    parents = [r for r in t.relations if r.kind == "many_to_one"]
    kids = mongo_plan.children(t, tables)
    w(f"class {base_class(L, T)}:")
    w(f'    """CRUD, relazioni e query di {T} su MongoDB. Le transazioni le apre il chiamante (run_in_mongo_transaction)."""\n')
    w(f"    UPDATABLE = frozenset({{{', '.join(repr(x) for x in updatable)}}})")
    w(f"    PAGING = PAGING_{snake(T).upper()}")
    w(f'    COLLECTION = "{t.db_name}"')
    w(f"    FIELDS = FIELDS_{snake(T).upper()}\n")
    w("    def __init__(self, session: MongoSession) -> None:")
    w("        self.session = session")
    if t.tenancy != "none":
        w(f"        tenant_of(session)  # tenancy: {t.tenancy}: senza un tenant legato alla sessione il repository non lavora")
    w("")
    w("    def _col(self) -> Any:")
    w("        return self.session.db[self.COLLECTION]\n")
    w("    def _scope(self, flt: Dict[str, Any]) -> Dict[str, Any]:")
    if tc:
        w(f'        return {{"$and": [flt, {{"{tc.db_name}": to_bson(tenant_of(self.session), "{tc.type}")}}]}}\n')
    else:
        w("        return flt\n")
    w(f"    def _find(self, id: {pkt}) -> Optional[{T}]:")
    w(f'        d = self._col().find_one(self._scope({{"_id": to_bson(id, "{pk.type}")}}), session=self.session.session)')
    w("        return None if d is None else from_document(d)\n")
    w(f"    def _check(self, entity: {T}) -> None:")
    w('        """Tenant della sessione e record collegati esistenti (MongoDB non ha chiavi esterne)."""')
    if tc:
        tm = m[tc.name]
        w("        tenant = tenant_of(self.session)")
        w(f"        if entity.{tm} is not None and entity.{tm} != tenant:")
        w(f'            raise ModelValidationError("{T}", {{"{tc.name}": "tenant diverso da quello della sessione"}})')
        w(f"        entity.{tm} = tenant")
    w(f"        validate_{snake(T)}(entity)")
    if parents:
        w("        errors: Dict[str, str] = {}")
        for r in parents:
            tg = tables[r.target]
            fk = m[r.foreign_key]
            w(f"        if entity.{fk} is not None:")
            if r.target != T:
                w(f"            from .{r.target} import {base_class(L, r.target)}")
            w(f"            if {base_class(L, r.target)}(self.session)._find(entity.{fk}) is None:")
            w(f'                errors["{r.foreign_key}"] = "non trovato"')
        w("        if errors:")
        w(f'            raise ModelValidationError("{T}", errors)')
    w("")
    for meth in methods_of(t):
        k, _, arg = meth.key.partition(":")
        name = method_name(L, meth.key)
        w(f"    # {meth.summary}")
        if k == "get_by_id":
            w(f"    def {name}(self, id: {pkt}) -> Optional[{T}]:")
            w("        return self._find(id)\n")
        elif k == "list_page":
            w(f"    def {name}(self, page: PageRequest = PageRequest()) -> Page[{T}]:")
            w("        return run_mongo_page(self.session, self.COLLECTION, self.PAGING, self.FIELDS, self._scope({}), page, from_document)\n")
        elif k == "count":
            w(f"    def {name}(self) -> int:")
            w("        return self._col().count_documents(self._scope({}), session=self.session.session)\n")
        elif k == "exists":
            w(f"    def {name}(self, id: {pkt}) -> bool:")
            w(f'        return self._col().count_documents(self._scope({{"_id": to_bson(id, "{pk.type}")}}), limit=1, session=self.session.session) > 0\n')
        elif k == "create":
            w(f"    def {name}(self, entity: {T}) -> {T}:")
            w("        self._check(entity)")
            if pk.auto:
                gen_id = "uuid.uuid4()" if pk.type == "uuid" else "next_id(self.session, self.COLLECTION)"
                w(f"        if entity.{pkm} is None:")
                w(f"            entity.{pkm} = {gen_id}")
            for c in t.columns:
                if c.generated:
                    w(f"        entity.{m[c.name]} = now_ms()")
            w("        self._col().insert_one(to_document(entity), session=self.session.session)")
            w("        return entity\n")
        elif k == "update":
            w(f"    def {name}(self, id: {pkt}, changes: Dict[str, Any]) -> Optional[{T}]:")
            w("        unknown = set(changes) - self.UPDATABLE")
            w("        if unknown:")
            w(f'            raise ModelValidationError("{T}", {{k: "campo non modificabile" for k in sorted(unknown)}})')
            w("        entity = self._find(id)")
            w("        if entity is None:")
            w("            return None")
            w("        for key, value in changes.items():")
            w("            setattr(entity, key, value)")
            w("        self._check(entity)")
            for c in t.columns:
                if c.generated == "on_update":
                    w(f"        entity.{m[c.name]} = now_ms()")
            w(f'        self._col().replace_one(self._scope({{"_id": to_bson(id, "{pk.type}")}}), to_document(entity), session=self.session.session)')
            w("        return entity\n")
        elif k == "delete":
            w(f"    def {name}(self, id: {pkt}) -> bool:")
            w("        if self._find(id) is None:")
            w("            return False")
            for c, r in kids:
                ctc = tenant_column(c)
                fk_f = mongo_plan.field_name(c, c.col(r.foreign_key))
                flt = f'{{"{fk_f}": to_bson(id, "{pk.type}")' + (f', "{ctc.db_name}": to_bson(tenant_of(self.session), "{ctc.type}")' if ctc else "") + "}"
                if r.on_delete == "restrict":
                    w(f'        if self.session.db["{c.db_name}"].count_documents({flt}, limit=1, session=self.session.session):')
                    w(f'            raise ModelValidationError("{T}", {{"{mongo_plan.child_label(t, c, r)}": "record collegati"}})')
                else:
                    w(f'        self.session.db["{c.db_name}"].update_many({flt}, {{"$unset": {{"{fk_f}": ""}}}}, session=self.session.session)')
            w(f'        self._col().delete_one(self._scope({{"_id": to_bson(id, "{pk.type}")}}), session=self.session.session)')
            w("        return True\n")
        elif k == "find_by":
            c = t.col(arg)
            w(f"    def {name}(self, value: {PY_TYPE[c.type]}) -> Optional[{T}]:")
            w(f'        d = self._col().find_one(self._scope({{"{fields[m[arg]]}": to_bson(value, "{c.type}")}}), session=self.session.session)')
            w("        return None if d is None else from_document(d)\n")
        elif k == "list_by":
            c = t.col(arg)
            w(f"    def {name}(self, value: {PY_TYPE[c.type]}, page: PageRequest = PageRequest()) -> Page[{T}]:")
            w(f'        flt = self._scope({{"{fields[m[arg]]}": to_bson(value, "{c.type}")}})')
            w("        return run_mongo_page(self.session, self.COLLECTION, self.PAGING, self.FIELDS, flt, page, from_document)\n")
        elif k == "get_rel":
            r = next(x for x in t.relations if x.name == arg)
            fk = m[r.foreign_key]
            w(f'    def {name}(self, id: {pkt}) -> "Optional[{r.target}]":')
            if r.target != T:
                w(f"        from .{r.target} import {base_class(L, r.target)}")
            w("        entity = self._find(id)")
            w(f"        if entity is None or entity.{fk} is None:" if t.col(r.foreign_key).nullable else "        if entity is None:")
            w("            return None")
            w(f"        return {base_class(L, r.target)}(self.session)._find(entity.{fk})\n")
        elif k == "list_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f'    def {name}(self, id: {pkt}, page: PageRequest = PageRequest()) -> "Page[{r.target}]":')
            if r.target != T:
                w(f"        from .{r.target} import {base_class(L, r.target)}")
            w(f"        return {base_class(L, r.target)}(self.session).{method_name(L, 'list_by:' + r.foreign_key)}(id, page)\n")
        elif k in ("query_page", "query_list", "query_one"):
            q = next(x for x in t.queries if x.name == arg)
            params, conds = [], []
            for c in q.where:
                col = t.col(c.column)
                if c.param:
                    pn = snake(c.param)
                    pt = f"Sequence[{PY_TYPE[col.type]}]" if c.op == "in" else PY_TYPE[col.type]
                    params.append(f"{pn}: {pt}")
                    raw = pn
                else:
                    raw = _py_value(col, c.value) if c.has_value else "None"
                if c.op == "in":
                    val = f'[to_bson(x, "{col.type}") for x in {raw}]'
                elif c.op == "prefix":
                    val = raw
                else:
                    val = f'to_bson({raw}, "{col.type}")'
                conds.append(_mongo_cond(t, c, val))
            sig = ", ".join(["self"] + params)
            order = [(m[cn], member("typescript", cn), t.col(cn).type, d) for cn, d in t.order(q.order_by or None)]
            order_lit = "[" + ", ".join(f'("{a}", "{j}", "{ty}", {d})' for a, j, ty, d in order) + "]"
            flt = "self._scope({'$and': [" + ", ".join(conds) + "]})"
            if k == "query_page":
                w(f"    def {name}({sig}, page: PageRequest = PageRequest()) -> Page[{T}]:")
                w(f"        return run_mongo_page(self.session, self.COLLECTION, self.PAGING, self.FIELDS, {flt}, page, from_document,")
                w(f"                              fixed_order={order_lit})\n")
            elif k == "query_list":
                w(f"    def {name}({sig}) -> List[{T}]:")
                w(f"        docs = find_sorted(self.session, self.COLLECTION, {flt}, self.FIELDS, {order_lit}, self.PAGING.max_limit)")
                w("        return [from_document(d) for d in docs]\n")
            else:
                w(f"    def {name}({sig}) -> Optional[{T}]:")
                w(f"        docs = find_sorted(self.session, self.COLLECTION, {flt}, self.FIELDS, {order_lit}, 1)")
                w("        return from_document(docs[0]) if docs else None\n")
    return "\n".join(L_).rstrip() + "\n"
