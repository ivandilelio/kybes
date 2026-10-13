"""Runtime MongoDB (storage: mongo) nei quattro linguaggi: sessione del modello, conversioni BSON, contatori,
paginazione keyset con lo stesso cursore delle tabelle SQL, Unit of Work con le transazioni MongoDB."""
from __future__ import annotations

from naming import header


def python_file() -> str:
    return header("python", "kit") + "# ruff: noqa\n" + '''"""MongoDB per le tabelle con storage: mongo (vedi docs/mongodb.md).

    ms = mongo_session(client, "app", tenant=t)          # come una Session SQLAlchemy: repository, tenant
    Repository(ms).get_by_id(id)
    run_in_mongo_transaction(client, "app", lambda ms: ..., tenant=t)   # transazione (replica set)
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence, TypeVar

from bson.decimal128 import Decimal128
from bson.int64 import Int64
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from ._paging import OrderItem, Page, PageRequest, PagingSpec, decode_cursor, encode_cursor, prepare_page
from ._tenant import bind_tenant

T = TypeVar("T")
COUNTERS = "kybes_counters"


class MongoSession:
    """Sessione del modello su MongoDB: database, sessione del driver (in una transazione) e contesto (tenant)."""

    def __init__(self, db: Any, session: Any = None) -> None:
        self.db = db
        self.session = session
        self.info: Dict[str, Any] = {}


def mongo_session(client: Any, database: str, tenant: Any = None) -> MongoSession:
    """Sessione sul database indicato; con tenant lo lega subito (bind_tenant)."""
    ms = MongoSession(client[database])
    bind_tenant(ms, tenant)
    return ms


def run_in_mongo_transaction(client: Any, database: str, work: Callable[[MongoSession], T], tenant: Any = None) -> T:
    """Esegue work in una transazione MongoDB (serve un replica set): conferma se riesce, annulla se solleva.
    Il driver ripete da solo gli errori transitori (TransientTransactionError)."""
    with client.start_session() as s:
        return s.with_transaction(lambda driver_session: work(_bound(MongoSession(client[database], driver_session), tenant)))


def _bound(ms: MongoSession, tenant: Any) -> MongoSession:
    bind_tenant(ms, tenant)
    return ms


def to_bson(value: Any, typ: str) -> Any:
    """Valore del modello nel formato dei documenti (uuid stringa, decimal Decimal128, date a mezzanotte UTC)."""
    if value is None:
        return None
    if typ == "uuid":
        return str(value)
    if typ == "decimal":
        return Decimal128(Decimal(str(value)))
    if typ == "bigint":
        return Int64(value)
    if typ == "date":
        return datetime.combine(value, time(), tzinfo=timezone.utc)
    if typ == "datetime":
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return value


def from_bson(value: Any, typ: str) -> Any:
    if value is None:
        return None
    if typ == "uuid":
        return uuid.UUID(value)
    if typ == "decimal":
        return value.to_decimal()
    if typ == "bigint":
        return int(value)
    if typ == "date":
        return value.date()
    if typ == "datetime":
        return value.replace(tzinfo=timezone.utc)  # il driver restituisce UTC senza fuso
    return value


def now_ms() -> datetime:
    """Adesso in UTC, ai millisecondi: la precisione delle date di MongoDB."""
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def next_id(ms: MongoSession, collection: str) -> int:
    """Chiave intera generata: contatore della collection in kybes_counters."""
    doc = ms.db[COUNTERS].find_one_and_update({"_id": collection}, {"$inc": {"seq": 1}}, upsert=True,
                                              return_document=ReturnDocument.AFTER, session=ms.session)
    return int(doc["seq"])


def prefix(value: str) -> Dict[str, str]:
    """Condizione "inizia con" con i caratteri speciali delle espressioni regolari protetti."""
    return {"$regex": "^" + re.escape(value)}


def after(fields: Dict[str, str], order: Sequence[OrderItem], values: Sequence[Any]) -> Dict[str, Any]:
    """(a, b, c) > (x, y, z) espanso campo per campo, rispettando la direzione di ognuno."""
    branches = []
    for i, (attr, _, typ, desc) in enumerate(order):
        cond = {fields[order[j][0]]: to_bson(values[j], order[j][2]) for j in range(i)}
        cond[fields[attr]] = {"$lt" if desc else "$gt": to_bson(values[i], typ)}
        branches.append(cond)
    return {"$or": branches}


def find_sorted(ms: MongoSession, collection: str, flt: Dict[str, Any], fields: Dict[str, str],
                order: Sequence[OrderItem], limit: int) -> List[Dict[str, Any]]:
    sort = [(fields[a], DESCENDING if d else ASCENDING) for a, _, _, d in order]
    return list(ms.db[collection].find(flt, sort=sort, limit=limit, session=ms.session))


def run_mongo_page(ms: MongoSession, collection: str, spec: PagingSpec, fields: Dict[str, str], flt: Dict[str, Any],
                   page: PageRequest, from_doc: Callable[[Dict[str, Any]], T],
                   fixed_order: Optional[List[OrderItem]] = None) -> Page[T]:
    """Pagina a cursore: stesso contratto, stesso cursore e stesse validazioni delle tabelle SQL."""
    order, limit = prepare_page(spec, page, fixed_order)
    if page.cursor:
        flt = {"$and": [flt, after(fields, order, decode_cursor(spec, order, page.cursor))]}
    rows = [from_doc(d) for d in find_sorted(ms, collection, flt, fields, order, limit + 1)]
    more = len(rows) > limit
    rows = rows[:limit]
    return Page(items=rows, next_cursor=encode_cursor(order, rows[-1]) if more and rows else None, limit=limit)
'''


