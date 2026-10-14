"""Moduli comuni delle API generate in TypeScript: validatore, router e middleware, identità, dati, conversioni, adattatori."""
from __future__ import annotations

from typing import Dict

from naming import header
from sqlonly import strip_sql

HEAD = header("typescript", "kit") + "/* eslint-disable */\n"

SCHEMA = r'''// Validatore del sottoinsieme di JSON Schema (OpenAPI 3.0) usato dal contratto delle API: stesse regole e stessi
// testi in tutti i linguaggi. Per ogni campo si riporta la prima regola violata.
export type Schema = Record<string, any>;

const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const DATE = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/;
const DATE_TIME = /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]{1,9})?(Z|[+-]([0-9]{2}):([0-9]{2}))$/;
const INTEGER = /^-?[0-9]+$/;
const NUMBER = /^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$/;

/** Numero nel testo di una regola: gli interi senza decimali. */
export function num(x: number): string {
  return String(x);
}

function validDate(y: string, m: string, d: string): boolean {
  const dt = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d)));
  return dt.getUTCFullYear() === Number(y) && dt.getUTCMonth() === Number(m) - 1 && dt.getUTCDate() === Number(d);
}

export function checkFormat(fmt: string, s: string): boolean {
  if (fmt === "uuid") return UUID.test(s);
  if (fmt === "date") {
    const m = DATE.exec(s);
    return m !== null && validDate(m[1], m[2], m[3]);
  }
  const m = DATE_TIME.exec(s);
  if (m === null || !validDate(m[1], m[2], m[3])) return false;
  if (Number(m[4]) > 23 || Number(m[5]) > 59 || Number(m[6]) > 59) return false;
  return m[8] === "Z" || (Number(m[9]) <= 23 && Number(m[10]) <= 59);
}

/** Tipo JSON di un valore non nullo (il nullo lo gestisce validate). */
export function typeOf(v: unknown): string {
  if (typeof v === "boolean") return "boolean";
  if (typeof v === "number") return Number.isInteger(v) ? "integer" : "number";
  if (typeof v === "string") return "string";
  if (Array.isArray(v)) return "array";
  return typeof v === "object" ? "object" : "unknown";
}

function same(a: unknown, b: unknown): boolean {
  if (typeOf(a) !== typeOf(b)) return false;
  if (typeof a !== "object" || a === null) return a === b;
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Aggiunge a errors {percorso: regola} le violazioni di value; un solo errore per percorso. */
export function validate(schema: Schema, value: unknown, path: string, errors: Record<string, string>): void {
  const where = path || "body";
  if (where in errors) return;
  if (value === null || value === undefined) {
    if (!schema.nullable && "type" in schema) errors[where] = "nullo non ammesso";
    return;
  }
  const t = typeOf(value);
  const want = schema.type;
  if (want && !(t === want || (want === "number" && t === "integer"))) {
    errors[where] = `tipo atteso: ${want}`;
    return;
  }
  if ("enum" in schema && !(schema.enum as unknown[]).some((e) => same(e, value))) {
    errors[where] = "valore non ammesso";
    return;
  }
  if (t === "string") {
    const s = value as string;
    const n = [...s].length;
    if ("minLength" in schema && n < schema.minLength) errors[where] = `lunghezza minima ${schema.minLength}`;
    else if ("maxLength" in schema && n > schema.maxLength) errors[where] = `lunghezza massima ${schema.maxLength}`;
    else if ("pattern" in schema && !new RegExp(schema.pattern).test(s)) errors[where] = "formato non valido";
    else if ("format" in schema && !checkFormat(schema.format, s)) errors[where] = `formato ${schema.format}`;
  } else if (t === "integer" || t === "number") {
    const x = value as number;
    if ("minimum" in schema && x < schema.minimum) errors[where] = `valore minimo ${num(schema.minimum)}`;
    else if ("maximum" in schema && x > schema.maximum) errors[where] = `valore massimo ${num(schema.maximum)}`;
  } else if (t === "array") {
    const a = value as unknown[];
    if ("minItems" in schema && a.length < schema.minItems) errors[where] = `almeno ${schema.minItems} elementi`;
    else if ("maxItems" in schema && a.length > schema.maxItems) errors[where] = `al massimo ${schema.maxItems} elementi`;
    else if ("items" in schema) a.forEach((item, i) => validate(schema.items, item, `${path}[${i}]`, errors));
  } else if (t === "object") {
    const o = value as Record<string, unknown>;
    const props: Record<string, Schema> = schema.properties ?? {};
    const prefix = path ? `${path}.` : "";
    for (const name of (schema.required ?? []) as string[]) {
      if (!(name in o) && !(prefix + name in errors)) errors[prefix + name] = "obbligatorio";
    }
    for (const [name, sub] of Object.entries(props)) {
      if (name in o) validate(sub, o[name], prefix + name, errors);
    }
    const extra = schema.additionalProperties ?? true;
    for (const name of Object.keys(o)) {
      if (name in props) continue;
      if (extra === false) {
        if (!(prefix + name in errors)) errors[prefix + name] = "non ammesso";
      } else if (typeof extra === "object") {
        validate(extra, o[name], prefix + name, errors);
      }
    }
  }
}

/** Valore di un parametro di path o query (testo) nel tipo dello schema: [valore, regola violata o null]. */
export function coerce(schema: Schema, raw: string[]): [unknown, string | null] {
  if (schema.type === "array") {
    const out: unknown[] = [];
    for (const r of raw) {
      const [v, err] = coerce(schema.items ?? {}, [r]);
      if (err) return [null, err];
      out.push(v);
    }
    return [out, null];
  }
  if (raw.length !== 1) return [null, "un solo valore"];
  const r = raw[0];
  if (schema.type === "integer") return INTEGER.test(r) ? [Number(r), null] : [null, "tipo atteso: integer"];
  if (schema.type === "number") return NUMBER.test(r) ? [Number(r), null] : [null, "tipo atteso: number"];
  if (schema.type === "boolean") return r === "true" || r === "false" ? [r === "true", null] : [null, "tipo atteso: boolean"];
  return [r, null];
}
'''

