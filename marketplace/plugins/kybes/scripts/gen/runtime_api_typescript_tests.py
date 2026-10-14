"""Test node:test dei moduli comuni delle API TypeScript, con operazioni sintetiche (indipendenti dagli schemi)."""
from __future__ import annotations

import json
from typing import Dict, List

from api_plan import Operation
from naming import header
from schema import Table
from sqlonly import has_sql, strip_sql
from verification import API_RT, METHODS, Catalog

HEAD = r'''/* eslint-disable */
// Test di unità generati per i moduli comuni delle API. Specifica: docs/generated/verification/kybes-api-runtime.md.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { Api, ApiData, ApiError, buildApi, httpHandler, includeApi, lambdaHandler, reply } from "../../src/api/generated";
import type { ApiRequest, Call, Identity } from "../../src/api/generated";
import { dateText, datetimeText, decimalText, text, toDatetime, toUuid, uuidText } from "../../src/api/generated/_convert";
import { errorBody, isResponse, response } from "../../src/api/generated/_http";
import { CLAIMS, HEADERS, fromClaims, fromHeaders, fromLambda, scopesOf } from "../../src/api/generated/_identity";
import { Route, mapError } from "../../src/api/generated/_router";
import type { Spec } from "../../src/api/generated/_router";
import { checkFormat, coerce, num, typeOf, validate } from "../../src/api/generated/_schema";
import { toProxy, toRequest } from "../../src/api/generated/lambda";
import { readRequest } from "../../src/api/generated/http";
import { Readable } from "node:stream";
import { ModelValidationError, TenantError } from "../../src/model/generated";
import { TENANT_A } from "./kybes_builders";
__RUNNERS__

const ID = { name: "id", in: "path" as const, required: true, schema: { type: "integer" } };
const SPECS: Spec[] = [
  { id: "getItem", method: "GET", path: "/items/{id}", context: "uno", kind: "custom", table: null, arg: null, status: 200, secured: true,
    scopes: ["s.read"], body: null, bodyRequired: false,
    params: [ID, { name: "tag", in: "query", required: false, schema: { type: "array", items: { type: "string" } } },
      { name: "n", in: "query", required: true, schema: { type: "integer", minimum: 1 } }] },
  { id: "special", method: "GET", path: "/items/special", context: "uno", kind: "custom", table: null, arg: null, status: 200,
    secured: false, scopes: [], params: [], body: null, bodyRequired: false },
  { id: "putItem", method: "PUT", path: "/items/{id}", context: "due", kind: "custom", table: null, arg: null, status: 200, secured: false,
    scopes: [], params: [ID], bodyRequired: true,
    body: { type: "object", required: ["nome"], properties: { nome: { type: "string", maxLength: 3 } }, additionalProperties: false } },
  { id: "postOpt", method: "POST", path: "/opt", context: "due", kind: "custom", table: null, arg: null, status: 204, secured: false,
    scopes: [], params: [], body: { type: "object" }, bodyRequired: false },
  { id: "boom", method: "POST", path: "/boom", context: "due", kind: "custom", table: null, arg: null, status: 200, secured: false,
    scopes: [], params: [], body: null, bodyRequired: false },
];
const ME: Identity = { subject: "kybes-test", tenant: "t1", scopes: new Set(["s.read"]), claims: {} };
const echo = (call: Call) => ({ op: call.operation, path: call.path, query: call.query, body: call.body });

function synthetic(basePath = "", boom: (call: Call) => unknown = () => { throw new Error("dettaglio interno da non mostrare"); }): Api {
  return new Api(SPECS, { getItem: echo, special: (call: Call) => reply(202, { x: 1 }, { location: call.basePath + "/items/special" }), putItem: echo,
    postOpt: echo, boom }, basePath);
}

function req(method: string, path: string, query: Record<string, string[]> = {}, body: string | Uint8Array | null = null,
  who: Identity | null = ME, headers: Record<string, string> = {}): ApiRequest {
  const raw = typeof body === "string" ? Buffer.from(body, "utf8") : body;
  return { method, path, query, headers: { "content-type": "application/json", ...headers }, body: raw, identity: who };
}
void TENANT_A;
'''

