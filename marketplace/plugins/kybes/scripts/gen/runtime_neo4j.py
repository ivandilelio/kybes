"""Runtime Neo4j (storage: neo4j) nei quattro linguaggi: sessione del driver, conversioni,
paginazione con offset (Neo4j non ha cursore keyset nativo), Unit of Work con le transazioni Neo4j."""
from __future__ import annotations

from naming import header


def python_file() -> str:
    return header("python", "kit") + "# ruff: noqa\n" + '''"""Neo4j per le tabelle con storage: neo4j (vedi docs/neo4j.md).

    driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
    session = neo4j_session(driver, tenant=t)
    Repository(session).get_by_id(id)
    run_in_neo4j_transaction(driver, lambda tx: ..., tenant=t)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, TypeVar

from neo4j import GraphDatabase, ManagedTransaction, Session

from ._paging import OrderItem, Page, PageRequest, PagingSpec
from ._tenant import bind_tenant

T = TypeVar("T")


class Neo4jSession:
    """Sessione Neo4j con supporto tenant opzionale."""
    def __init__(self, session: Session, tenant: Optional[str] = None):
        self.session = session
        self.tenant = tenant


def neo4j_session(driver, tenant: Optional[str] = None) -> Neo4jSession:
    return Neo4jSession(driver.session(), tenant=tenant)


def run_in_neo4j_transaction(driver, fn: Callable, tenant: Optional[str] = None):
    with driver.session() as session:
        ns = Neo4jSession(session, tenant=tenant)
        return session.execute_write(lambda tx: fn(ns, tx))


def to_neo4j(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, date) and not isinstance(val, datetime):
        return val.isoformat()
    return val


def from_neo4j(val: Any, target_type: str) -> Any:
    if val is None:
        return None
    if target_type == "uuid":
        return uuid.UUID(val) if isinstance(val, str) else val
    if target_type == "decimal":
        return Decimal(str(val))
    if target_type == "date":
        return date.fromisoformat(val) if isinstance(val, str) else val
    return val


def run_neo4j_page(session: Neo4jSession, cypher_match: str, params: Dict[str, Any],
                   paging: PagingSpec, page: Optional[PageRequest], from_record: Callable,
                   order_items: Optional[List[OrderItem]] = None) -> Page:
    """Paginazione offset su query Cypher: SKIP/LIMIT."""
    p = page or PageRequest()
    limit = min(p.limit or paging.default_limit, paging.max_limit)
    offset = int(p.cursor) if p.cursor else 0
    order_clause = ""
    if order_items:
        parts = []
        for oi in order_items:
            parts.append(f"n.{oi.column} {'DESC' if oi.desc else 'ASC'}")
        order_clause = " ORDER BY " + ", ".join(parts)
    elif paging.default_sort:
        parts = []
        for oi in paging.default_sort:
            parts.append(f"n.{oi.column} {'DESC' if oi.desc else 'ASC'}")
        order_clause = " ORDER BY " + ", ".join(parts)
    full = f"{cypher_match}{order_clause} SKIP $offset LIMIT $fetch"
    params = {**params, "offset": offset, "fetch": limit + 1}
    with session.session.begin_transaction() as tx:
        result = tx.run(full, params)
        rows = [from_record(record) for record in result]
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = str(offset + limit) if has_more else None
    return Page(items=items, next_cursor=next_cursor, limit=limit)
'''


def typescript_file() -> str:
    return header("typescript", "kit") + '''/**
 * Neo4j per le tabelle con storage: neo4j.
 * import { neo4jSession, runInNeo4jTransaction, runNeo4jPage } from "./_neo4j";
 */
import neo4j, { Driver, Session, ManagedTransaction } from "neo4j-driver";
import { OrderItem, Page, PageRequest, PagingSpec } from "./_paging";

export interface Neo4jSession {
  session: Session;
  tenant?: string;
}

export function neo4jSession(driver: Driver, tenant?: string): Neo4jSession {
  return { session: driver.session(), tenant };
}

export async function runInNeo4jTransaction<T>(
  driver: Driver, fn: (session: Neo4jSession, tx: ManagedTransaction) => Promise<T>, tenant?: string
): Promise<T> {
  const session = driver.session();
  try {
    return await session.executeWrite((tx) => fn({ session, tenant }, tx));
  } finally {
    await session.close();
  }
}

export function toNeo4j(val: unknown): unknown {
  if (val === null || val === undefined) return null;
  if (typeof val === "bigint") return neo4j.int(Number(val));
  return val;
}

export async function runNeo4jPage<T>(
  session: Neo4jSession, cypherMatch: string, params: Record<string, unknown>,
  paging: PagingSpec, page: PageRequest | undefined, fromRecord: (r: neo4j.Record) => T,
  orderItems?: OrderItem[]
): Promise<Page<T>> {
  const p = page ?? {};
  const limit = Math.min(p.limit ?? paging.defaultLimit, paging.maxLimit);
  const offset = p.cursor ? parseInt(p.cursor, 10) : 0;
  let orderClause = "";
  const ois = orderItems ?? paging.defaultSort ?? [];
  if (ois.length > 0) {
    orderClause = " ORDER BY " + ois.map((o) => `n.${o.column} ${o.desc ? "DESC" : "ASC"}`).join(", ");
  }
  const full = `${cypherMatch}${orderClause} SKIP $offset LIMIT $fetch`;
  const result = await session.session.run(full, { ...params, offset: neo4j.int(offset), fetch: neo4j.int(limit + 1) });
  const rows = result.records.map(fromRecord);
  const hasMore = rows.length > limit;
  return { items: rows.slice(0, limit), nextCursor: hasMore ? String(offset + limit) : null, limit };
}
'''


