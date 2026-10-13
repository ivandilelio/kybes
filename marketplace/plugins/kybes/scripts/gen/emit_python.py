"""Emettitore Python: SQLAlchemy 2.0 (Declarative + Mapped)."""
from __future__ import annotations

from typing import Dict, List, Tuple

import runtime_archive
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
        gen[f"{GEN_DIR}/{n}.py"] = _table_file(t, tables, schema_rel[n])
    custom = {custom_file(L, n): custom_stub(t) for n, t in tables.items()}
    custom["__init__.py"] = '"""Modelli e repository: un file per tabella (vedi MODEL_INDEX.md)."""\n'
    return gen, custom