BODIES: Dict[str, List[str]] = {
    "rt_api_validate": [
        "  const cases: [Record<string, unknown>, unknown, string | null][] = [",
        '    [{ type: "string" }, "x", null], [{ type: "string" }, 1, "tipo atteso: string"], [{ type: "integer" }, 2.0, null],',
        '    [{ type: "integer" }, 2.5, "tipo atteso: integer"], [{ type: "number" }, 3, null], [{ type: "boolean" }, 1, "tipo atteso: boolean"],',
        '    [{ type: "string" }, null, "nullo non ammesso"], [{ type: "string", nullable: true }, null, null], [{}, null, null],',
        '    [{ enum: ["a", "b"] }, "c", "valore non ammesso"], [{ enum: ["a", "b"] }, "a", null], [{ enum: [{ a: 1 }] }, { a: 1 }, null],',
        '    [{ type: "string", minLength: 2 }, "a", "lunghezza minima 2"], [{ type: "string", maxLength: 2 }, "àbc", "lunghezza massima 2"],',
        '    [{ type: "string", maxLength: 2 }, "àb", null], [{ type: "string", pattern: "^[0-9]+$" }, "12a", "formato non valido"],',
        '    [{ type: "string", format: "uuid" }, "x", "formato uuid"], [{ type: "string", format: "date" }, "2026-02-30", "formato date"],',
        '    [{ type: "string", format: "date-time" }, "2026-01-01T10:00:00Z", null],',
        '    [{ type: "integer", minimum: 1 }, 0, "valore minimo 1"], [{ type: "number", maximum: 1.5 }, 2, "valore massimo 1.5"],',
        '    [{ type: "number", minimum: 1, maximum: 2 }, 1.5, null],',
        '    [{ type: "array", minItems: 1 }, [], "almeno 1 elementi"], [{ type: "array", maxItems: 1 }, [1, 2], "al massimo 1 elementi"],',
        '    [{ type: "array" }, [1], null], [{ type: "object" }, [], "tipo atteso: object"], [{ type: "array" }, {}, "tipo atteso: array"],',
        '    [{ type: "string", pattern: "^[0-9]+$" }, "12\\n", "formato non valido"], [{ type: "string", pattern: "^(a|b)$|^c$" }, "c", null],',
        '    [{ type: "string", format: "uuid" }, "00000000-0000-4000-8000-00000000000a\\n", "formato uuid"],',
        "  ];",
        "  for (const [schema, value, rule] of cases) {",
        "    const errors: Record<string, string> = {};",
        '    validate(schema, value, "campo", errors);',
        "    assert.deepEqual(errors, rule === null ? {} : { campo: rule }, JSON.stringify([schema, value]));",
        "  }",
        '  const schema = { type: "object", required: ["a", "b"], properties: { a: { type: "array", items: { type: "integer" } },',
        '    o: { type: "object", properties: { x: { type: "string" } }, additionalProperties: { type: "integer" } } }, additionalProperties: false };',
        "  let errors: Record<string, string> = {};",
        '  validate(schema, { a: [1, "x"], o: { x: 1, y: "z", w: 2 }, k: 1 }, "", errors);',
        '  assert.deepEqual(errors, { b: "obbligatorio", "a[1]": "tipo atteso: integer", "o.x": "tipo atteso: string", "o.y": "tipo atteso: integer", k: "non ammesso" });',
        '  errors = { body: "già presente" };',
        '  validate({ type: "string" }, 1, "", errors);',
        '  assert.deepEqual(errors, { body: "già presente" });',
        "  errors = {};",
        '  validate({ type: "object", properties: {} }, { libero: 1 }, "", errors);',
        '  validate({ type: "object", required: ["a"], properties: { a: { type: "string" } }, additionalProperties: false }, { x: 1 }, "p", { "p.a": "x", "p.x": "y" });',
        "  assert.deepEqual(errors, {});",
        '  assert.equal(num(2.0), "2");', '  assert.equal(num(1.5), "1.5");', '  assert.equal(typeOf(undefined), "unknown");',
        '  for (const good of ["2026-01-01T00:00:00.123456789+02:00", "2026-12-31T23:59:59-05:30"]) assert.ok(checkFormat("date-time", good), good);',
        '  for (const bad of ["2026-01-01 10:00:00Z", "2026-02-30T10:00:00Z", "2026-01-01T24:00:00Z", "2026-01-01T10:60:00Z",',
        '    "2026-01-01T10:00:60Z", "2026-01-01T10:00:00+24:00", "2026-01-01T10:00:00+01:60"]) assert.ok(!checkFormat("date-time", bad), bad);',
        '  assert.ok(checkFormat("uuid", "00000000-0000-4000-8000-00000000000A") && checkFormat("date", "2024-02-29"));',
        '  assert.ok(!checkFormat("date", "2026-1-1"));',
        '  assert.ok(checkFormat("date", "0050-01-01") && !checkFormat("date", "0000-01-01"), "anni prima del 100 come negli altri linguaggi");',
        "  errors = Object.create(null);",
        '  validate({ type: "object", required: ["constructor"], additionalProperties: false }, JSON.parse(\'{"__proto__": 1}\'), "", errors);',
        '  assert.deepEqual(Object.entries(errors), [["constructor", "obbligatorio"], ["__proto__", "non ammesso"]]);',
    ],
    "rt_api_coerce": [
        '  assert.deepEqual(coerce({ type: "integer" }, ["-12"]), [-12, null]);',
        '  assert.deepEqual(coerce({ type: "integer" }, ["1.5"]), [null, "tipo atteso: integer"]);',
        '  assert.deepEqual(coerce({ type: "number" }, ["1.5e2"]), [150, null]);',
        '  assert.deepEqual(coerce({ type: "number" }, ["abc"]), [null, "tipo atteso: number"]);',
        '  assert.deepEqual(coerce({ type: "boolean" }, ["true"]), [true, null]);',
        '  assert.deepEqual(coerce({ type: "boolean" }, ["false"]), [false, null]);',
        '  assert.deepEqual(coerce({ type: "boolean" }, ["1"]), [null, "tipo atteso: boolean"]);',
        '  assert.deepEqual(coerce({ type: "string" }, ["x"]), ["x", null]);',
        '  assert.deepEqual(coerce({ type: "string" }, ["x", "y"]), [null, "un solo valore"]);',
        '  assert.deepEqual(coerce({ type: "array", items: { type: "integer" } }, ["1", "2"]), [[1, 2], null]);',
        '  assert.deepEqual(coerce({ type: "array", items: { type: "integer" } }, ["1", "x"]), [null, "tipo atteso: integer"]);',
        '  assert.deepEqual(coerce({ type: "array" }, []), [[], null]);',
        '  assert.deepEqual(coerce({ type: "number" }, ["1e400"]), [null, "tipo atteso: number"]);',
        '  assert.deepEqual(coerce({ type: "integer" }, ["1\\n"]), [null, "tipo atteso: integer"]);',
    ],
    "rt_api_route": [
        "  const api = synthetic();",
        '  let r = await api.handle(req("GET", "/items/special"));',
        '  assert.equal(r.status, 202, "il segmento fisso vince sul parametro");', "  assert.deepEqual(r.body, { x: 1 });",
        '  assert.deepEqual([r.headers["content-type"], r.headers.location], ["application/json", "/items/special"]);',
        '  r = await api.handle(req("GET", "/items/%zz", { n: ["1"] }));',
        '  assert.deepEqual([r.status, (r.body as any).error.fields], [400, { id: "tipo atteso: integer" }]);',
        '  r = await api.handle(req("GET", "/items/special", JSON.parse(\'{"__proto__": ["1"]}\')));',
        '  assert.deepEqual([r.status, Object.entries((r.body as any).error.fields)], [400, [["__proto__", "parametro sconosciuto"]]]);',
        '  r = await api.handle(req("GET", "/items/7", { n: ["2"], tag: ["a", "b"] }));',
        '  assert.equal(r.status, 200);',
        '  assert.deepEqual(r.body, { op: "getItem", path: { id: 7 }, query: { n: 2, tag: ["a", "b"] }, body: null });',
        '  r = await api.handle(req("GET", "/items/%37", { n: ["1"] }));',
        "  assert.deepEqual((r.body as any).path, { id: 7 });",
        '  r = await api.handle(req("GET", "/items/x", { n: ["0"], altro: ["1"] }));',
        '  assert.equal(r.status, 400);',
        '  assert.deepEqual((r.body as any).error.fields, { altro: "parametro sconosciuto", id: "tipo atteso: integer", n: "valore minimo 1" });',
        '  r = await api.handle(req("GET", "/items/7"));',
        '  assert.deepEqual((r.body as any).error.fields, { n: "obbligatorio" });',
        '  r = await api.handle(req("GET", "/items/x", { n: ["x"], tag: ["a"] }, null, null));',
        '  assert.equal(r.status, 401);', '  assert.equal((r.body as any).error.code, "IDENTITY_REQUIRED");',
        '  r = await api.handle(req("GET", "/nessuno"));',
        '  assert.equal(r.status, 404);', '  assert.equal((r.body as any).error.code, "ROUTE_NOT_FOUND");',
        '  assert.equal((await api.handle(req("GET", "/items"))).status, 404);',
        '  r = await api.handle(req("DELETE", "/items/7"));',
        '  assert.equal(r.status, 405);', '  assert.equal(r.headers.allow, "GET, PUT");', '  assert.equal((r.body as any).error.code, "METHOD_NOT_ALLOWED");',
        '  r = await api.handle(req("GET", "/items/7", { n: ["1"] }, null, { ...ME, scopes: new Set() }));',
        '  assert.equal(r.status, 403);', '  assert.equal((r.body as any).error.code, "SCOPE_REQUIRED");',
        '  const based = synthetic("/v1/");',
        '  assert.equal((await based.handle(req("GET", "/v1/items/special"))).headers.location, "/v1/items/special");',
        '  assert.equal((await based.handle(req("GET", "/v1"))).status, 404);',
        '  assert.equal((await based.handle(req("GET", "/items/special"))).status, 202);',
        "  const route = new Route(SPECS[0], echo);",
        '  assert.equal(route.match(["items"]), null);', '  assert.equal(route.match(["altro", "1"]), null);',
        '  assert.deepEqual(route.match(["items", "1"]), { id: "1" });',
        '  const sorted = new Api([SPECS[1], SPECS[0], SPECS[4], SPECS[3]], { getItem: echo, special: echo, boom: echo, postOpt: echo });',
        "  assert.deepEqual(sorted.routes.map((x) => x.spec.id), [\"boom\", \"postOpt\", \"special\", \"getItem\"]);",
    ],
    "rt_api_body": [
        "  const api = synthetic();",
        '  let r = await api.handle(req("PUT", "/items/1", {}, \'{"nome": "abc"}\', ME, { "content-type": "text/plain" }));',
        '  assert.equal(r.status, 415);', '  assert.equal((r.body as any).error.code, "JSON_REQUIRED");',
        '  r = await api.handle(req("PUT", "/items/1", {}, \'{"nome": "abc"}\', ME, { "content-type": "Application/JSON; charset=utf-8" }));',
        '  assert.equal(r.status, 200);', '  assert.deepEqual((r.body as any).body, { nome: "abc" });',
        '  for (const raw of ["{", \'{"nome": NaN}\', new Uint8Array([0xff]), \'{"nome": 1e400}\', new Uint8Array([0xef, 0xbb, 0xbf, 0x7b, 0x7d])]) {',
        '    r = await api.handle(req("PUT", "/items/1", {}, raw));',
        '    assert.equal(r.status, 400);', '    assert.deepEqual((r.body as any).error.fields, { body: "JSON non valido" });', "  }",
        '  r = await api.handle(req("PUT", "/items/1", {}, \'{"nome": "abcd", "x": 1}\'));',
        '  assert.deepEqual((r.body as any).error.fields, { nome: "lunghezza massima 3", x: "non ammesso" });',
        '  r = await api.handle(req("PUT", "/items/1", {}, "[]"));',
        '  assert.deepEqual((r.body as any).error.fields, { body: "tipo atteso: object" });',
        '  r = await api.handle(req("PUT", "/items/1", { body: ["1"] }));',
        '  assert.deepEqual((r.body as any).error.fields, { body: "parametro sconosciuto" });',
        '  r = await api.handle(req("PUT", "/items/1", { body: ["1"] }, "{"));',
        '  assert.deepEqual((r.body as any).error.fields, { body: "parametro sconosciuto" });',
        '  r = await api.handle(req("GET", "/items/special", { body: ["1"] }, "{}"));',
        '  assert.deepEqual((r.body as any).error.fields, { body: "parametro sconosciuto" });',
        '  r = await api.handle(req("PUT", "/items/1"));',
        '  assert.equal(r.status, 400);', '  assert.deepEqual((r.body as any).error.fields, { body: "obbligatorio" });',
        '  r = await api.handle(req("POST", "/opt"));',
        '  assert.equal(r.status, 204);', "  assert.equal(r.body, undefined);",
        '  assert.equal((await api.handle(req("POST", "/opt", {}, \'{"x": 1.5}\'))).status, 204);',
        '  r = await new Api(SPECS, { getItem: echo, special: echo, putItem: echo, postOpt: echo, boom: () => reply(204) }).handle(req("POST", "/boom"));',
        '  assert.deepEqual([r.status, r.headers["content-type"]], [204, undefined]);',
        '  r = await api.handle(req("GET", "/items/special", {}, "{}"));',
        '  assert.equal(r.status, 400);', '  assert.deepEqual((r.body as any).error.fields, { body: "corpo non ammesso" });',
        '  r = await api.handle(req("PUT", "/items/1", {}, "{}", ME, {}));',
        '  assert.deepEqual((r.body as any).error.fields, { nome: "obbligatorio" });',
        '  r = await api.handle({ method: "PUT", path: "/items/1", query: {}, headers: {}, body: Buffer.from("{}"), identity: null });',
        '  assert.equal(r.status, 415);',
    ],
    "rt_api_errors": [
        "  const api = synthetic();",
        '  let r = await api.handle(req("POST", "/boom", {}, null, ME, { "x-correlation-id": "abc-1" }));',
        '  assert.equal(r.status, 500);', '  assert.deepEqual(r.body, errorBody("INTERNAL", "UNEXPECTED", "abc-1"));',
        '  assert.equal(r.headers["x-correlation-id"], "abc-1");', '  assert.ok(!JSON.stringify(r.body).includes("dettaglio"));',
        '  r = await api.handle(req("POST", "/boom", {}, null, ME, { "x-correlation-id": "non valido!" }));',
        '  assert.notEqual(r.headers["x-correlation-id"], "non valido!");',
        '  assert.deepEqual(errorBody("VALIDATION", "X", "c", { a: "b" }), { error: { code: "X", message: "Richiesta non valida", correlationId: "c", fields: { a: "b" } } });',
        '  assert.deepEqual(errorBody("VALIDATION", "X", "c", {}), { error: { code: "X", message: "Richiesta non valida", correlationId: "c" } });',
        '  const same = new ApiError("CONFLICT", "MIO");',
        "  assert.equal(mapError(same), same);", '  assert.deepEqual(new ApiError("NOT_FOUND", "X").fields, {});',
        '  let e = mapError(new ModelValidationError("T", { limit: "tra 1 e 100" }));',
        '  assert.deepEqual([e.kind, e.code, e.fields], ["VALIDATION", "INVALID_PAGE", { limit: "tra 1 e 100" }]);',
        '  e = mapError(new ModelValidationError("T", { Righe: "record collegati" }));',
        '  assert.deepEqual([e.kind, e.code], ["CONFLICT", "RELATED_RECORDS"]);',
        '  e = mapError(new ModelValidationError("T", { Nome: "obbligatorio" }));',
        '  assert.deepEqual([e.kind, e.code], ["UNPROCESSABLE", "MODEL_RULE"]);',
        '  assert.equal(mapError(new ModelValidationError("T", {})).kind, "UNPROCESSABLE");',
        '  assert.equal(mapError(new TenantError("x")).code, "TENANT_REQUIRED");',
        '  assert.equal(mapError(Object.assign(new Error("dup"), { name: "MongoServerError", code: 11000 })).code, "DUPLICATE");',
        '  assert.equal(mapError(Object.assign(new Error("dup"), { name: "Altro", code: 11000 })).code, "UNEXPECTED");',
        '  assert.equal(mapError(new Error("x")).code, "UNEXPECTED");',
        '  assert.equal(mapError(null).code, "UNEXPECTED");',
        "  // kybes:sql-begin",
        '  assert.equal(mapError(Object.assign(new Error("x"), { name: "QueryFailedError", driverError: { code: "23505" } })).code, "CONSTRAINT");',
        '  assert.equal(mapError(Object.assign(new Error("SQLITE_CONSTRAINT: FOREIGN KEY constraint failed"), { name: "QueryFailedError" })).code, "CONSTRAINT");',
        '  assert.equal(mapError(Object.assign(new Error("x"), { name: "QueryFailedError", driverError: { code: "42P01" } })).code, "UNEXPECTED");',
        '  assert.equal(mapError(Object.assign(new Error("x"), { name: "QueryFailedError", driverError: { code: "40001" } })).code, "RETRY_LATER");',
        "  // kybes:sql-end",
        '  r = await synthetic("", () => { throw new ModelValidationError("T", { Nome: "obbligatorio" }); }).handle(req("POST", "/boom"));',
        '  assert.equal(r.status, 422);', '  assert.deepEqual((r.body as any).error.fields, { Nome: "obbligatorio" });',
        '  r = await synthetic("", () => { throw new TenantError("x"); }).handle(req("POST", "/boom"));',
        '  assert.equal(r.status, 403);', '  assert.equal((r.body as any).error.fields, undefined);',
        '  assert.ok(isResponse(reply(200)) && !isResponse(response(200)) && !isResponse(null));',
    ],
    "rt_api_identity": [
        "  assert.deepEqual(scopesOf(null), []);", '  assert.deepEqual(scopesOf(["a", 1]), ["a", "1"]);',
        '  assert.deepEqual(scopesOf("[a b]"), ["a", "b"]);', '  assert.deepEqual(scopesOf("a,b c"), ["a", "b", "c"]);',
        '  let i = fromClaims({ [CLAIMS.subject]: "u1", [CLAIMS.tenant]: "t1", [CLAIMS.scopes[0]]: "a b" });',
        '  assert.deepEqual([i.subject, i.tenant, [...i.scopes]], ["u1", "t1", ["a", "b"]]);',
        '  i = fromClaims({ [CLAIMS.subject]: "", [CLAIMS.tenant]: null });',
        "  assert.deepEqual([i.subject, i.tenant, i.scopes.size], [null, null, 0]);",
        '  assert.equal(fromLambda({}), null);', '  assert.equal(fromLambda({ requestContext: { authorizer: "x" } }), null);',
        '  assert.equal(fromLambda({ requestContext: { authorizer: null } }), null);',
        '  assert.equal(fromLambda({ requestContext: { authorizer: { jwt: { claims: { [CLAIMS.subject]: "a" } } } } })!.subject, "a");',
        '  assert.equal(fromLambda({ requestContext: { authorizer: { lambda: { [CLAIMS.subject]: "b" } } } })!.subject, "b");',
        '  assert.equal(fromLambda({ requestContext: { authorizer: { claims: { [CLAIMS.subject]: "c" } } } })!.subject, "c");',
        '  assert.equal(fromLambda({ requestContext: { authorizer: { [CLAIMS.subject]: "d" } } })!.subject, "d");',
        '  assert.equal(fromLambda({ requestContext: { authorizer: { claims: JSON.stringify({ [CLAIMS.subject]: "e" }) } } })!.subject, "e");',
        "  assert.equal(fromHeaders({}), null);",
        '  i = fromHeaders({ [HEADERS.subject]: "u", [HEADERS.tenant]: "t", [HEADERS.scopes]: "x y" })!;',
        '  assert.deepEqual([i.subject, i.tenant, [...i.scopes]], ["u", "t", ["x", "y"]]);',
        '  assert.equal(fromHeaders({ [HEADERS.subject]: "u" })!.tenant, null);',
    ],
    "rt_api_lambda": [
        "  const handler = lambdaHandler(synthetic());",
        '  const v2 = { version: "2.0", rawPath: "/items/7", rawQueryString: "n=2&tag=a&tag=b", headers: { "Content-Type": "application/json" },',
        '    requestContext: { http: { method: "GET" }, authorizer: { jwt: { claims: { [CLAIMS.subject]: "u", [CLAIMS.scopes[0]]: "s.read" } } } } };',
        "  let out = await handler(v2);",
        "  assert.equal(out.statusCode, 200);", "  assert.equal(out.isBase64Encoded, false);",
        '  assert.deepEqual(JSON.parse(out.body as string).query, { n: 2, tag: ["a", "b"] });',
        '  const put = { httpMethod: "PUT", path: "/items/1", headers: { "content-type": "application/json" },',
        '    body: Buffer.from(\'{"nome": "ab"}\').toString("base64"), isBase64Encoded: true, requestContext: {} };',
        '  assert.deepEqual(JSON.parse((await handler(put)).body as string).body, { nome: "ab" });',
        '  const v1 = { httpMethod: "GET", path: "/items/7", multiValueQueryStringParameters: { n: ["3"] }, queryStringParameters: { n: "3" },',
        '    requestContext: { authorizer: { claims: { [CLAIMS.subject]: "u", [CLAIMS.scopes[0]]: "s.read" } } } };',
        '  assert.deepEqual(JSON.parse((await handler(v1)).body as string).query, { n: 3 });',
        '  const single = toRequest({ httpMethod: "POST", queryStringParameters: { a: "1" }, body: "{}" });',
        '  assert.deepEqual([single.query, single.path, Buffer.from(single.body!).toString(), single.identity], [{ a: ["1"] }, "/", "{}", null]);',
        '  assert.equal(toRequest({ version: "2.0", requestContext: { http: { method: "GET" } } }).path, "/");',
        '  assert.deepEqual(toRequest({ httpMethod: "GET" }).query, {});',
        '  const proto = toRequest({ version: "2.0", rawQueryString: "__proto__=1", requestContext: { http: { method: "GET" } } });',
        '  assert.deepEqual(Object.entries(proto.query), [["__proto__", ["1"]]]);',
        '  assert.deepEqual(toProxy(response(204)), { statusCode: 204, headers: {}, isBase64Encoded: false, body: "" });',
        "  void out;",
    ],
    "rt_api_http": [
        "  const server = createServer(httpHandler(synthetic()));",
        "  await new Promise<void>((resolve) => server.listen(0, resolve));",
        "  const port = (server.address() as AddressInfo).port;",
        "  try {",
        '    let r = await fetch(`http://127.0.0.1:${port}/items/4?n=1&tag=a&tag=b`, { headers: { [HEADERS.subject]: "u", [HEADERS.scopes]: "s.read" } });',
        "    assert.equal(r.status, 200);", '    assert.deepEqual((await r.json()).query, { n: 1, tag: ["a", "b"] });',
        '    r = await fetch(`http://127.0.0.1:${port}/items/4`, { method: "PUT", body: \'{"nome": "x"}\', headers: { "content-type": "application/json", "x-multi": "a" } });',
        '    assert.deepEqual((await r.json()).body, { nome: "x" });',
        '    r = await fetch(`http://127.0.0.1:${port}/opt`, { method: "POST" });',
        "    assert.equal(r.status, 204);", '    assert.equal(await r.text(), "");',
        "  } finally {", "    server.close();", "  }",
        '  const raw = Object.assign(Readable.from([Buffer.from("{}")]), { headers: { "set-cookie": ["a", "b"] } });',
        "  const parsed = await readRequest(raw as never);",
        '  assert.deepEqual([parsed.method, parsed.path, parsed.headers["set-cookie"], Buffer.from(parsed.body!).toString()], ["GET", "/", "a, b", "{}"]);',
    ],
    "rt_api_framework": [
        '  const { default: fastify } = await import("fastify");',
        "  const app = includeApi(fastify(), synthetic());",
        "  try {",
        '    let r = await app.inject({ method: "GET", url: "/items/7?n=1&tag=a&tag=b", headers: { [HEADERS.subject]: "u", [HEADERS.scopes]: "s.read" } });',
        "    assert.equal(r.statusCode, 200);", '    assert.deepEqual(r.json().query, { n: 1, tag: ["a", "b"] });',
        '    r = await app.inject({ method: "PUT", url: "/items/7", payload: \'{"nome": "x"}\', headers: { "content-type": "application/json" } });',
        '    assert.deepEqual(r.json().body, { nome: "x" });',
        '    r = await app.inject({ method: "DELETE", url: "/items/7" });',
        "    assert.equal(r.statusCode, 405);", '    assert.equal(r.json().error.code, "METHOD_NOT_ALLOWED");',
        '    r = await app.inject({ method: "GET", url: "/nessuno" });',
        "    assert.equal(r.statusCode, 404);", '    assert.equal(r.json().error.code, "ROUTE_NOT_FOUND");',
        '    r = await app.inject({ method: "POST", url: "/opt" });', "    assert.equal(r.statusCode, 204);",
        "  } finally {", "    await app.close();", "  }",
        "  let captured: ((req: unknown, reply: unknown) => Promise<unknown>) | null = null;",
        "  const fake = { removeAllContentTypeParsers: () => undefined, addContentTypeParser: () => undefined,",
        "    route: (o: { handler: (req: unknown, reply: unknown) => Promise<unknown> }) => { captured = o.handler; } };",
        "  includeApi(fake, synthetic());",
        "  const sent: unknown[] = [];",
        "  const rep: Record<string, unknown> = { code: () => rep, headers: () => rep, send: (p: unknown) => sent.push(p) };",
        '  await captured!({ method: "POST", url: "/opt", headers: { a: undefined, b: ["1", "2"] }, body: new Uint8Array() }, rep);',
        '  assert.deepEqual(sent, [""]);',
    ],
    "rt_api_convert": [
        "  for (const f of [toUuid, toDatetime, text, uuidText, dateText, datetimeText]) {",
        "    assert.equal(f(null), null);", "    assert.equal(f(undefined), null);", "  }",
        '  assert.equal(decimalText(null, 2), null);', '  assert.equal(decimalText("1.5", 2), "1.50");', '  assert.equal(decimalText(3, 0), "3");',
        '  assert.equal(decimalText("-0.001", 2), "0.00");',
        '  assert.equal(decimalText("-007.129", 2), "-7.12");', '  assert.equal(decimalText(0.5, 1), "0.5");',
        '  assert.equal(toUuid("00000000-0000-4000-8000-00000000000A"), "00000000-0000-4000-8000-00000000000a");',
        '  assert.equal(uuidText("ABC"), "abc");', '  assert.equal(text(7), "7");',
        '  const utc = new Date(Date.UTC(2026, 1, 3, 4, 5, 6, 123));',
        '  assert.equal(toDatetime("2026-02-03T04:05:06.123456789Z")!.getTime(), utc.getTime());',
        '  assert.equal(toDatetime("2026-02-03T06:05:06.123+02:00")!.getTime(), utc.getTime());',
        '  assert.equal(toDatetime("2026-02-02T22:35:06.12-05:30")!.getTime(), utc.getTime() - 3);',
        '  assert.equal(toDatetime("2026-02-03T04:05:06Z")!.getTime(), utc.getTime() - 123);',
        '  assert.equal(datetimeText(utc), "2026-02-03T04:05:06.123Z");',
        '  assert.equal(datetimeText("2026-02-03T06:05:06.123+02:00"), "2026-02-03T04:05:06.123Z");',
        '  assert.equal(dateText(utc), "2026-02-03");', '  assert.equal(dateText("2026-02-03"), "2026-02-03");',
    ],
}


