"""Moduli di supporto TypeScript generati: paginazione a cursore e Unit of Work."""
from __future__ import annotations

from typing import Dict

from naming import header
from sqlonly import strip_sql
from schema import Table

PAGING = r'''// Paginazione a cursore (keyset), uguale per UI, API e DB-Model.
// La UI invia limit, cursor e sort (es. "-data,numero", nomi JSON); riceve items e nextCursor.
// Il cursore è opaco: codifica i valori dell'ultima riga e l'ordinamento con cui è stato prodotto.
// kybes:sql-begin
import { Brackets } from "typeorm";
import type { ObjectLiteral, SelectQueryBuilder, WhereExpressionBuilder } from "typeorm";
// kybes:sql-end
import { ModelValidationError } from "./_base";

export type SortType = "uuid" | "string" | "int" | "bigint" | "decimal" | "date" | "datetime";

export interface PageRequest {
  limit?: number;
  cursor?: string | null;
  sort?: string | null;
}

export interface Page<T> {
  items: T[];
  nextCursor: string | null;
  limit: number;
}

export interface OrderItem {
  prop: string;
  json: string;
  type: SortType;
  desc: boolean;
}

export interface PagingSpec {
  table: string;
  pk: { prop: string; json: string; type: SortType };
  sortable: Record<string, { prop: string; type: SortType }>;
  defaultOrder: OrderItem[];
  defaultLimit: number;
  maxLimit: number;
}

// kybes:sql-begin
export function likePrefix(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/%/g, "\\%").replace(/_/g, "\\_") + "%";
}
// kybes:sql-end

function invalid(spec: PagingSpec, field: string, rule: string): ModelValidationError {
  return new ModelValidationError(spec.table, { [field]: rule });
}

export function resolveOrder(spec: PagingSpec, sort?: string | null): OrderItem[] {
  if (!sort) return [...spec.defaultOrder];
  const order: OrderItem[] = [];
  for (const raw of sort.split(",").map((s) => s.trim()).filter((s) => s.length > 0)) {
    const desc = raw.startsWith("-");
    const name = raw.replace(/^[-+]/, "");
    if (name === spec.pk.json) {
      order.push({ ...spec.pk, desc });
      continue;
    }
    const col = spec.sortable[name];
    if (!col) throw invalid(spec, "sort", "colonna non ordinabile: " + name);
    order.push({ prop: col.prop, json: name, type: col.type, desc });
  }
  if (!order.some((o) => o.prop === spec.pk.prop)) order.push({ ...spec.pk, desc: false });
  return order;
}

function signature(order: OrderItem[]): string {
  return order.map((o) => (o.desc ? "-" : "") + o.json).join(",");
}

function encodeValue(value: unknown, type: SortType): unknown {
  if (type === "datetime") return (value as Date).toISOString();
  if (type === "int") return value;
  return String(value);
}

function decodeValue(value: unknown, type: SortType): unknown {
  if (type === "int") {
    if (typeof value !== "number" || !Number.isInteger(value)) throw new Error("intero atteso");
    return value;
  }
  if (typeof value !== "string") throw new Error("stringa attesa");
  if (type === "datetime") {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) throw new Error("data non valida");
    return d;
  }
  return value;
}

export function encodeCursor(order: OrderItem[], row: object): string {
  const payload = { s: signature(order), v: order.map((o) => encodeValue((row as Record<string, unknown>)[o.prop], o.type)) };
  return Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
}

export function decodeCursor(spec: PagingSpec, order: OrderItem[], cursor: string): unknown[] {
  try {
    const payload = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8")) as { s?: unknown; v?: unknown };
    if (payload.s !== signature(order) || !Array.isArray(payload.v) || payload.v.length !== order.length) {
      throw new Error("ordinamento diverso");
    }
    const values = payload.v as unknown[];
    return order.map((o, i) => decodeValue(values[i], o.type));
  } catch {
    throw invalid(spec, "cursor", "non valido");
  }
}

// kybes:sql-begin
export function orderRows<T extends ObjectLiteral>(qb: SelectQueryBuilder<T>, alias: string, order: OrderItem[]): SelectQueryBuilder<T> {
  order.forEach((o, i) => {
    const expr = `${alias}.${o.prop}`;
    if (i === 0) qb.orderBy(expr, o.desc ? "DESC" : "ASC");
    else qb.addOrderBy(expr, o.desc ? "DESC" : "ASC");
  });
  return qb;
}

function after(alias: string, order: OrderItem[], values: unknown[]): Brackets {
  // (a, b, c) > (x, y, z) espanso colonna per colonna, rispettando la direzione di ognuna
  return new Brackets((outer: WhereExpressionBuilder) => {
    order.forEach((o, i) => {
      const branch = new Brackets((inner: WhereExpressionBuilder) => {
        for (let j = 0; j < i; j++) {
          const cond = `${alias}.${order[j].prop} = :kc${j}`;
          if (j === 0) inner.where(cond, { [`kc${j}`]: values[j] });
          else inner.andWhere(cond, { [`kc${j}`]: values[j] });
        }
        const step = `${alias}.${o.prop} ${o.desc ? "<" : ">"} :kc${i}`;
        if (i === 0) inner.where(step, { [`kc${i}`]: values[i] });
        else inner.andWhere(step, { [`kc${i}`]: values[i] });
      });
      if (i === 0) outer.where(branch);
      else outer.orWhere(branch);
    });
  });
}
// kybes:sql-end

/** Ordinamento e limite validati di una richiesta di pagina (comune a SQL e MongoDB). */
export function preparePage(spec: PagingSpec, page: PageRequest, fixedOrder?: OrderItem[]): { order: OrderItem[]; limit: number } {
  if (fixedOrder && page.sort) throw invalid(spec, "sort", "questa query ha un ordinamento fisso");
  const order = fixedOrder ?? resolveOrder(spec, page.sort);
  const limit = page.limit ?? spec.defaultLimit;
  if (!Number.isInteger(limit) || limit < 1 || limit > spec.maxLimit) throw invalid(spec, "limit", `tra 1 e ${spec.maxLimit}`);
  return { order, limit };
}

export function emptyPage<T>(spec: PagingSpec, page: PageRequest = {}): Page<T> {
  return { items: [], nextCursor: null, limit: page.limit ?? spec.defaultLimit };
}

// kybes:sql-begin
export async function runPage<T extends ObjectLiteral>(
  qb: SelectQueryBuilder<T>,
  alias: string,
  spec: PagingSpec,
  page: PageRequest = {},
  fixedOrder?: OrderItem[],
): Promise<Page<T>> {
  const { order, limit } = preparePage(spec, page, fixedOrder);
  if (page.cursor) qb.andWhere(after(alias, order, decodeCursor(spec, order, page.cursor)));
  const rows = await orderRows(qb, alias, order).limit(limit + 1).getMany();
  const more = rows.length > limit;
  const items = rows.slice(0, limit);
  return { items, nextCursor: more && items.length > 0 ? encodeCursor(order, items[items.length - 1]) : null, limit };
}
// kybes:sql-end
'''