HTTP = r'''// Richieste, risposte ed errori delle API generate: indipendenti dal framework e dal runtime (Lambda, node:http, Fastify).

/** Errore -> stato HTTP; il messaggio pubblico non contiene dettagli (che restano nei log, con il correlationId). */
export const STATUS: Record<string, number> = {
  VALIDATION: 400, AUTH: 401, FORBIDDEN: 403, NOT_FOUND: 404, METHOD_NOT_ALLOWED: 405, CONFLICT: 409,
  UNSUPPORTED_MEDIA_TYPE: 415, UNPROCESSABLE: 422, INTERNAL: 500, TRANSIENT: 503,
};
export const MESSAGE: Record<string, string> = {
  VALIDATION: "Richiesta non valida", AUTH: "Autenticazione richiesta", FORBIDDEN: "Operazione non consentita",
  NOT_FOUND: "Risorsa non trovata", METHOD_NOT_ALLOWED: "Metodo non ammesso", CONFLICT: "Conflitto con lo stato attuale",
  UNSUPPORTED_MEDIA_TYPE: "Serve un corpo application/json", UNPROCESSABLE: "Dati non accettati dal modello",
  INTERNAL: "Errore interno", TRANSIENT: "Servizio temporaneamente non disponibile",
};

/** Chi chiama: claim già verificati dal gateway (mai il token grezzo). */
export interface Identity {
  subject: string | null;
  tenant: string | null;
  scopes: ReadonlySet<string>;
  claims: Record<string, unknown>;
}

export interface ApiRequest {
  method: string;
  path: string;
  query: Record<string, string[]>;
  headers: Record<string, string>;   // nomi in minuscolo
  body: Uint8Array | null;
  identity: Identity | null;
}

export interface ApiResponse {
  status: number;
  body: unknown;                       // JSON serializzabile; undefined per 204
  headers: Record<string, string>;
}

/** Errore applicativo con esito HTTP: kind è una chiave di STATUS, fields {campo: regola}. */
export class ApiError extends Error {
  constructor(public readonly kind: string, public readonly code: string, public readonly fields: Record<string, string> = {}) {
    super(code);
    this.name = "ApiError";
  }
}

/** Input già validato di un'operazione, passato al controller generato o al metodo del service. */
export interface Call {
  operation: string;
  path: Record<string, unknown>;
  query: Record<string, unknown>;
  body: unknown;
  identity: Identity;
  correlationId: string;
  tenant: string | null;
}

export function response(status: number, body?: unknown, headers: Record<string, string> = {}): ApiResponse {
  return { status, body, headers };
}

export function isResponse(x: unknown): x is ApiResponse {
  return typeof x === "object" && x !== null && (x as Record<string, unknown>)[RESPONSE] === true;
}

/** Marca una risposta costruita dal service (stato e header propri). */
export const RESPONSE = "__kybesResponse";

export function reply(status: number, body?: unknown, headers: Record<string, string> = {}): ApiResponse {
  return { status, body, headers, [RESPONSE]: true } as ApiResponse;
}

export function errorBody(kind: string, code: string, cid: string, fields?: Record<string, string>): unknown {
  const error: Record<string, unknown> = { code, message: MESSAGE[kind], correlationId: cid };
  if (fields && Object.keys(fields).length) error.fields = fields;
  return { error };
}

export function anonymous(): Identity {
  return { subject: null, tenant: null, scopes: new Set(), claims: {} };
}
'''