def _custom_body(ops: List[Operation]) -> List[str]:
    custom = [o for o in ops if o.kind == "custom"]
    o = ["  const empty = buildApi(new ApiData(), null, []);", "  assert.deepEqual(empty.routes, []);",
         '  assert.equal((await empty.handle(req("GET", "/qualsiasi"))).status, 404);']
    if custom:
        o += [f"  assert.throws(() => buildApi(new ApiData(), {{}} as never), /{custom[0].op_id}/);",
              "  assert.throws(() => buildApi(new ApiData(), null), TypeError);"]
        free = [x.context for x in ops if x.kind != "custom" and x.context not in {c.context for c in custom}]
        if free:
            o += [f"  const only = buildApi(new ApiData(), {{}} as never, [{json.dumps(free[0])}]);",
                  f"  assert.deepEqual([...new Set(only.routes.map((r) => r.spec.context))], [{json.dumps(free[0])}]);"]
        o += ["  const calls: string[] = [];",
              "  const full = buildApi(new ApiData(), new Proxy({}, { get: (_t, name) => (call: Call) => { calls.push(String(name)); return call.operation; } }) as never);",
              f"  assert.equal(full.routes.length, {len(ops)});"]
    else:
        o += [f"  assert.equal(buildApi(new ApiData()).routes.length, {len(ops)});"]
    return o


