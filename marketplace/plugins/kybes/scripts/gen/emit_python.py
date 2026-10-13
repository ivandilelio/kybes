"""Emettitore Python: SQLAlchemy 2.0 (Declarative + Mapped)."""
from __future__ import annotations

from typing import Dict, List, Tuple

import runtime_python
from naming import GEN_DIR, base_class, custom_file, header, member, method_name, repo_class
from schema import Table, index_specs, methods_of, snake

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
    cols_updatable = [m[c.name] for c in t.columns if not c.primary_key and not c.generated]
    w(f"class {base_class(L, t.name)}:")
    w(f'    """CRUD, relazioni e query di {t.name}. La transazione la gestisce il chiamante (vedi _uow.py)."""\n')
    w(f"    UPDATABLE = frozenset({{{', '.join(repr(x) for x in cols_updatable)}}})")
    w(f"    PAGING = PAGING_{snake(t.name).upper()}\n")
    w("    def __init__(self, session: Session) -> None:")
    w("        self.session = session\n")
    for meth in methods_of(t):
        k, _, arg = meth.key.partition(":")
        name = method_name(L, meth.key)
        w(f"    # {meth.summary}")
        if k == "get_by_id":
            w(f"    def {name}(self, id: {pkt}) -> Optional[{t.name}]:")
            w(f"        return self.session.get({t.name}, id)\n")
        elif k == "list_page":
            w(f"    def {name}(self, page: PageRequest = PageRequest()) -> Page[{t.name}]:")
            w(f"        return run_page(self.session, select({t.name}), self.PAGING, page)\n")
        elif k == "count":
            w(f"    def {name}(self) -> int:")
            w(f"        return int(self.session.scalar(select(func.count()).select_from({t.name})) or 0)\n")
        elif k == "exists":
            w(f"    def {name}(self, id: {pkt}) -> bool:")
            w(f"        return self.session.scalar(select({t.name}.{pkm}).where({t.name}.{pkm} == id)) is not None\n")
        elif k == "create":
            w(f"    def {name}(self, entity: {t.name}) -> {t.name}:")
            for r in t.relations:
                if r.kind == "many_to_one":
                    rn, fk = member(L, r.name), m[r.foreign_key]
                    tpk = member(L, tables[r.target].pk.name)
                    w(f"        if entity.{rn} is not None:  # collegato come oggetto: la chiave segue l'oggetto")
                    w(f"            entity.{fk} = entity.{rn}.{tpk}")
            w(f"        validate_{snake(t.name)}(entity)")
            w("        self.session.add(entity)")
            w("        self.session.flush()")
            w("        return entity\n")
        elif k == "update":
            w(f"    def {name}(self, id: {pkt}, changes: Dict[str, Any]) -> Optional[{t.name}]:")
            w("        unknown = set(changes) - self.UPDATABLE")
            w("        if unknown:")
            w(f'            raise ModelValidationError("{t.name}", {{k: "campo non modificabile" for k in sorted(unknown)}})')
            w(f"        entity = self.session.get({t.name}, id)")
            w("        if entity is None:")
            w("            return None")
            w("        for key, value in changes.items():")
            w("            setattr(entity, key, value)")
            w(f"        validate_{snake(t.name)}(entity)")
            w("        self.session.flush()")
            w("        return entity\n")
        elif k == "delete":
            w(f"    def {name}(self, id: {pkt}) -> bool:")
            w(f"        entity = self.session.get({t.name}, id)")
            w("        if entity is None:")
            w("            return False")
            w("        self.session.delete(entity)")
            w("        self.session.flush()")
            w("        return True\n")
        elif k == "find_by":
            c = t.col(arg)
            w(f"    def {name}(self, value: {PY_TYPE[c.type]}) -> Optional[{t.name}]:")
            w(f"        return self.session.scalars(select({t.name}).where({t.name}.{m[arg]} == value)).first()\n")
        elif k == "list_by":
            c = t.col(arg)
            w(f"    def {name}(self, value: {PY_TYPE[c.type]}, page: PageRequest = PageRequest()) -> Page[{t.name}]:")
            w(f"        return run_page(self.session, select({t.name}).where({t.name}.{m[arg]} == value), self.PAGING, page)\n")
        elif k == "get_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f'    def {name}(self, id: {pkt}) -> "Optional[{r.target}]":')
            w(f"        entity = self.session.get({t.name}, id)")
            w(f"        return entity.{member(L, r.name)} if entity is not None else None\n")
        elif k == "list_rel":
            r = next(x for x in t.relations if x.name == arg)
            w(f'    def {name}(self, id: {pkt}, page: PageRequest = PageRequest()) -> "Page[{r.target}]":')
            if r.target != t.name:
                w(f"        from .{r.target} import {r.target}, PAGING_{snake(r.target).upper()}")
            w(f"        stmt = select({r.target}).where({r.target}.{member(L, r.foreign_key)} == id)")
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
                w(f"        stmt = select({t.name}).where({where})")
                w(f"        return run_page(self.session, stmt, self.PAGING, page, fixed_order={order_lit})\n")
            elif k == "query_list":
                w(f"    def {name}({sig}) -> List[{t.name}]:")
                w(f"        stmt = select({t.name}).where({where})")
                w(f"        stmt = order_rows(stmt, self.PAGING, {order_lit}).limit(self.PAGING.max_limit)")
                w("        return list(self.session.scalars(stmt))\n")
            else:
                w(f"    def {name}({sig}) -> Optional[{t.name}]:")
                w(f"        stmt = select({t.name}).where({where})")
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
             "from ._uow import isolation_for, run_in_transaction, transaction"]
    for n in tables:
        lines.append(f"from .{n} import {n}, {base_class(L, n)}, validate_{snake(n)}, PAGING_{snake(n).upper()}")
    names = ["Base", "ModelValidationError", "Page", "PageRequest", "isolation_for", "run_in_transaction", "transaction"] + \
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
           f"{GEN_DIR}/_paging.py": runtime_python.paging_file(), f"{GEN_DIR}/_uow.py": runtime_python.uow_file(tables)}
    for n, t in tables.items():
        gen[f"{GEN_DIR}/{n}.py"] = _table_file(t, tables, schema_rel[n])
    custom = {custom_file(L, n): custom_stub(t) for n, t in tables.items()}
    custom["__init__.py"] = '"""Modelli e repository: un file per tabella (vedi MODEL_INDEX.md)."""\n'
    return gen, custom