IDENTITY = r'''// Identità dai claim già verificati dal gateway: requestContext.authorizer (Lambda) o header impostati dal gateway.
// Il servizio non verifica il token: deve essere raggiungibile solo dal gateway (rete privata, VPC link), che
// sovrascrive gli header di identità a ogni richiesta.
import type { Identity } from "./_http";

export const CLAIMS: { subject: string; tenant: string; scopes: string[] } = __CLAIMS__;
export const HEADERS: { subject: string; tenant: string; scopes: string } = __HEADERS__;

/** Scope da un claim: lista, "a b", "a,b" o "[a b]" (forma degli array nei claim di API Gateway HTTP API). */
export function scopesOf(value: unknown): string[] {
  if (value === null || value === undefined) return [];
  if (Array.isArray(value)) return value.map((x) => String(x));
  let text = String(value).trim();
  if (text.startsWith("[") && text.endsWith("]")) text = text.slice(1, -1);
  return text.replace(/,/g, " ").split(/\s+/).filter((s) => s.length > 0);
}

function opt(v: unknown): string | null {
  return v === null || v === undefined || v === "" ? null : String(v);
}

export function fromClaims(claims: Record<string, unknown>): Identity {
  const scopes = new Set<string>();
  for (const name of CLAIMS.scopes) for (const s of scopesOf(claims[name])) scopes.add(s);
  return { subject: opt(claims[CLAIMS.subject]), tenant: opt(claims[CLAIMS.tenant]), scopes, claims: { ...claims } };
}

/** API Gateway: HTTP API (authorizer.jwt.claims o authorizer.lambda) o REST API (authorizer.claims o contesto). */
export function fromLambda(event: Record<string, any>): Identity | null {
  const auth = (event.requestContext ?? {}).authorizer;
  if (typeof auth !== "object" || auth === null) return null;
  let claims = auth.jwt?.claims ?? auth.lambda ?? auth.claims ?? auth;
  if (typeof claims === "string") claims = JSON.parse(claims); // authorizer Lambda di REST API: claim come JSON
  return fromClaims(claims);
}

/** Kubernetes dietro il gateway: claim copiati negli header dal parameter mapping del gateway. */
export function fromHeaders(headers: Record<string, string>): Identity | null {
  if (!(HEADERS.subject in headers)) return null;
  const claims: Record<string, unknown> = { [CLAIMS.subject]: headers[HEADERS.subject] };
  if (HEADERS.tenant in headers) claims[CLAIMS.tenant] = headers[HEADERS.tenant];
  if (HEADERS.scopes in headers) claims[CLAIMS.scopes[0]] = headers[HEADERS.scopes];
  return fromClaims(claims);
}
'''