def typescript_file() -> str:
    return header("typescript", "kit") + "/* eslint-disable */\n" + '''// MongoDB per le tabelle con storage: mongo (vedi docs/mongodb.md).
//   const em = mongoSession(client, "app", tenant);            // come un EntityManager: repository, tenant
//   await new Repository(em).getById(id);
//   await runInMongoTransaction(client, "app", async (em) => ..., { tenant });   // transazione (replica set)
import { Decimal128 } from "mongodb";
import type { ClientSession, Collection, Db, Document, Filter, MongoClient, Sort } from "mongodb";
import { decodeCursor, encodeCursor, preparePage } from "./_paging";
import type { OrderItem, Page, PageRequest, PagingSpec, SortType } from "./_paging";
import { bindTenant } from "./_tenant";

export const COUNTERS = "kybes_counters";
/** Chiave dei documenti: quella della tabella (uuid o stringa, intero, int64), non un ObjectId. */
export type KybesId = string | number | bigint;
export interface KybesDocument extends Document {
  _id: KybesId;
}
export type ColumnType = SortType | "text" | "bool" | "json";

/** Sessione del modello su MongoDB: database e sessione del driver (in una transazione); il tenant si lega con bindTenant. */
export class MongoSession {
  constructor(readonly db: Db, readonly session?: ClientSession) {}

  /** Collection con gli int64 letti come bigint (nessuna perdita di precisione). */
  collection(name: string): Collection<KybesDocument> {
    return this.db.collection<KybesDocument>(name, { useBigInt64: true });
  }
}

/** Sessione sul database indicato; con tenant lo lega subito. */
export function mongoSession(client: MongoClient, database: string, tenant: unknown = null): MongoSession {
  const em = new MongoSession(client.db(database));
  bindTenant(em, tenant);
  return em;
}

/** Esegue work in una transazione MongoDB (serve un replica set): conferma se riesce, annulla se solleva.
 *  Il driver ripete da solo gli errori transitori (TransientTransactionError). */
export async function runInMongoTransaction<T>(client: MongoClient, database: string, work: (em: MongoSession) => Promise<T>,
  options: { tenant?: unknown } = {}): Promise<T> {
  const session = client.startSession();
  try {
    let result: T | undefined;
    await session.withTransaction(async () => {
      const em = new MongoSession(client.db(database), session);
      bindTenant(em, options.tenant);
      result = await work(em);
    });
    return result as T;
  } finally {
    await session.endSession();
  }
}

/** Valore del modello nel formato dei documenti (uuid in minuscolo, decimal Decimal128, bigint int64, date a mezzanotte UTC). */
export function toBson(value: unknown, type: ColumnType): unknown {
  if (value === null || value === undefined) return null;
  switch (type) {
    case "uuid": return String(value).toLowerCase();
    case "decimal": return Decimal128.fromString(String(value));
    case "bigint": return BigInt(String(value));
    case "date": return new Date(`${String(value)}T00:00:00.000Z`);
    default: return value;
  }
}

/** Valore di un documento nel tipo del modello (uuid, decimal, bigint e date come stringa, datetime come Date). */
export function fromBson(value: unknown, type: ColumnType): unknown {
  if (value === null || value === undefined) return null;
  switch (type) {
    case "decimal": return (value as Decimal128).toString();
    case "bigint": return String(value);
    case "date": return (value as Date).toISOString().slice(0, 10);
    default: return value;
  }
}

/** Chiave intera generata: contatore della collection in kybes_counters. */
export async function nextId(em: MongoSession, collection: string): Promise<number> {
  const doc = await em.db.collection<{ _id: string; seq: number }>(COUNTERS).findOneAndUpdate(
    { _id: collection }, { $inc: { seq: 1 } }, { upsert: true, returnDocument: "after", session: em.session });
  return Number(doc!.seq);
}

/** Condizione "inizia con" con i caratteri speciali delle espressioni regolari protetti. */
export function prefix(value: string): { $regex: string } {
  return { $regex: "^" + value.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&") };
}

/** (a, b, c) > (x, y, z) espanso campo per campo, rispettando la direzione di ognuno. */
export function after(fields: Record<string, string>, order: OrderItem[], values: unknown[]): Filter<KybesDocument> {
  return {
    $or: order.map((o, i) => {
      const cond: Record<string, unknown> = {};
      for (let j = 0; j < i; j++) cond[fields[order[j].prop]] = toBson(values[j], order[j].type);
      cond[fields[o.prop]] = { [o.desc ? "$lt" : "$gt"]: toBson(values[i], o.type) };
      return cond;
    }),
  };
}

export async function findSorted(em: MongoSession, collection: string, filter: Filter<KybesDocument>, fields: Record<string, string>,
  order: OrderItem[], limit: number): Promise<KybesDocument[]> {
  const sort: Sort = order.map((o) => [fields[o.prop], o.desc ? -1 : 1] as [string, 1 | -1]);
  return em.collection(collection).find(filter, { sort, limit, session: em.session }).toArray();
}

/** Pagina a cursore: stesso contratto, stesso cursore e stesse validazioni delle tabelle SQL. */
export async function runMongoPage<T extends object>(em: MongoSession, collection: string, spec: PagingSpec, fields: Record<string, string>,
  filter: Filter<KybesDocument>, page: PageRequest, fromDocument: (d: KybesDocument) => T, fixedOrder?: OrderItem[]): Promise<Page<T>> {
  const { order, limit } = preparePage(spec, page, fixedOrder);
  const flt = page.cursor ? { $and: [filter, after(fields, order, decodeCursor(spec, order, page.cursor))] } : filter;
  const rows = (await findSorted(em, collection, flt, fields, order, limit + 1)).map(fromDocument);
  const more = rows.length > limit;
  const items = rows.slice(0, limit);
  return { items, nextCursor: more && items.length > 0 ? encodeCursor(order, items[items.length - 1] as Record<string, unknown>) : null, limit };
}
'''