def paging_file(sql: bool = True) -> str:
    return header("typescript", "kit") + "/* eslint-disable */\n" + strip_sql(PAGING, sql)


def uow_file(tables: Dict[str, Table]) -> str:
    iso = "\n".join(f'  {n}: "{t.isolation}",' for n, t in tables.items())
    return header("typescript", "kit") + "/* eslint-disable */\n" + f'''// Unit of Work: transazioni aperte dal service, con isolamento e retry sui conflitti.
//
//   await runInTransaction(dataSource, async (em) => {{
//     const ordini = new OrdiniRepository(em);
//     const righe = new RigheOrdineRepository(em);
//     ...
//   }}, {{ tables: ["Ordini", "RigheOrdine"] }});
import type {{ DataSource, EntityManager }} from "typeorm";
import {{ applyTenantSetting, bindTenant }} from "./_tenant";

export type Isolation = "read_committed" | "repeatable_read" | "serializable";
type TypeOrmIsolation = Parameters<EntityManager["transaction"]>[0];

/** Livello di isolamento dichiarato negli schemi (transactions.isolation). */
export const ISOLATION: Record<string, Isolation> = {{
{iso}
}};
const RANK: Record<Isolation, number> = {{ read_committed: 0, repeatable_read: 1, serializable: 2 }};
export const LEVELS: Record<Isolation, string | null> = {{
  read_committed: "READ COMMITTED",
  repeatable_read: "REPEATABLE READ",
  serializable: "SERIALIZABLE",
}};
/** SQLSTATE ritentabili: conflitto di serializzazione e deadlock. */
export const RETRYABLE_SQLSTATE = new Set(["40001", "40P01"]);

export function isolationFor(tables: Iterable<string>): Isolation {{
  let best: Isolation = "read_committed";
  for (const t of tables) {{
    const level = ISOLATION[t] ?? "read_committed";
    if (RANK[level] > RANK[best]) best = level;
  }}
  return best;
}}

export function isRetryable(error: unknown): boolean {{
  const seen = new Set<unknown>();
  let cur: unknown = error;
  while (cur && typeof cur === "object" && !seen.has(cur)) {{
    seen.add(cur);
    const e = cur as {{ code?: unknown; sqlState?: unknown; driverError?: unknown; cause?: unknown }};
    if (RETRYABLE_SQLSTATE.has(String(e.code)) || RETRYABLE_SQLSTATE.has(String(e.sqlState))) return true;
    cur = e.driverError ?? e.cause;
  }}
  return false;
}}

export interface TransactionOptions {{
  tables?: string[];
  isolation?: Isolation;
  maxRetries?: number;
  backoffMs?: number;
  /** nomi dei livelli per il database in uso; null = livello predefinito del database */
  levels?: Partial<Record<Isolation, string | null>>;
  /** tenant da legare all'EntityManager della transazione (su PostgreSQL anche app.tenant_id) */
  tenant?: unknown;
}}

/** Esegue work in una transazione; la ripete da capo sui conflitti di serializzazione e sui deadlock. */
export async function runInTransaction<T>(
  dataSource: DataSource,
  work: (em: EntityManager) => Promise<T>,
  options: TransactionOptions = {{}},
): Promise<T> {{
  const level = options.isolation ?? isolationFor(options.tables ?? []);
  const names = {{ ...LEVELS, ...(options.levels ?? {{}}) }};
  const maxRetries = options.maxRetries ?? 3;
  const backoffMs = options.backoffMs ?? 50;
  const bound = async (em: EntityManager): Promise<T> => {{
    if (options.tenant !== undefined && options.tenant !== null) {{
      bindTenant(em, options.tenant);
      await applyTenantSetting(em);
    }}
    return work(em);
  }};
  for (let attempt = 0; ; attempt++) {{
    try {{
      const name = names[level];
      if (name) return await dataSource.transaction(name as TypeOrmIsolation, bound);
      return await dataSource.transaction(bound);
    }} catch (error) {{
      if (attempt >= maxRetries || !isRetryable(error)) throw error;
      await new Promise((resolve) => setTimeout(resolve, backoffMs * 2 ** attempt));
    }}
  }}
}}
'''