ROUTER = r'''// Router e middleware delle API: correlationId, percorso e metodo, identità e scope, validazione, errori.
// Ordine per ogni richiesta (uguale in tutti i linguaggi):
//   1. correlationId dall'header x-correlation-id (se valido) o nuovo;
//   2. operazione dal percorso (i segmenti fissi vincono sui parametri) e dal metodo: 404 o 405;
//   3. identità obbligatoria per le operazioni protette (401) e scope richiesti (403);
//   4. parametri di path e query: tipi, regole, parametri sconosciuti (400);
//   5. corpo: application/json (415), JSON valido e conforme allo schema (400);
//   6. controller o metodo del service; errori del modello e del database -> 404, 409, 422, 503; il resto -> 500.
import { randomUUID } from "node:crypto";
import { ApiError, STATUS, anonymous, errorBody, isResponse, response } from "./_http";
import type { ApiRequest, ApiResponse, Call } from "./_http";
import { coerce, validate } from "./_schema";
import type { Schema } from "./_schema";
import { ModelValidationError, TenantError } from "../../model/generated";
// kybes:sql-begin
import { isRetryable } from "../../model/generated/_uow";
// kybes:sql-end

const CID = /^[A-Za-z0-9._-]{1,128}$/;
const PAGING_FIELDS = new Set(["limit", "sort", "cursor"]);
const UTF8 = new TextDecoder("utf-8", { fatal: true });

export interface Param { name: string; in: "path" | "query"; required: boolean; schema: Schema }
export interface Spec {
  id: string; method: string; path: string; context: string; kind: string; table: string | null; arg: string | null;
  status: number; secured: boolean; scopes: string[]; params: Param[]; body: Schema | null; bodyRequired: boolean;
}
export type Handler = (call: Call) => unknown | Promise<unknown>;

/** Errore del modello, del database o inatteso -> errore dell'API. */
export function mapError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  if (err instanceof ModelValidationError) {
    const fields = { ...err.fields };
    const keys = Object.keys(fields);
    if (keys.length && keys.every((k) => PAGING_FIELDS.has(k))) return new ApiError("VALIDATION", "INVALID_PAGE", fields);
    if (keys.length && keys.every((k) => fields[k] === "record collegati")) return new ApiError("CONFLICT", "RELATED_RECORDS", fields);
    return new ApiError("UNPROCESSABLE", "MODEL_RULE", fields);
  }
  if (err instanceof TenantError) return new ApiError("FORBIDDEN", "TENANT_REQUIRED");
  const e = (err ?? {}) as Record<string, any>;
  if (e.code === 11000 && String(e.name).startsWith("Mongo")) return new ApiError("CONFLICT", "DUPLICATE");
  // kybes:sql-begin
  const driver = e.driverError ?? {};
  if (e.name === "QueryFailedError" && (String(driver.code ?? "").startsWith("23") || /constraint/i.test(String(e.message)))) {
    return new ApiError("CONFLICT", "CONSTRAINT");
  }
  if (isRetryable(err)) return new ApiError("TRANSIENT", "RETRY_LATER");
  // kybes:sql-end
  return new ApiError("INTERNAL", "UNEXPECTED");
}

export class Route {
  readonly segments: string[];
  constructor(readonly spec: Spec, readonly handler: Handler) {
    this.segments = spec.path.split("/").filter((s) => s.length > 0);
  }

  match(parts: string[]): Record<string, string> | null {
    if (parts.length !== this.segments.length) return null;
    const out: Record<string, string> = {};
    for (let i = 0; i < parts.length; i++) {
      const seg = this.segments[i];
      if (seg.startsWith("{")) out[seg.slice(1, -1)] = parts[i];
      else if (seg !== parts[i]) return null;
    }
    return out;
  }

  /** I segmenti fissi vincono sui parametri, da sinistra a destra. */
  get rank(): string {
    return this.segments.map((s) => (s.startsWith("{") ? "1" : "0")).join("");
  }
}

/** Le operazioni del contratto con i loro handler: handle(ApiRequest) -> ApiResponse. */
export class Api {
  readonly routes: Route[];
  readonly basePath: string;

  constructor(specs: Spec[], handlers: Record<string, Handler>, basePath = "") {
    this.routes = specs.map((s) => new Route(s, handlers[s.id])).sort((a, b) => (a.rank < b.rank ? -1 : a.rank > b.rank ? 1 : 0));
    this.basePath = basePath.replace(/\/+$/, "");
  }

  async handle(req: ApiRequest): Promise<ApiResponse> {
    const given = req.headers["x-correlation-id"] ?? "";
    const cid = CID.test(given) ? given : randomUUID();
    let resp: ApiResponse;
    try {
      resp = await this.dispatch(req, cid);
    } catch (exc) {
      const err = mapError(exc);
      if (err.kind === "INTERNAL") console.error(JSON.stringify({ level: "error", msg: "api: errore inatteso", correlationId: cid, cause: String(exc) }));
      const headers: Record<string, string> = { "content-type": "application/json" };
      const fields = { ...err.fields };
      if (err.kind === "METHOD_NOT_ALLOWED") {
        headers.allow = fields.allow;
        delete fields.allow;
      }
      const shown = ["VALIDATION", "CONFLICT", "UNPROCESSABLE"].includes(err.kind) ? fields : undefined;
      resp = response(STATUS[err.kind], errorBody(err.kind, err.code, cid, shown), headers);
    }
    resp.headers["x-correlation-id"] = cid;
    return resp;
  }

  private find(req: ApiRequest): [Route, Record<string, string>] {
    let path = req.path;
    if (this.basePath && (path === this.basePath || path.startsWith(this.basePath + "/"))) path = path.slice(this.basePath.length);
    const parts = path.split("/").filter((p) => p.length > 0).map((p) => decodeURIComponent(p));
    const allowed: string[] = [];
    for (const r of this.routes) {
      const params = r.match(parts);
      if (params === null) continue;
      if (r.spec.method === req.method.toUpperCase()) return [r, params];
      allowed.push(r.spec.method);
    }
    if (allowed.length) throw new ApiError("METHOD_NOT_ALLOWED", "METHOD_NOT_ALLOWED", { allow: [...new Set(allowed)].sort().join(", ") });
    throw new ApiError("NOT_FOUND", "ROUTE_NOT_FOUND");
  }

  private async dispatch(req: ApiRequest, cid: string): Promise<ApiResponse> {
    const [route, rawPath] = this.find(req);
    const spec = route.spec;
    const identity = req.identity ?? anonymous();
    if (spec.secured && !identity.subject) throw new ApiError("AUTH", "IDENTITY_REQUIRED");
    if (!spec.scopes.every((s) => identity.scopes.has(s))) throw new ApiError("FORBIDDEN", "SCOPE_REQUIRED");
    const errors: Record<string, string> = {};
    const pathVals: Record<string, unknown> = {};
    const queryVals: Record<string, unknown> = {};
    const known = new Set(spec.params.filter((p) => p.in === "query").map((p) => p.name));
    for (const name of Object.keys(req.query)) if (!known.has(name)) errors[name] = "parametro sconosciuto";
    for (const p of spec.params) {
      const raw = p.in === "path" ? [rawPath[p.name]] : req.query[p.name];
      if (raw === undefined) {
        if (p.required && !(p.name in errors)) errors[p.name] = "obbligatorio";
        continue;
      }
      const [value, err] = coerce(p.schema, raw);
      if (err) {
        if (!(p.name in errors)) errors[p.name] = err;
        continue;
      }
      validate(p.schema, value, p.name, errors);
      (p.in === "path" ? pathVals : queryVals)[p.name] = value;
    }
    let body: unknown = null;
    const hasBody = req.body !== null && req.body.length > 0;
    if (spec.body === null) {
      if (hasBody && !("body" in errors)) errors.body = "corpo non ammesso";
    } else if (hasBody) {
      const ctype = (req.headers["content-type"] ?? "").split(";")[0].trim().toLowerCase();
      if (ctype !== "application/json") throw new ApiError("UNSUPPORTED_MEDIA_TYPE", "JSON_REQUIRED");
      try {
        body = JSON.parse(UTF8.decode(req.body as Uint8Array));
      } catch {
        if (!("body" in errors)) errors.body = "JSON non valido";
      }
      if (!("body" in errors)) validate(spec.body, body, "", errors);
    } else if (spec.bodyRequired && !("body" in errors)) {
      errors.body = "obbligatorio";
    }
    if (Object.keys(errors).length) throw new ApiError("VALIDATION", "INVALID_REQUEST", errors);
    const result = await route.handler({ operation: spec.id, path: pathVals, query: queryVals, body, identity, correlationId: cid,
      tenant: identity.tenant });
    if (isResponse(result)) return response(result.status, result.body, { ...result.headers });
    if (spec.status === 204) return response(204, undefined, {});
    return response(spec.status, result, { "content-type": "application/json" });
  }
}
'''