def java_file(pkg: str, id_type: str) -> str:
    jt = "UUID" if id_type == "uuid" else "String"
    return header("java", "kit").rstrip("\n") + f'''
package {pkg}.generated;

import com.mongodb.client.ClientSession;
import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoCollection;
import com.mongodb.client.MongoDatabase;
import com.mongodb.client.model.FindOneAndUpdateOptions;
import com.mongodb.client.model.ReturnDocument;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Function;
import java.util.regex.Pattern;
import org.bson.Document;
import org.bson.types.Decimal128;

/**
 * Sessione del modello su MongoDB (storage: mongo): database, sessione del driver (in una transazione) e tenant.
 * <pre>
 * MongoSession em = MongoSession.open(client, "app", tenant);     // come un EntityManager: repository, tenant
 * new Repository(em).getById(id);
 * MongoSession.transaction(client, "app", em -&gt; ..., tenant);   // transazione (replica set)
 * </pre>
 * Formato dei documenti: uuid stringa, decimal Decimal128, bigint int64, date a mezzanotte UTC, datetime Date (millisecondi).
 */
public final class MongoSession {{
    public static final String COUNTERS = "kybes_counters";

    private final MongoDatabase db;
    private final ClientSession session;
    private {jt} tenant;

    public MongoSession(MongoDatabase db, ClientSession session) {{
        this.db = db;
        this.session = session;
    }}

    /** Sessione sul database indicato; con tenant non nullo lo lega subito. */
    public static MongoSession open(MongoClient client, String database, Object tenant) {{
        MongoSession em = new MongoSession(client.getDatabase(database), null);
        em.bindTenant(tenant);
        return em;
    }}

    /**
     * Esegue work in una transazione MongoDB (serve un replica set): conferma se riesce, annulla se solleva.
     * Il driver ripete da solo gli errori transitori (TransientTransactionError).
     */
    public static <T> T transaction(MongoClient client, String database, Function<MongoSession, T> work, Object tenant) {{
        try (ClientSession s = client.startSession()) {{
            return s.withTransaction(() -> {{
                MongoSession em = new MongoSession(client.getDatabase(database), s);
                em.bindTenant(tenant);
                return work.apply(em);
            }});
        }}
    }}

    public MongoDatabase db() {{
        return db;
    }}

    public ClientSession session() {{
        return session;
    }}

    public MongoCollection<Document> collection(String name) {{
        return db.getCollection(name);
    }}

    /** Lega il tenant alla sessione (null lo scollega). */
    public void bindTenant(Object value) {{
        tenant = value == null ? null : Tenancy.coerce(value);
    }}

    public {jt} requireTenant() {{
        if (tenant == null) throw new Tenancy.TenantException("sessione MongoDB senza tenant: chiama bindTenant(tenant) o usa MongoSession.transaction(..., tenant)");
        return tenant;
    }}

    // ---- operazioni con la sessione del driver, se c'è (transazione)

    public Document findOne(String collection, Document filter) {{
        MongoCollection<Document> c = collection(collection);
        return (session == null ? c.find(filter) : c.find(session, filter)).first();
    }}

    public List<Document> find(String collection, Document filter, Document sort, int limit) {{
        MongoCollection<Document> c = collection(collection);
        return (session == null ? c.find(filter) : c.find(session, filter)).sort(sort).limit(limit).into(new ArrayList<>());
    }}

    public long count(String collection, Document filter, int limit) {{
        com.mongodb.client.model.CountOptions options = new com.mongodb.client.model.CountOptions().limit(limit);
        MongoCollection<Document> c = collection(collection);
        return session == null ? c.countDocuments(filter, options) : c.countDocuments(session, filter, options);
    }}

    public void insert(String collection, Document doc) {{
        MongoCollection<Document> c = collection(collection);
        if (session == null) c.insertOne(doc);
        else c.insertOne(session, doc);
    }}

    public void replace(String collection, Document filter, Document doc) {{
        MongoCollection<Document> c = collection(collection);
        if (session == null) c.replaceOne(filter, doc);
        else c.replaceOne(session, filter, doc);
    }}

    public void updateMany(String collection, Document filter, Document update) {{
        MongoCollection<Document> c = collection(collection);
        if (session == null) c.updateMany(filter, update);
        else c.updateMany(session, filter, update);
    }}

    public void delete(String collection, Document filter) {{
        MongoCollection<Document> c = collection(collection);
        if (session == null) c.deleteOne(filter);
        else c.deleteOne(session, filter);
    }}

    /** Chiave intera generata: contatore della collection in kybes_counters. */
    public long nextId(String collection) {{
        Document filter = new Document("_id", collection);
        Document update = new Document("$inc", new Document("seq", 1));
        FindOneAndUpdateOptions options = new FindOneAndUpdateOptions().upsert(true).returnDocument(ReturnDocument.AFTER);
        MongoCollection<Document> c = collection(COUNTERS);
        Document doc = session == null ? c.findOneAndUpdate(filter, update, options) : c.findOneAndUpdate(session, filter, update, options);
        return ((Number) doc.get("seq")).longValue();
    }}

    // ---- conversioni tra modello e documenti

    /** Valore del modello nel formato dei documenti. */
    public static Object toBson(Object value, String type) {{
        if (value == null) return null;
        return switch (type) {{
            case "uuid" -> value.toString().toLowerCase(java.util.Locale.ROOT);
            case "decimal" -> new Decimal128((BigDecimal) value);
            case "date" -> Date.from(((LocalDate) value).atStartOfDay(ZoneOffset.UTC).toInstant());
            case "datetime" -> Date.from(((OffsetDateTime) value).toInstant());
            case "json" -> Document.parse("{{\\"v\\": " + value + "}}").get("v");
            default -> value;
        }};
    }}

    /** Valore di un documento nel tipo del modello. */
    public static Object fromBson(Object value, String type) {{
        if (value == null) return null;
        return switch (type) {{
            case "uuid" -> UUID.fromString((String) value);
            case "int" -> ((Number) value).intValue();
            case "bigint" -> ((Number) value).longValue();
            case "decimal" -> ((Decimal128) value).bigDecimalValue();
            case "date" -> ((Date) value).toInstant().atOffset(ZoneOffset.UTC).toLocalDate();
            case "datetime" -> ((Date) value).toInstant().atOffset(ZoneOffset.UTC);
            case "json" -> {{
                String json = new Document("v", value).toJson();
                yield json.substring(json.indexOf(':') + 1, json.length() - 1).trim();
            }}
            default -> value;
        }};
    }}

    /** Adesso in UTC, ai millisecondi: la precisione delle date di MongoDB. */
    public static OffsetDateTime nowMs() {{
        return OffsetDateTime.now(ZoneOffset.UTC).truncatedTo(java.time.temporal.ChronoUnit.MILLIS);
    }}

    /** Condizione "inizia con" con i caratteri speciali delle espressioni regolari protetti. */
    public static Document prefix(String value) {{
        return new Document("$regex", "^" + Pattern.quote(value));
    }}

    /** Condizione con più parti in AND. */
    public static Document and(Document... parts) {{
        return new Document("$and", List.of(parts));
    }}

    /** (a, b, c) &gt; (x, y, z) espanso campo per campo, rispettando la direzione di ognuno. */
    public static Document after(Map<String, String> fields, List<Paging.OrderItem> order, List<Object> values) {{
        List<Document> branches = new ArrayList<>();
        for (int i = 0; i < order.size(); i++) {{
            Document cond = new Document();
            for (int j = 0; j < i; j++) cond.append(fields.get(order.get(j).field()), toBson(values.get(j), bsonType(order.get(j).type())));
            Paging.OrderItem o = order.get(i);
            cond.append(fields.get(o.field()), new Document(o.desc() ? "$lt" : "$gt", toBson(values.get(i), bsonType(o.type()))));
            branches.add(cond);
        }}
        return new Document("$or", branches);
    }}

    static String bsonType(Paging.SortType type) {{
        return type.name().toLowerCase(java.util.Locale.ROOT);
    }}

    public static Document sort(Map<String, String> fields, List<Paging.OrderItem> order) {{
        Document sort = new Document();
        for (Paging.OrderItem o : order) sort.append(fields.get(o.field()), o.desc() ? -1 : 1);
        return sort;
    }}

    /** Pagina a cursore: stesso contratto, stesso cursore e stesse validazioni delle tabelle SQL. */
    public <T> Paging.Page<T> runPage(String collection, Paging.Spec spec, Map<String, String> fields, Document filter,
                                      Paging.PageRequest page, List<Paging.OrderItem> fixedOrder, Function<Document, T> fromDocument,
                                      java.util.function.BiFunction<T, String, Object> value) {{
        Paging.Prepared prep = Paging.prepare(spec, page, fixedOrder);
        Document flt = prep.after() == null ? filter : and(filter, after(fields, prep.order(), prep.after()));
        List<T> rows = new ArrayList<>();
        for (Document d : find(collection, flt, sort(fields, prep.order()), prep.limit() + 1)) rows.add(fromDocument.apply(d));
        boolean more = rows.size() > prep.limit();
        List<T> items = more ? new ArrayList<>(rows.subList(0, prep.limit())) : rows;
        String next = more ? Paging.encodeCursor(prep.order(), items.get(items.size() - 1), value) : null;
        return new Paging.Page<>(items, next, prep.limit());
    }}
}}
'''


