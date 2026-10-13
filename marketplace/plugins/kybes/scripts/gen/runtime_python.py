"""Moduli di supporto Python generati: paginazione a cursore e Unit of Work."""
from __future__ import annotations

from typing import Dict

from naming import header
from schema import Table

PAGING = '''"""Paginazione a cursore (keyset), uguale per UI, API e DB-Model.

Contratto: la UI invia limit, cursor e sort (es. "-data,numero", nomi JSON); riceve items e next_cursor.
Il cursore è opaco: codifica i valori dell'ultima riga e l'ordinamento con cui è stato prodotto.
"""
from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Generic, List, Optional, Sequence, Tuple, TypeVar

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ._base import ModelValidationError

T = TypeVar("T")

# (attributo, nome JSON, tipo, discendente)
OrderItem = Tuple[str, str, str, bool]


@dataclass(frozen=True)
class PageRequest:
    """Richiesta di pagina. sort usa i nomi JSON (camelCase), con "-" davanti per l'ordine discendente."""

    limit: Optional[int] = None
    cursor: Optional[str] = None
    sort: Optional[str] = None


@dataclass
class Page(Generic[T]):
    items: List[T]
    next_cursor: Optional[str]
    limit: int

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


@dataclass(frozen=True)
class PagingSpec:
    table: str
    entity: Any
    pk: Tuple[str, str, str]                     # (attributo, nome JSON, tipo)
    sortable: Dict[str, Tuple[str, str]] = field(default_factory=dict)   # nome JSON -> (attributo, tipo)
    default_order: List[OrderItem] = field(default_factory=list)
    default_limit: int = 50
    max_limit: int = 100


def like_prefix(value: str) -> str:
    """Valore per LIKE 'prefisso%' con i caratteri speciali protetti."""
    return value.replace("\\\\", "\\\\\\\\").replace("%", "\\\\%").replace("_", "\\\\_") + "%"


def _invalid(spec: PagingSpec, field_name: str, rule: str) -> ModelValidationError:
    return ModelValidationError(spec.table, {field_name: rule})


def resolve_order(spec: PagingSpec, sort: Optional[str]) -> List[OrderItem]:
    if not sort:
        return list(spec.default_order)
    order: List[OrderItem] = []
    for token in [s.strip() for s in sort.split(",") if s.strip()]:
        desc = token.startswith("-")
        name = token.lstrip("-+")
        if name == spec.pk[1]:
            order.append((spec.pk[0], spec.pk[1], spec.pk[2], desc))
            continue
        if name not in spec.sortable:
            raise _invalid(spec, "sort", "colonna non ordinabile: " + name)
        attr, typ = spec.sortable[name]
        order.append((attr, name, typ, desc))
    if not any(o[0] == spec.pk[0] for o in order):
        order.append((spec.pk[0], spec.pk[1], spec.pk[2], False))
    return order


def _signature(order: Sequence[OrderItem]) -> str:
    return ",".join(("-" if d else "") + j for _, j, _, d in order)


def _encode(value: Any, typ: str) -> Any:
    # formato comune a tutti i linguaggi: int come numero, tutto il resto come stringa (date in ISO 8601)
    if typ in ("uuid", "decimal", "bigint"):
        return str(value)
    if typ in ("date", "datetime"):
        return value.isoformat()
    return value


def _decode(value: Any, typ: str) -> Any:
    if typ == "uuid":
        return uuid.UUID(str(value))
    if typ == "decimal":
        return Decimal(str(value))
    if typ == "date":
        return date.fromisoformat(value)
    if typ == "datetime":
        return datetime.fromisoformat(value)
    if typ == "bigint":
        if not isinstance(value, str) or not value.lstrip("-").isdigit():
            raise ValueError("intero atteso")
        return int(value)
    if typ == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("intero atteso")
        return value
    if not isinstance(value, str):
        raise ValueError("stringa attesa")
    return value


def encode_cursor(order: Sequence[OrderItem], row: Any) -> str:
    payload = {"s": _signature(order), "v": [_encode(getattr(row, a), t) for a, _, t, _ in order]}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(spec: PagingSpec, order: Sequence[OrderItem], cursor: str) -> List[Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("s") != _signature(order) or len(payload.get("v", [])) != len(order):
            raise ValueError("ordinamento diverso")
        return [_decode(v, t) for v, (_, _, t, _) in zip(payload["v"], order)]
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation, binascii.Error, json.JSONDecodeError):
        raise _invalid(spec, "cursor", "non valido") from None


def order_rows(stmt: Any, spec: PagingSpec, order: Sequence[OrderItem]) -> Any:
    cols = [getattr(spec.entity, a) for a, _, _, _ in order]
    return stmt.order_by(*[c.desc() if d else c.asc() for c, (_, _, _, d) in zip(cols, order)])


def _after(spec: PagingSpec, order: Sequence[OrderItem], values: Sequence[Any]) -> Any:
    """(a, b, c) > (x, y, z) espanso colonna per colonna, rispettando la direzione di ognuna."""
    cols = [getattr(spec.entity, a) for a, _, _, _ in order]
    branches = []
    for i, (col, (_, _, _, desc)) in enumerate(zip(cols, order)):
        prefix = [cols[j] == values[j] for j in range(i)]
        step = col < values[i] if desc else col > values[i]
        branches.append(and_(*prefix, step) if prefix else step)
    return or_(*branches)


def prepare_page(spec: PagingSpec, page: PageRequest, fixed_order: Optional[List[OrderItem]] = None) -> Tuple[List[OrderItem], int]:
    """Ordinamento e limite validati di una richiesta di pagina (comune a SQL e MongoDB)."""
    if fixed_order is not None and page.sort:
        raise _invalid(spec, "sort", "questa query ha un ordinamento fisso")
    order = fixed_order if fixed_order is not None else resolve_order(spec, page.sort)
    limit = spec.default_limit if page.limit is None else page.limit
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > spec.max_limit:
        raise _invalid(spec, "limit", f"tra 1 e {spec.max_limit}")
    return order, limit


def run_page(session: Session, stmt: Any, spec: PagingSpec, page: PageRequest,
             fixed_order: Optional[List[OrderItem]] = None) -> Page[Any]:
    order, limit = prepare_page(spec, page, fixed_order)
    if page.cursor:
        stmt = stmt.where(_after(spec, order, decode_cursor(spec, order, page.cursor)))
    rows = list(session.scalars(order_rows(stmt, spec, order).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return Page(items=rows, next_cursor=encode_cursor(order, rows[-1]) if more and rows else None, limit=limit)
'''