DATA = r'''// Accesso ai dati per i controller generati: letture con il tenant legato, scritture in una Unit of Work
// (tabelle SQL) o in una transazione MongoDB (collection).
// kybes:sql-begin
import type { DataSource, EntityManager } from "typeorm";
import { bindTenant, runInTransaction } from "../../model/generated";
// kybes:sql-end
// kybes:mongo-begin
import type { MongoClient } from "mongodb";
import { mongoSession, runInMongoTransaction } from "../../model/generated";
import type { MongoSession } from "../../model/generated";
// kybes:mongo-end

export interface ApiDataOptions {
  // kybes:sql-begin
  /** DataSource TypeORM, oppure sqlFor(tenant) per le tabelle con tenancy schema o database. */
  dataSource?: DataSource;
  sqlFor?: (tenant: string | null) => DataSource;
  /** nomi dei livelli di isolamento per il database in uso (vedi _uow.ts) */
  levels?: Record<string, string | null>;
  // kybes:sql-end
  // kybes:mongo-begin
  mongoClient?: MongoClient;
  mongoDatabase?: string;
  mongoDatabaseFor?: (tenant: string | null) => string;
  // kybes:mongo-end
}

export class ApiData {
  constructor(readonly options: ApiDataOptions = {}) {}

  // kybes:sql-begin
  private sql(tenant: string | null): DataSource {
    const ds = this.options.sqlFor ? this.options.sqlFor(tenant) : this.options.dataSource;
    if (!ds) throw new Error("ApiData: serve dataSource (o sqlFor) per le tabelle SQL");
    return ds;
  }

  async read<T>(tenant: string | null, work: (em: EntityManager) => Promise<T>): Promise<T> {
    const em = this.sql(tenant).createEntityManager();
    if (tenant !== null) bindTenant(em, tenant);
    return work(em);
  }

  async write<T>(tables: string[], tenant: string | null, work: (em: EntityManager) => Promise<T>): Promise<T> {
    return runInTransaction(this.sql(tenant), work, { tables, tenant, levels: this.options.levels as never });
  }
  // kybes:sql-end

  // kybes:mongo-begin
  private mongo(tenant: string | null): [MongoClient, string] {
    const client = this.options.mongoClient;
    if (!client) throw new Error("ApiData: serve mongoClient per le collection MongoDB");
    return [client, this.options.mongoDatabaseFor ? this.options.mongoDatabaseFor(tenant) : (this.options.mongoDatabase as string)];
  }

  async mongoRead<T>(tenant: string | null, work: (em: MongoSession) => Promise<T>): Promise<T> {
    const [client, db] = this.mongo(tenant);
    return work(mongoSession(client, db, tenant));
  }

  async mongoWrite<T>(tenant: string | null, work: (em: MongoSession) => Promise<T>): Promise<T> {
    const [client, db] = this.mongo(tenant);
    return runInMongoTransaction(client, db, work, { tenant });
  }
  // kybes:mongo-end
}
'''