def java_file() -> str:
    return header("java", "kit") + '''package kybes;

import org.neo4j.driver.*;
import org.neo4j.driver.types.Node;
import java.util.*;

/**
 * Neo4j per le tabelle con storage: neo4j.
 */
public final class Neo4jSupport {
    private Neo4jSupport() {}

    public interface Neo4jSession {
        Session session();
        String tenant();
    }

    public static Neo4jSession neo4jSession(Driver driver, String tenant) {
        Session s = driver.session();
        return new Neo4jSession() {
            public Session session() { return s; }
            public String tenant() { return tenant; }
        };
    }

    @FunctionalInterface
    public interface TxFunction<T> {
        T apply(Neo4jSession session, TransactionContext tx);
    }

    public static <T> T runInNeo4jTransaction(Driver driver, TxFunction<T> fn, String tenant) {
        try (Session session = driver.session()) {
            Neo4jSession ns = neo4jSession(driver, tenant);
            return session.executeWrite(tx -> fn.apply(ns, tx));
        }
    }

    public static Object toNeo4j(Object val) {
        if (val == null) return null;
        if (val instanceof java.math.BigDecimal) return ((java.math.BigDecimal) val).doubleValue();
        if (val instanceof UUID) return val.toString();
        return val;
    }

    public static Paging.Page<Map<String, Object>> runNeo4jPage(
        Session session, String cypherMatch, Map<String, Object> params,
        Paging.PagingSpec paging, Paging.PageRequest page,
        List<Paging.OrderItem> orderItems
    ) {
        int limit = Math.min(page != null && page.limit() > 0 ? page.limit() : paging.defaultLimit(), paging.maxLimit());
        int offset = page != null && page.cursor() != null ? Integer.parseInt(page.cursor()) : 0;
        StringBuilder order = new StringBuilder();
        List<Paging.OrderItem> ois = orderItems != null && !orderItems.isEmpty() ? orderItems : paging.defaultSort();
        if (ois != null && !ois.isEmpty()) {
            order.append(" ORDER BY ");
            for (int i = 0; i < ois.size(); i++) {
                if (i > 0) order.append(", ");
                order.append("n.").append(ois.get(i).column()).append(ois.get(i).desc() ? " DESC" : " ASC");
            }
        }
        String full = cypherMatch + order + " SKIP $offset LIMIT $fetch";
        Map<String, Object> allParams = new HashMap<>(params);
        allParams.put("offset", offset);
        allParams.put("fetch", limit + 1);
        var result = session.run(full, allParams);
        List<Map<String, Object>> rows = new ArrayList<>();
        while (result.hasNext()) {
            rows.add(result.next().get("n").asMap());
        }
        boolean hasMore = rows.size() > limit;
        return new Paging.Page<>(rows.subList(0, Math.min(rows.size(), limit)),
            hasMore ? String.valueOf(offset + limit) : null, limit);
    }
}
'''


def csharp_file() -> str:
    return header("csharp", "kit") + '''using Neo4j.Driver;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Kybes;

/// <summary>Neo4j per le tabelle con storage: neo4j.</summary>
public sealed class Neo4jSession
{
    public IAsyncSession Session { get; }
    public string? Tenant { get; }
    public Neo4jSession(IAsyncSession session, string? tenant = null)
    {
        Session = session;
        Tenant = tenant;
    }
}

public static class Neo4jSupport
{
    public static Neo4jSession Neo4jSessionFor(IDriver driver, string? tenant = null) =>
        new(driver.AsyncSession(), tenant);

    public static async Task<T> RunInNeo4jTransactionAsync<T>(
        IDriver driver, Func<Neo4jSession, IAsyncQueryRunner, Task<T>> fn, string? tenant = null)
    {
        await using var session = driver.AsyncSession();
        var ns = new Neo4jSession(session, tenant);
        return await session.ExecuteWriteAsync(tx => fn(ns, tx));
    }

    public static object? ToNeo4j(object? val)
    {
        if (val is null) return null;
        if (val is decimal d) return (double)d;
        if (val is Guid g) return g.ToString();
        return val;
    }

    public static async Task<Page<Dictionary<string, object?>>> RunNeo4jPageAsync(
        IAsyncSession session, string cypherMatch, Dictionary<string, object?> parameters,
        PagingSpec paging, PageRequest? page, IReadOnlyList<OrderItem>? orderItems = null,
        CancellationToken ct = default)
    {
        var p = page ?? new PageRequest();
        int limit = Math.Min(p.Limit > 0 ? p.Limit : paging.DefaultLimit, paging.MaxLimit);
        int offset = p.Cursor != null ? int.Parse(p.Cursor) : 0;
        var ois = orderItems != null && orderItems.Count > 0 ? orderItems : paging.DefaultSort;
        string orderClause = "";
        if (ois != null && ois.Count > 0)
            orderClause = " ORDER BY " + string.Join(", ", ois.Select(o => $"n.{o.Column} {(o.Desc ? "DESC" : "ASC")}"));
        string full = $"{cypherMatch}{orderClause} SKIP $offset LIMIT $fetch";
        var allParams = new Dictionary<string, object?>(parameters) { ["offset"] = offset, ["fetch"] = limit + 1 };
        var result = await session.RunAsync(full, allParams);
        var rows = new List<Dictionary<string, object?>>();
        await result.ForEachAsync(r => rows.Add(r["n"].As<INode>().Properties.ToDictionary(kv => kv.Key, kv => kv.Value)));
        bool hasMore = rows.Count > limit;
        return new Page<Dictionary<string, object?>>(rows.Take(limit).ToList(), hasMore ? (offset + limit).ToString() : null, limit);
    }
}
'''