def _data_body(tables: Dict[str, Table]) -> List[str]:
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    o = []
    if sql:
        o += ["  await withDb(async (_em, ds) => {",
              "    await assert.rejects(new ApiData().read(null, async () => 1), /dataSource/);",
              "    const data = new ApiData({ sqlFor: () => ds });",
              "    assert.equal(await data.read(null, async (em) => em.connection === ds), true);",
              '    const { tenantOf } = await import("../../src/model/generated");',
              "    assert.equal(await data.read(String(TENANT_A), async (em) => tenantOf(em)), String(TENANT_A).toLowerCase());",
              "    assert.equal(await new ApiData({ dataSource: ds, levels: process.env.KYBES_TEST_DATABASE_URL ? undefined : "
              "{ read_committed: null, repeatable_read: null, serializable: null } }).write([], null, async () => 5), 5);",
              "  });"]
    if mongo:
        o += ["  await withMongo(async (_em, ds) => {",
              "    await assert.rejects(new ApiData().mongoRead(null, async () => 1), /mongoClient/);",
              "    const data = new ApiData({ mongoClient: ds.client, mongoDatabaseFor: () => ds.db.databaseName });",
              "    assert.equal(await data.mongoRead(null, async (ms) => ms.db.databaseName), ds.db.databaseName);",
              "    const plain = new ApiData({ mongoClient: ds.client, mongoDatabase: ds.db.databaseName });",
              "    assert.equal(await plain.mongoWrite(null, async (ms) => ms.db.databaseName), ds.db.databaseName);",
              "  });"]
    return o


def render(cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str) -> str:
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    runners = []
    if sql:
        runners.append('import { withDb } from "./_db";')
    if mongo:
        runners.append('import { withMongo } from "./_mongo_db";')
    bodies = dict(BODIES)
    bodies["rt_api_custom"] = _custom_body(ops) + _data_body(tables)
    head = strip_sql(HEAD, sql).replace("__RUNNERS__", "\n".join(runners))
    o = [header("typescript", "kit").rstrip("\n") + "\n" + head]
    for tc in cat.for_table(API_RT, "api"):
        title = json.dumps(tc.id + " · " + ", ".join(tc.reqs) + " · " + METHODS[tc.method] + ": " + tc.title)
        o += ["", f"test({title}, async () => {{",
              f"  // atteso: {tc.expected}"]
        o += strip_sql("\n".join(bodies[tc.kind]), sql).split("\n")
        o.append("});")
    return "\n".join(o) + "\n"