CONVERT = r'''// Conversioni tra il JSON delle API e i valori del modello (uguali in tutti i linguaggi): uuid, bigint e decimal come
// stringhe; date "AAAA-MM-GG"; datetime ISO 8601 in UTC al millisecondo ("...Z").
const DT = /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,9}))?(Z|([+-])([0-9]{2}):([0-9]{2}))$/;

export function toUuid(v: unknown): string | null {
  return v === null || v === undefined ? null : String(v).toLowerCase();
}

export function toDatetime(v: unknown): Date | null {
  if (v === null || v === undefined) return null;
  const m = DT.exec(String(v)) as RegExpExecArray;
  const ms = Number((m[7] ?? "0").padEnd(3, "0").slice(0, 3));
  const offset = m[8] === "Z" ? 0 : (m[9] === "+" ? 1 : -1) * (Number(m[10]) * 60 + Number(m[11]));
  return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6]), ms) - offset * 60000);
}

export function text(v: unknown): string | null {
  return v === null || v === undefined ? null : String(v);
}

export function uuidText(v: unknown): string | null {
  return v === null || v === undefined ? null : String(v).toLowerCase();
}

/** Decimale con esattamente scale cifre dopo la virgola, senza passare dai numeri in virgola mobile. */
export function decimalText(v: unknown, scale: number): string | null {
  if (v === null || v === undefined) return null;
  let s = String(v);
  const neg = s.startsWith("-");
  if (neg) s = s.slice(1);
  let [whole, frac = ""] = s.split(".");
  frac = frac.padEnd(scale, "0").slice(0, scale);
  whole = whole.replace(/^0+(?=[0-9])/, "");
  return (neg ? "-" : "") + whole + (scale ? "." + frac : "");
}

export function dateText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  return v instanceof Date ? v.toISOString().slice(0, 10) : String(v).slice(0, 10);
}

export function datetimeText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  return (v instanceof Date ? v : new Date(String(v))).toISOString();
}
'''