def csharp_file(ns: str, id_type: str) -> str:
    ct = "Guid" if id_type == "uuid" else "string"
    return header("csharp", "kit") + "// <auto-generated />\n#nullable enable\n" + '''using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using MongoDB.Bson;
using MongoDB.Driver;

namespace ''' + ns + ''';

/// <summary>
/// Sessione del modello su MongoDB (storage: mongo): database, sessione del driver (in una transazione) e tenant.
/// <code>
/// var em = MongoSession.Open(client, "app", tenant);                       // come un AppDbContext: repository, tenant
/// await new Repository(em).GetByIdAsync(id);
/// await MongoSession.TransactionAsync(client, "app", async em =&gt; ..., tenant); // transazione (replica set)
/// </code>
/// Formato dei documenti: uuid stringa, decimal Decimal128, bigint int64, date a mezzanotte UTC, datetime Date (millisecondi).
/// </summary>
public sealed class MongoSession
{
    public const string Counters = "kybes_counters";

    public MongoSession(IMongoDatabase db, IClientSessionHandle? session = null)
    {
        Db = db;
        Session = session;
    }

    public IMongoDatabase Db { get; }

    /// <summary>Sessione del driver: c'è solo dentro TransactionAsync.</summary>
    public IClientSessionHandle? Session { get; }

    /// <summary>Il tenant legato alla sessione, se c'è.</summary>
    public ''' + ct + '''? KybesTenant { get; private set; }

    /// <summary>Lega il tenant alla sessione (null lo scollega).</summary>
    public void BindTenant(object? tenant) => KybesTenant = tenant is null ? null : Tenancy.Coerce(tenant);

    public ''' + ct + ''' RequireTenant() =>
        KybesTenant ?? throw new TenantException("sessione MongoDB senza tenant: chiama BindTenant(tenant) o usa MongoSession.TransactionAsync(..., tenant)");

    /// <summary>Sessione sul database indicato; con tenant non nullo lo lega subito.</summary>
    public static MongoSession Open(IMongoClient client, string database, object? tenant = null)
    {
        var em = new MongoSession(client.GetDatabase(database));
        em.BindTenant(tenant);
        return em;
    }

    /// <summary>
    /// Esegue work in una transazione MongoDB (serve un replica set): conferma se riesce, annulla se solleva.
    /// Il driver ripete da solo gli errori transitori (TransientTransactionError).
    /// </summary>
    public static async Task<T> TransactionAsync<T>(IMongoClient client, string database, Func<MongoSession, Task<T>> work,
        object? tenant = null, CancellationToken ct = default)
    {
        using var handle = await client.StartSessionAsync(cancellationToken: ct);
        return await handle.WithTransactionAsync(async (h, c) =>
        {
            var em = new MongoSession(client.GetDatabase(database), h);
            em.BindTenant(tenant);
            return await work(em);
        }, cancellationToken: ct);
    }

    public IMongoCollection<BsonDocument> Collection(string name) => Db.GetCollection<BsonDocument>(name);

    // ---- operazioni con la sessione del driver, se c'è (transazione)

    private IFindFluent<BsonDocument, BsonDocument> Find(string collection, BsonDocument filter)
    {
        var c = Collection(collection);
        FilterDefinition<BsonDocument> f = filter;
        return Session is null ? c.Find(f) : c.Find(Session, f);
    }

    public async Task<BsonDocument?> FindOneAsync(string collection, BsonDocument filter, CancellationToken ct = default) =>
        await Find(collection, filter).Limit(1).FirstOrDefaultAsync(ct);

    public Task<List<BsonDocument>> FindAsync(string collection, BsonDocument filter, BsonDocument sort, int limit, CancellationToken ct = default) =>
        Find(collection, filter).Sort(sort).Limit(limit).ToListAsync(ct);

    public Task<long> CountAsync(string collection, BsonDocument filter, long? limit = null, CancellationToken ct = default)
    {
        var c = Collection(collection);
        FilterDefinition<BsonDocument> f = filter;
        var options = new CountOptions { Limit = limit };
        return Session is null ? c.CountDocumentsAsync(f, options, ct) : c.CountDocumentsAsync(Session, f, options, ct);
    }

    public Task InsertAsync(string collection, BsonDocument doc, CancellationToken ct = default)
    {
        var c = Collection(collection);
        return Session is null ? c.InsertOneAsync(doc, new InsertOneOptions(), ct) : c.InsertOneAsync(Session, doc, new InsertOneOptions(), ct);
    }

    public Task ReplaceAsync(string collection, BsonDocument filter, BsonDocument doc, CancellationToken ct = default)
    {
        var c = Collection(collection);
        FilterDefinition<BsonDocument> f = filter;
        return Session is null ? c.ReplaceOneAsync(f, doc, new ReplaceOptions(), ct) : c.ReplaceOneAsync(Session, f, doc, new ReplaceOptions(), ct);
    }

    public Task UpdateManyAsync(string collection, BsonDocument filter, BsonDocument update, CancellationToken ct = default)
    {
        var c = Collection(collection);
        FilterDefinition<BsonDocument> f = filter;
        UpdateDefinition<BsonDocument> u = update;
        return Session is null ? c.UpdateManyAsync(f, u, new UpdateOptions(), ct) : c.UpdateManyAsync(Session, f, u, new UpdateOptions(), ct);
    }

    public Task DeleteAsync(string collection, BsonDocument filter, CancellationToken ct = default)
    {
        var c = Collection(collection);
        FilterDefinition<BsonDocument> f = filter;
        return Session is null ? c.DeleteOneAsync(f, ct) : c.DeleteOneAsync(Session, f, new DeleteOptions(), ct);
    }

    /// <summary>Chiave intera generata: contatore della collection in kybes_counters.</summary>
    public async Task<long> NextIdAsync(string collection, CancellationToken ct = default)
    {
        var c = Collection(Counters);
        FilterDefinition<BsonDocument> f = new BsonDocument("_id", collection);
        UpdateDefinition<BsonDocument> u = new BsonDocument("$inc", new BsonDocument("seq", 1));
        var options = new FindOneAndUpdateOptions<BsonDocument> { IsUpsert = true, ReturnDocument = ReturnDocument.After };
        var doc = Session is null ? await c.FindOneAndUpdateAsync(f, u, options, ct) : await c.FindOneAndUpdateAsync(Session, f, u, options, ct);
        return doc["seq"].ToInt64();
    }

    // ---- conversioni tra modello e documenti

    /// <summary>Valore del modello nel formato dei documenti.</summary>
    public static BsonValue ToBson(object? value, string type)
    {
        if (value is null) return BsonNull.Value;
        return type switch
        {
            "uuid" => new BsonString(value.ToString()!.ToLowerInvariant()),
            "decimal" => new BsonDecimal128((decimal)value),
            "bigint" => new BsonInt64(Convert.ToInt64(value, CultureInfo.InvariantCulture)),
            "int" => new BsonInt32(Convert.ToInt32(value, CultureInfo.InvariantCulture)),
            "date" => new BsonDateTime(((DateOnly)value).ToDateTime(TimeOnly.MinValue, DateTimeKind.Utc)),
            "datetime" => new BsonDateTime(((DateTimeOffset)value).UtcDateTime),
            "json" => BsonDocument.Parse("{\\"v\\": " + value + "}")["v"],
            "bool" => (bool)value ? BsonBoolean.True : BsonBoolean.False,
            _ => new BsonString((string)value),
        };
    }

    /// <summary>Valore di un documento nel tipo del modello.</summary>
    public static object? FromBson(BsonValue? value, string type)
    {
        if (value is null || value.IsBsonNull) return null;
        return type switch
        {
            "uuid" => Guid.Parse(value.AsString),
            "decimal" => Decimal128.ToDecimal(value.AsDecimal128),
            "bigint" => value.ToInt64(),
            "int" => value.ToInt32(),
            "date" => DateOnly.FromDateTime(value.ToUniversalTime()),
            "datetime" => new DateTimeOffset(value.ToUniversalTime(), TimeSpan.Zero),
            "json" => Compact(new BsonDocument("v", value).ToJson()),
            "bool" => value.AsBoolean,
            _ => value.AsString,
        };
    }

    /// <summary>{"v": x} in JSON compatto → x.</summary>
    private static string Compact(string wrapped)
    {
        using var doc = JsonDocument.Parse(wrapped);
        return JsonSerializer.Serialize(doc.RootElement.GetProperty("v"));
    }

    /// <summary>Adesso in UTC, ai millisecondi: la precisione delle date di MongoDB.</summary>
    public static DateTimeOffset NowMs()
    {
        var now = DateTimeOffset.UtcNow;
        return now.AddTicks(-(now.Ticks % TimeSpan.TicksPerMillisecond));
    }

    /// <summary>Condizione "inizia con" con i caratteri speciali delle espressioni regolari protetti.</summary>
    public static BsonDocument Prefix(string value) => new("$regex", "^" + Regex.Escape(value));

    /// <summary>Condizione con più parti in AND.</summary>
    public static BsonDocument And(params BsonDocument[] parts) => new("$and", new BsonArray(parts));

    private static string BsonType(SortType type) => type switch
    {
        SortType.Uuid => "uuid",
        SortType.Int => "int",
        SortType.BigInt => "bigint",
        SortType.Decimal => "decimal",
        SortType.Date => "date",
        SortType.DateTime => "datetime",
        _ => "string",
    };

    /// <summary>(a, b, c) &gt; (x, y, z) espanso campo per campo, rispettando la direzione di ognuno.</summary>
    public static BsonDocument After(IReadOnlyDictionary<string, string> fields, IReadOnlyList<OrderItem> order, IReadOnlyList<object> values)
    {
        var branches = new BsonArray();
        for (var i = 0; i < order.Count; i++)
        {
            var cond = new BsonDocument();
            for (var j = 0; j < i; j++) cond.Add(fields[order[j].Prop], ToBson(values[j], BsonType(order[j].Type)));
            cond.Add(fields[order[i].Prop], new BsonDocument(order[i].Desc ? "$lt" : "$gt", ToBson(values[i], BsonType(order[i].Type))));
            branches.Add(cond);
        }
        return new BsonDocument("$or", branches);
    }

    public static BsonDocument Sort(IReadOnlyDictionary<string, string> fields, IEnumerable<OrderItem> order)
    {
        var sort = new BsonDocument();
        foreach (var o in order) sort.Add(fields[o.Prop], o.Desc ? -1 : 1);
        return sort;
    }

    /// <summary>Pagina a cursore: stesso contratto, stesso cursore e stesse validazioni delle tabelle SQL.</summary>
    public async Task<Page<T>> RunPageAsync<T>(string collection, PagingSpec spec, IReadOnlyDictionary<string, string> fields, BsonDocument filter,
        PageRequest? page, IReadOnlyList<OrderItem>? fixedOrder, Func<BsonDocument, T> fromDocument, CancellationToken ct = default) where T : class
    {
        var (order, limit, after) = Paging.Prepare(spec, page, fixedOrder);
        var flt = after is null ? filter : And(filter, After(fields, order, after));
        var rows = (await FindAsync(collection, flt, Sort(fields, order), limit + 1, ct)).Select(fromDocument).ToList();
        var more = rows.Count > limit;
        var items = more ? rows.GetRange(0, limit) : rows;
        return new Page<T>(items, more ? Paging.EncodeCursor(order, items[^1]) : null, limit);
    }
}
'''