def paging_file() -> str:
    return header("python", "kit") + "# ruff: noqa\n" + PAGING


def uow_file(tables: Dict[str, Table]) -> str:
    iso = ",\n".join(f'    "{n}": "{t.isolation}"' for n, t in tables.items())
    return header("python", "kit") + "# ruff: noqa\n" + f'''"""Unit of Work: transazioni aperte dal service, con isolamento e retry sui conflitti.

Uso tipico nel service:

    def registra_ordine(session):
        ordini = OrdiniRepository(session)
        righe = RigheOrdineRepository(session)
        ...
    run_in_transaction(SessionFactory, registra_ordine, tables=["Ordini", "RigheOrdine"])
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, TypeVar

from sqlalchemy.orm import Session

from ._tenant import apply_tenant_setting, bind_tenant

R = TypeVar("R")

# livello di isolamento dichiarato negli schemi (transactions.isolation)
ISOLATION: Dict[str, str] = {{
{iso}
}}
_RANK = {{"read_committed": 0, "repeatable_read": 1, "serializable": 2}}
LEVELS = {{"read_committed": "READ COMMITTED", "repeatable_read": "REPEATABLE READ", "serializable": "SERIALIZABLE"}}
# SQLSTATE ritentabili: conflitto di serializzazione e deadlock
RETRYABLE_SQLSTATE = frozenset({{"40001", "40P01"}})


def isolation_for(tables: Iterable[str]) -> str:
    """Il livello più severo tra quelli delle tabelle coinvolte."""
    levels = [ISOLATION.get(t, "read_committed") for t in tables]
    return max(levels, key=_RANK.__getitem__) if levels else "read_committed"


def is_retryable(exc: BaseException) -> bool:
    seen = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        code = getattr(cur, "pgcode", None) or getattr(cur, "sqlstate", None)
        if code in RETRYABLE_SQLSTATE:
            return True
        cur = getattr(cur, "orig", None) or cur.__cause__
    return False


@contextmanager
def transaction(session_factory: Callable[[], Session], tables: Iterable[str] = (),
                isolation: Optional[str] = None, levels: Optional[Dict[str, Optional[str]]] = None,
                tenant: Any = None) -> Iterator[Session]:
    """Commit se il blocco termina, rollback se solleva. levels permette di adattare i nomi al database.
    Con tenant la sessione è legata a quel tenant (e su PostgreSQL app.tenant_id vale per la transazione)."""
    level = isolation or isolation_for(tables)
    names = levels or LEVELS
    with session_factory() as session:
        if names.get(level):
            session.connection(execution_options={{"isolation_level": names[level]}})
        if tenant is not None:
            bind_tenant(session, tenant)
            apply_tenant_setting(session)
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


def run_in_transaction(session_factory: Callable[[], Session], work: Callable[[Session], R], tables: Iterable[str] = (),
                       isolation: Optional[str] = None, max_retries: int = 3, backoff_s: float = 0.05,
                       levels: Optional[Dict[str, Optional[str]]] = None, tenant: Any = None) -> R:
    """Esegue work in una transazione; la ripete da capo sui conflitti di serializzazione e sui deadlock."""
    tables = list(tables)
    attempt = 0
    while True:
        try:
            with transaction(session_factory, tables, isolation, levels, tenant) as session:
                return work(session)
        except Exception as exc:  # noqa: BLE001 - si ritenta solo se il database lo indica
            if attempt >= max_retries or not is_retryable(exc):
                raise
            attempt += 1
            time.sleep(backoff_s * (2 ** (attempt - 1)))
'''