LAMBDA = r'''// Adattatore AWS Lambda (API Gateway HTTP API v2 e REST API v1): evento -> ApiRequest -> risposta proxy.
import type { ApiRequest, ApiResponse } from "./_http";
import { fromLambda } from "./_identity";
import type { Api } from "./_router";

export function toRequest(event: Record<string, any>): ApiRequest {
  const headers: Record<string, string> = {};
  for (const [k, v] of Object.entries(event.headers ?? {})) headers[k.toLowerCase()] = String(v);
  let body: Uint8Array | null = null;
  if (event.body !== null && event.body !== undefined) {
    body = event.isBase64Encoded ? Buffer.from(String(event.body), "base64") : Buffer.from(String(event.body), "utf8");
  }
  const query: Record<string, string[]> = {};
  let method: string;
  let path: string;
  if (event.version === "2.0") {
    method = event.requestContext.http.method;
    path = event.rawPath || "/";
    for (const [k, v] of new URLSearchParams(event.rawQueryString ?? "")) (query[k] ??= []).push(v);
  } else {
    method = event.httpMethod;
    path = event.path || "/";
    const multi = event.multiValueQueryStringParameters;
    if (multi) for (const [k, v] of Object.entries(multi)) query[k] = (v as unknown[]).map(String);
    else for (const [k, v] of Object.entries(event.queryStringParameters ?? {})) query[k] = [String(v)];
  }
  return { method, path, query, headers, body, identity: fromLambda(event) };
}

export function toProxy(resp: ApiResponse): Record<string, unknown> {
  return { statusCode: resp.status, headers: { ...resp.headers }, isBase64Encoded: false,
    body: resp.body === undefined ? "" : JSON.stringify(resp.body) };
}

/** export const handler = lambdaHandler(buildApi(...)): il punto d'ingresso della function. */
export function lambdaHandler(api: Api): (event: Record<string, any>) => Promise<Record<string, unknown>> {
  return async (event) => toProxy(await api.handle(toRequest(event)));
}
'''

NODE_HTTP = r'''// Adattatore node:http senza framework, per i microservizi su Kubernetes dietro il gateway.
import type { IncomingMessage, ServerResponse } from "node:http";
import type { ApiRequest, ApiResponse } from "./_http";
import { fromHeaders } from "./_identity";
import type { Api } from "./_router";

export async function readRequest(req: IncomingMessage): Promise<ApiRequest> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  const body = Buffer.concat(chunks);
  const headers: Record<string, string> = {};
  for (const [k, v] of Object.entries(req.headers)) headers[k] = Array.isArray(v) ? v.join(", ") : String(v);
  const url = new URL(req.url ?? "/", "http://localhost");
  const query: Record<string, string[]> = {};
  for (const [k, v] of url.searchParams) (query[k] ??= []).push(v);
  return { method: req.method ?? "GET", path: url.pathname, query, headers, body: body.length ? body : null, identity: fromHeaders(headers) };
}

export function writeResponse(res: ServerResponse, resp: ApiResponse): void {
  res.writeHead(resp.status, resp.headers);
  res.end(resp.body === undefined ? "" : JSON.stringify(resp.body));
}

/** createServer(httpHandler(buildApi(...))).listen(8080) */
export function httpHandler(api: Api): (req: IncomingMessage, res: ServerResponse) => Promise<void> {
  return async (req, res) => writeResponse(res, await api.handle(await readRequest(req)));
}
'''

FASTIFY = r'''// Adattatore Fastify: ogni operazione del contratto diventa una route; validazione, errori e identità restano del
// nucleo. Tipi strutturali: il pacchetto non dipende da fastify, che serve solo a chi usa questo adattatore.
import type { ApiResponse } from "./_http";
import { fromHeaders } from "./_identity";
import type { Api } from "./_router";

export interface FastifyRequestLike {
  method: string;
  url: string;
  headers: Record<string, string | string[] | undefined>;
  body?: unknown;
}
export interface FastifyReplyLike {
  code(status: number): FastifyReplyLike;
  headers(values: Record<string, string>): FastifyReplyLike;
  send(payload?: unknown): unknown;
}
export interface FastifyLike {
  removeAllContentTypeParsers(): unknown;
  route(options: { method: string | string[]; url: string; handler: (req: any, reply: any) => Promise<unknown>; config?: any }): unknown;
  addContentTypeParser(type: string | string[] | RegExp, options: { parseAs: "buffer" }, parser: (req: any, body: Buffer, done: (err: Error | null, body?: unknown) => void) => void): unknown;
}

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

/** includeApi(fastify(), api): il corpo arriva grezzo al nucleo, che lo valida con il contratto. */
export function includeApi<T extends FastifyLike>(app: T, api: Api): T {
  app.removeAllContentTypeParsers();
  app.addContentTypeParser("*", { parseAs: "buffer" }, (_req, body, done) => done(null, body));
  const handler = async (req: FastifyRequestLike, reply: FastifyReplyLike): Promise<unknown> => {
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(req.headers)) if (v !== undefined) headers[k.toLowerCase()] = Array.isArray(v) ? v.join(", ") : v;
    const url = new URL(req.url, "http://localhost");
    const query: Record<string, string[]> = {};
    for (const [k, v] of url.searchParams) (query[k] ??= []).push(v);
    const body = req.body instanceof Uint8Array && req.body.length ? req.body : null;
    const resp: ApiResponse = await api.handle({ method: req.method, path: url.pathname, query, headers, body, identity: fromHeaders(headers) });
    return reply.code(resp.status).headers(resp.headers).send(resp.body === undefined ? "" : JSON.stringify(resp.body));
  };
  for (const r of api.routes) {
    app.route({ method: r.spec.method, url: api.basePath + r.spec.path.replace(/\{([^}]+)\}/g, ":$1"), handler, config: { operationId: r.spec.id } });
  }
  app.route({ method: METHODS, url: "/*", handler });
  return app;
}
'''


def _strip_block(text: str, tag: str, keep: bool) -> str:
    out, skip = [], False
    for line in text.split("\n"):
        if f"kybes:{tag}-begin" in line:
            skip = not keep
            continue
        if f"kybes:{tag}-end" in line:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "\n".join(out)


def files(sql: bool, mongo: bool, claims: Dict, headers: Dict) -> Dict[str, str]:
    import json
    data = _strip_block(strip_sql(DATA, sql), "mongo", mongo)
    if sql and mongo:  # un solo import dal model
        data = data.replace('import { bindTenant, runInTransaction } from "../../model/generated";\n', "").replace(
            'import { mongoSession, runInMongoTransaction } from "../../model/generated";',
            'import { bindTenant, mongoSession, runInMongoTransaction, runInTransaction } from "../../model/generated";')
    return {
        "_schema.ts": HEAD + SCHEMA,
        "_http.ts": HEAD + HTTP,
        "_identity.ts": HEAD + IDENTITY.replace("__CLAIMS__", json.dumps(claims)).replace("__HEADERS__", json.dumps(headers)),
        "_router.ts": HEAD + strip_sql(ROUTER, sql),
        "_data.ts": HEAD + data,
        "_convert.ts": HEAD + CONVERT,
        "lambda.ts": HEAD + LAMBDA,
        "http.ts": HEAD + NODE_HTTP,
        "fastify.ts": HEAD + FASTIFY,
    }
