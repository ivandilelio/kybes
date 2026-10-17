"""Test xUnit dei moduli comuni delle API C#, con operazioni sintetiche (indipendenti dagli schemi)."""
from __future__ import annotations

import json
from typing import Dict, List

from api_plan import Operation
from naming import header
from runtime_api_typescript import _strip_block
from schema import Table
from sqlonly import has_sql, strip_sql
from verification import API_RT, METHODS, Catalog

HEAD = r'''#nullable enable
using System;
using System.Collections.Generic;
using System.Data.Common;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Numerics;
using System.Text;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
// kybes:sql-begin
using Microsoft.EntityFrameworkCore;
// kybes:sql-end
// kybes:mongo-begin
using MongoDB.Driver;
// kybes:mongo-end
using Xunit;
using __MODEL__;
using __API__;
using __CTRL__;
using static __MODEL__.Tests.KybesApiSupport;

namespace __MODEL__.Tests;

/// <summary>Test di unità generati per i moduli comuni delle API. Specifica: docs/generated/verification/kybes-api-runtime.md.</summary>
public sealed class KybesApiRuntimeTests
{
    private static readonly Identity Self = new("kybes-test", "t1", new HashSet<string> { "s.read" }, new Dictionary<string, object?>());

    private static readonly List<Spec> Synth = new()
    {
        Spec.Of(Quotes("{'id': 'getItem', 'method': 'GET', 'path': '/items/{id}', 'context': 'uno', 'kind': 'custom', 'table': null, 'arg': null,"
            + " 'status': 200, 'secured': true, 'scopes': ['s.read'], 'body': null, 'bodyRequired': false, 'params': ["
            + "{'name': 'id', 'in': 'path', 'required': true, 'schema': {'type': 'integer'}},"
            + "{'name': 'tag', 'in': 'query', 'required': false, 'schema': {'type': 'array', 'items': {'type': 'string'}}},"
            + "{'name': 'n', 'in': 'query', 'required': true, 'schema': {'type': 'integer', 'minimum': 1}}]}")),
        Spec.Of(Quotes("{'id': 'special', 'method': 'GET', 'path': '/items/special', 'context': 'uno', 'kind': 'custom', 'table': null, 'arg': null,"
            + " 'status': 200, 'secured': false, 'scopes': [], 'params': [], 'body': null, 'bodyRequired': false}")),
        Spec.Of(Quotes("{'id': 'putItem', 'method': 'PUT', 'path': '/items/{id}', 'context': 'due', 'kind': 'custom', 'table': null, 'arg': null,"
            + " 'status': 200, 'secured': false, 'scopes': [], 'bodyRequired': true,"
            + " 'params': [{'name': 'id', 'in': 'path', 'required': true, 'schema': {'type': 'integer'}}],"
            + " 'body': {'type': 'object', 'required': ['nome'], 'properties': {'nome': {'type': 'string', 'maxLength': 3}},"
            + " 'additionalProperties': false}}")),
        Spec.Of(Quotes("{'id': 'postOpt', 'method': 'POST', 'path': '/opt', 'context': 'due', 'kind': 'custom', 'table': null, 'arg': null,"
            + " 'status': 204, 'secured': false, 'scopes': [], 'params': [], 'body': {'type': 'object'}, 'bodyRequired': false}")),
        Spec.Of(Quotes("{'id': 'boom', 'method': 'POST', 'path': '/boom', 'context': 'due', 'kind': 'custom', 'table': null, 'arg': null,"
            + " 'status': 200, 'secured': false, 'scopes': [], 'params': [], 'body': null, 'bodyRequired': false}")),
    };

    private static readonly Handler Echo = call => Task.FromResult<object?>(new Dictionary<string, object?>
    {
        ["op"] = call.Operation, ["path"] = call.Path, ["query"] = call.Query, ["body"] = call.Body,
    });

    private static string Quotes(string text) => text.Replace('\'', '"');

    private static ApiRouter Synthetic(string basePath = "", Handler? boom = null) => new(Synth, new Dictionary<string, Handler>
    {
        ["getItem"] = Echo,
        ["special"] = call => Task.FromResult<object?>(ApiResponse.Reply(202, new Dictionary<string, object?> { ["x"] = 1L },
            new Dictionary<string, string> { ["location"] = call.BasePath + "/items/special" })),
        ["putItem"] = Echo,
        ["postOpt"] = Echo,
        ["boom"] = boom ?? (call => throw new InvalidOperationException("dettaglio interno da non mostrare")),
    }, basePath);

    private static Dictionary<string, List<string>> Qs(params string[] kv)
    {
        var output = new Dictionary<string, List<string>>();
        for (var i = 0; i < kv.Length; i += 2)
        {
            if (!output.TryGetValue(kv[i], out var values)) output[kv[i]] = values = new List<string>();
            values.Add(kv[i + 1]);
        }
        return output;
    }

    private static ApiRequest Req(string method, string path, Dictionary<string, List<string>>? query = null, object? body = null,
        Identity? who = null, Dictionary<string, string>? headers = null, bool anonymous = false)
    {
        var h = new Dictionary<string, string> { ["content-type"] = "application/json" };
        foreach (var kv in headers ?? new Dictionary<string, string>()) h[kv.Key] = kv.Value;
        var raw = body is string s ? Encoding.UTF8.GetBytes(s) : (byte[]?)body;
        return new ApiRequest(method, path, query ?? new Dictionary<string, List<string>>(), h, raw, anonymous ? null : who ?? Self);
    }

    private static Dictionary<string, object?> BodyOf(ApiResponse r) => (Dictionary<string, object?>)Json.Parse(r.Text())!;
    private static Dictionary<string, object?> ErrorOf(ApiResponse r) => (Dictionary<string, object?>)BodyOf(r)["error"]!;
    private static object? FieldsOf(ApiResponse r) => ErrorOf(r).GetValueOrDefault("fields");

    private static Dictionary<string, string> Check(string schema, object? value)
    {
        var errors = new Dictionary<string, string>();
        JsonSchema.Validate((IReadOnlyDictionary<string, object?>)J(schema)!, value, "campo", errors);
        return errors;
    }

    private static void Same(object? expected, object? actual, string? message = null) =>
        Assert.True(Canon(expected) == Canon(actual), (message ?? "") + ": atteso " + Canon(expected) + ", ottenuto " + Canon(actual));
'''

BODIES: Dict[str, str] = {
    "rt_api_validate": r'''
        var cases = new (string Schema, object? Value, string? Rule)[]
        {
            ("{'type': 'string'}", "x", null), ("{'type': 'string'}", 1L, "tipo atteso: string"), ("{'type': 'integer'}", 2.0, null),
            ("{'type': 'integer'}", 2.5, "tipo atteso: integer"), ("{'type': 'number'}", 3L, null), ("{'type': 'boolean'}", 1L, "tipo atteso: boolean"),
            ("{'type': 'boolean'}", true, null), ("{'type': 'integer'}", BigInteger.Parse("99999999999999999999"), null),
            ("{'type': 'string'}", null, "nullo non ammesso"), ("{'type': 'string', 'nullable': true}", null, null), ("{}", null, null),
            ("{'enum': ['a', 'b']}", "c", "valore non ammesso"), ("{'enum': ['a', 'b']}", "a", null), ("{'enum': [{'a': 1}]}", J("{'a': 1}"), null),
            ("{'enum': [1, 2]}", 2.0, null), ("{'enum': [1, 2]}", "1", "valore non ammesso"),
            ("{'type': 'string', 'minLength': 2}", "a", "lunghezza minima 2"), ("{'type': 'string', 'maxLength': 2}", "àbc", "lunghezza massima 2"),
            ("{'type': 'string', 'maxLength': 2}", "àb", null), ("{'type': 'string', 'pattern': '^[0-9]+$'}", "12a", "formato non valido"),
            ("{'type': 'string', 'pattern': '^[0-9]+$'}", "12", null),
            ("{'type': 'string', 'format': 'uuid'}", "x", "formato uuid"), ("{'type': 'string', 'format': 'date'}", "2026-02-30", "formato date"),
            ("{'type': 'string', 'format': 'date-time'}", "2026-01-01T10:00:00Z", null),
            ("{'type': 'integer', 'minimum': 1}", 0L, "valore minimo 1"), ("{'type': 'number', 'maximum': 1.5}", 2L, "valore massimo 1.5"),
            ("{'type': 'number', 'minimum': 1, 'maximum': 2}", 1.5, null), ("{'type': 'integer', 'minimum': 1}", BigInteger.Parse("99999999999999999999"), null),
            ("{'type': 'array', 'minItems': 1}", new List<object?>(), "almeno 1 elementi"),
            ("{'type': 'array', 'maxItems': 1}", new List<object?> { 1L, 2L }, "al massimo 1 elementi"),
            ("{'type': 'array'}", new List<object?> { 1L }, null), ("{'type': 'object'}", new List<object?>(), "tipo atteso: object"),
            ("{'type': 'array'}", new Dictionary<string, object?>(), "tipo atteso: array"),
            ("{'type': 'string'}", Guid.NewGuid(), "tipo atteso: string"), ("{'type': 'number'}", "x", "tipo atteso: number"),
            ("{'type': 'string', 'minLength': 2}", "ab", null), ("{'type': 'array', 'minItems': 1}", new List<object?> { 1L }, null),
            ("{'type': 'array', 'maxItems': 1}", new List<object?> { 1L }, null), ("{}", Guid.NewGuid(), null),
        };
        foreach (var c in cases)
        {
            var expected = c.Rule is null ? new Dictionary<string, object?>() : new Dictionary<string, object?> { ["campo"] = c.Rule };
            Same(expected, Check(c.Schema, c.Value), c.Schema);
        }
        var schema = (IReadOnlyDictionary<string, object?>)J("{'type': 'object', 'required': ['a', 'b'], 'properties': {'a': {'type': 'array', 'items': {'type': 'integer'}},"
            + " 'o': {'type': 'object', 'properties': {'x': {'type': 'string'}}, 'additionalProperties': {'type': 'integer'}}},"
            + " 'additionalProperties': false}")!;
        var errors = new Dictionary<string, string>();
        JsonSchema.Validate(schema, J("{'a': [1, 'x'], 'o': {'x': 1, 'y': 'z', 'w': 2}, 'k': 1}"), "", errors);
        Same(J("{'b': 'obbligatorio', 'a[1]': 'tipo atteso: integer', 'o.x': 'tipo atteso: string', 'o.y': 'tipo atteso: integer', 'k': 'non ammesso'}"), errors);
        errors = new Dictionary<string, string> { ["body"] = "già presente" };
        JsonSchema.Validate((IReadOnlyDictionary<string, object?>)J("{'type': 'string'}")!, 1L, "", errors);
        Same(J("{'body': 'già presente'}"), errors);
        errors = new Dictionary<string, string>();
        JsonSchema.Validate((IReadOnlyDictionary<string, object?>)J("{'type': 'object', 'properties': {}}")!, J("{'libero': 1}"), "", errors);
        JsonSchema.Validate((IReadOnlyDictionary<string, object?>)J("{'type': 'object'}")!, J("{'libero': 1}"), "", errors);
        var taken = new Dictionary<string, string> { ["p.a"] = "x", ["p.x"] = "y" };
        JsonSchema.Validate((IReadOnlyDictionary<string, object?>)J("{'type': 'object', 'required': ['a'], 'properties': {'a': {'type': 'string'}}, 'additionalProperties': false}")!,
            J("{'x': 1}"), "p", taken);
        Same(J("{'p.a': 'x', 'p.x': 'y'}"), taken);
        Assert.Empty(errors);
        Assert.Equal("2", JsonSchema.Num(2.0));
        Assert.Equal("1.5", JsonSchema.Num(1.5));
        Assert.Equal("0", JsonSchema.Num(0L));
        Assert.Equal("unknown", JsonSchema.TypeOf(Guid.NewGuid()));
        Assert.Equal(0, JsonSchema.Compare(2L, 2.0));
        Assert.True(JsonSchema.Compare(BigInteger.Parse("99999999999999999999"), 1L) > 0);
        foreach (var good in new[] { "2026-01-01T00:00:00.123456789+02:00", "2026-12-31T23:59:59-05:30" }) Assert.True(JsonSchema.CheckFormat("date-time", good), good);
        foreach (var bad in new[] { "2026-01-01 10:00:00Z", "2026-02-30T10:00:00Z", "2026-01-01T24:00:00Z", "2026-01-01T10:60:00Z",
                     "2026-01-01T10:00:60Z", "2026-01-01T10:00:00+24:00", "2026-01-01T10:00:00+01:60" })
            Assert.False(JsonSchema.CheckFormat("date-time", bad), bad);
        Assert.True(JsonSchema.CheckFormat("uuid", "00000000-0000-4000-8000-00000000000A"));
        Assert.False(JsonSchema.CheckFormat("uuid", "00000000-0000-4000-8000-00000000000A\n"));
        Assert.False(JsonSchema.CheckFormat("date", "2024-01-02\n"));
        Assert.False(JsonSchema.CheckFormat("date-time", "2024-01-02T03:04:05Z\n"));
        Same(J("{'campo': 'formato non valido'}"), Check("{'type': 'string', 'pattern': '^[0-9]+$'}", "12\n"));
        Assert.Matches(JsonSchema.JsPattern("^(a|b$)$"), "b");
        Assert.DoesNotMatch(JsonSchema.JsPattern("^(a|b$)$"), "b\n");
        Assert.Matches(JsonSchema.JsPattern("^a\\$$"), "a$");
        Assert.Same(JsonSchema.JsPattern("^x$"), JsonSchema.JsPattern("^x$"));
        Assert.True(JsonSchema.CheckFormat("date", "2024-02-29"));
        Assert.False(JsonSchema.CheckFormat("date", "2026-1-1"));
        await Task.CompletedTask;
''',
    "rt_api_coerce": r'''
        var integer = (IReadOnlyDictionary<string, object?>)J("{'type': 'integer'}")!;
        Assert.Equal(new Coerced(-12L, null), JsonSchema.Coerce(integer, new[] { "-12" }));
        Assert.Equal(BigInteger.Parse("99999999999999999999"), JsonSchema.Coerce(integer, new[] { "99999999999999999999" }).Value);
        Assert.Equal(new Coerced(null, "tipo atteso: integer"), JsonSchema.Coerce(integer, new[] { "1.5" }));
        var number = (IReadOnlyDictionary<string, object?>)J("{'type': 'number'}")!;
        Assert.Equal(new Coerced(150.0, null), JsonSchema.Coerce(number, new[] { "1.5e2" }));
        Assert.Equal(new Coerced(null, "tipo atteso: number"), JsonSchema.Coerce(number, new[] { "abc" }));
        Assert.Equal(new Coerced(null, "tipo atteso: number"), JsonSchema.Coerce(number, new[] { "1e400" }));
        Assert.Equal(new Coerced(null, "tipo atteso: integer"), JsonSchema.Coerce(integer, new[] { "1\n" }));
        Assert.Equal(new Coerced(null, "tipo atteso: number"), JsonSchema.Coerce(number, new[] { "1\n" }));
        var boolean = (IReadOnlyDictionary<string, object?>)J("{'type': 'boolean'}")!;
        Assert.Equal(new Coerced(true, null), JsonSchema.Coerce(boolean, new[] { "true" }));
        Assert.Equal(new Coerced(false, null), JsonSchema.Coerce(boolean, new[] { "false" }));
        Assert.Equal(new Coerced(null, "tipo atteso: boolean"), JsonSchema.Coerce(boolean, new[] { "1" }));
        var text = (IReadOnlyDictionary<string, object?>)J("{'type': 'string'}")!;
        Assert.Equal(new Coerced("x", null), JsonSchema.Coerce(text, new[] { "x" }));
        Assert.Equal(new Coerced(null, "un solo valore"), JsonSchema.Coerce(text, new[] { "x", "y" }));
        var ints = (IReadOnlyDictionary<string, object?>)J("{'type': 'array', 'items': {'type': 'integer'}}")!;
        Same(J("[1, 2]"), JsonSchema.Coerce(ints, new[] { "1", "2" }).Value);
        Assert.Equal(new Coerced(null, "tipo atteso: integer"), JsonSchema.Coerce(ints, new[] { "1", "x" }));
        Same(J("[]"), JsonSchema.Coerce((IReadOnlyDictionary<string, object?>)J("{'type': 'array'}")!, Array.Empty<string>()).Value);
        Same(J("['a']"), JsonSchema.Coerce((IReadOnlyDictionary<string, object?>)J("{'type': 'array'}")!, new[] { "a" }).Value);
        Same(J("{'a': ['1', '3'], 'b': [''], 'c': ['x y', '%zz']}"), ApiRequest.ParseQuery("?a=1&&b&a=3&c=x+y&c=%zz"));
        Assert.Empty(ApiRequest.ParseQuery(null));
        Assert.Equal("a+b c", ApiRequest.Decode("a+b%20c", false));
        await Task.CompletedTask;
''',
    "rt_api_route": r'''
        var api = Synthetic();
        var r = await api.HandleAsync(Req("GET", "/items/special"));
        Assert.Equal(202, r.Status);
        Assert.Equal("application/json", r.Headers["content-type"]);
        Assert.Equal("/items/special", r.Headers["location"]);
        Same(J("{'x': 1}"), BodyOf(r));
        r = await api.HandleAsync(Req("GET", "/items/7", Qs("n", "2", "tag", "a", "tag", "b")));
        Assert.Equal(200, r.Status);
        Same(J("{'op': 'getItem', 'path': {'id': 7}, 'query': {'n': 2, 'tag': ['a', 'b']}, 'body': null}"), BodyOf(r));
        r = await api.HandleAsync(Req("GET", "/items/%37", Qs("n", "1")));
        Same(J("{'id': 7}"), BodyOf(r)["path"]);
        r = await api.HandleAsync(Req("GET", "/items/x", Qs("n", "0", "altro", "1")));
        Assert.Equal(400, r.Status);
        Same(J("{'altro': 'parametro sconosciuto', 'id': 'tipo atteso: integer', 'n': 'valore minimo 1'}"), FieldsOf(r));
        r = await api.HandleAsync(Req("GET", "/items/7"));
        Same(J("{'n': 'obbligatorio'}"), FieldsOf(r));
        r = await api.HandleAsync(Req("GET", "/items/x", Qs("n", "x", "tag", "a"), anonymous: true));
        Assert.Equal(401, r.Status);
        Assert.Equal("IDENTITY_REQUIRED", ErrorOf(r)["code"]);
        r = await api.HandleAsync(Req("GET", "/nessuno"));
        Assert.Equal(404, r.Status);
        Assert.Equal("ROUTE_NOT_FOUND", ErrorOf(r)["code"]);
        Assert.Equal(404, (await api.HandleAsync(Req("GET", "/items"))).Status);
        r = await api.HandleAsync(Req("DELETE", "/items/7"));
        Assert.Equal(405, r.Status);
        Assert.Equal("GET, PUT", r.Headers["allow"]);
        Assert.Equal("METHOD_NOT_ALLOWED", ErrorOf(r)["code"]);
        r = await api.HandleAsync(Req("get", "/items/7", Qs("n", "1"), who: new Identity("u", null, new HashSet<string>(), new Dictionary<string, object?>())));
        Assert.Equal(403, r.Status);
        Assert.Equal("SCOPE_REQUIRED", ErrorOf(r)["code"]);
        var based = Synthetic("/v1/", call => Task.FromResult<object?>(null));
        Assert.Equal("/v1", based.BasePath);
        Assert.Equal(202, (await based.HandleAsync(Req("GET", "/v1/items/special"))).Status);
        Assert.Equal("/v1/items/special", (await based.HandleAsync(Req("GET", "/v1/items/special"))).Headers["location"]);
        Assert.Equal(404, (await based.HandleAsync(Req("GET", "/v1"))).Status);
        Assert.Equal(202, (await based.HandleAsync(Req("GET", "/items/special"))).Status);
        Assert.Equal(404, (await based.HandleAsync(Req("GET", "/v1x/items/special"))).Status);
        var route = new Route(Synth[0], Echo);
        Assert.Same(Echo, route.Handler);
        Assert.Null(route.Match(new[] { "items" }));
        Assert.Null(route.Match(new[] { "altro", "1" }));
        Same(J("{'id': '1'}"), route.Match(new[] { "items", "1" }));
        var sorted = new ApiRouter(new[] { Synth[1], Synth[0], Synth[4], Synth[3] }, new Dictionary<string, Handler> { ["getItem"] = Echo });
        Assert.Equal(new[] { "boom", "postOpt", "special", "getItem" }, sorted.Routes.Select(x => x.Spec.Id).ToArray());
''',
    "rt_api_body": r'''
        var api = Synthetic();
        var r = await api.HandleAsync(Req("PUT", "/items/1", body: "{\"nome\": \"abc\"}", headers: new() { ["content-type"] = "text/plain" }));
        Assert.Equal(415, r.Status);
        Assert.Equal("JSON_REQUIRED", ErrorOf(r)["code"]);
        r = await api.HandleAsync(Req("PUT", "/items/1", body: "{\"nome\": \"abc\"}", headers: new() { ["content-type"] = "Application/JSON; charset=utf-8" }));
        Assert.Equal(200, r.Status);
        Same(J("{'nome': 'abc'}"), BodyOf(r)["body"]);
        foreach (var raw in new object[] { "{", "{\"nome\": NaN}", new byte[] { 0xff }, "{\"nome\": 1e400}", new byte[] { 0xef, 0xbb, 0xbf, (byte)'{', (byte)'}' } })
        {
            r = await api.HandleAsync(Req("PUT", "/items/1", body: raw));
            Assert.Equal(400, r.Status);
            Same(J("{'body': 'JSON non valido'}"), FieldsOf(r));
        }
        r = await api.HandleAsync(Req("PUT", "/items/1", body: "{\"nome\": \"abcd\", \"x\": 1}"));
        Same(J("{'nome': 'lunghezza massima 3', 'x': 'non ammesso'}"), FieldsOf(r));
        r = await api.HandleAsync(Req("PUT", "/items/1", body: "[]"));
        Same(J("{'body': 'tipo atteso: object'}"), FieldsOf(r));
        r = await api.HandleAsync(Req("PUT", "/items/1", Qs("body", "1")));
        Same(J("{'body': 'parametro sconosciuto'}"), FieldsOf(r));
        r = await api.HandleAsync(Req("PUT", "/items/1", Qs("body", "1"), "{"));
        Same(J("{'body': 'parametro sconosciuto'}"), FieldsOf(r));
        r = await api.HandleAsync(Req("GET", "/items/special", Qs("body", "1"), "{}"));
        Same(J("{'body': 'parametro sconosciuto'}"), FieldsOf(r));
        r = await api.HandleAsync(Req("PUT", "/items/1"));
        Assert.Equal(400, r.Status);
        Same(J("{'body': 'obbligatorio'}"), FieldsOf(r));
        r = await api.HandleAsync(Req("POST", "/opt"));
        Assert.Equal(204, r.Status);
        Assert.False(r.HasBody);
        Assert.Equal("", r.Text());
        Assert.Equal(204, (await api.HandleAsync(Req("POST", "/opt", body: "{}"))).Status);
        Assert.Equal(204, (await api.HandleAsync(Req("POST", "/opt", body: Array.Empty<byte>()))).Status);
        r = await api.HandleAsync(Req("GET", "/items/special", body: "{}"));
        Assert.Equal(400, r.Status);
        Same(J("{'body': 'corpo non ammesso'}"), FieldsOf(r));
        r = await api.HandleAsync(new ApiRequest("PUT", "/items/1", new Dictionary<string, List<string>>(), new Dictionary<string, string>(), Encoding.UTF8.GetBytes("{}"), null));
        Assert.Equal(415, r.Status);
        // JSON: lettura e scrittura
        var parsed = (Dictionary<string, object?>)Json.Parse(" {\"a\" : [1, -2.5, 1E+3, true, false, null, {}, [ ]], \"b\": \"x\\\"\\\\\\/\\b\\f\\n\\r\\t\\u00e8\"} ")!;
        Same(J("[1, -2.5, 1000, true, false, null, {}, []]"), parsed["a"]);
        Assert.Equal("x\"\\/\b\f\n\r\tè", parsed["b"]);
        Assert.Equal(BigInteger.Parse("123456789012345678901234567890"), Json.Parse("123456789012345678901234567890"));
        Assert.Equal(0L, Json.Parse("-0"));
        Assert.Equal(1.5e-3, Json.Parse("1.5e-3"));
        foreach (var bad in new[] { "", "{", "[1,]", "{\"a\" 1}", "{\"a\": 1,}", "{1: 2}", "[1 2]", "\"a", "\"\\x\"", "\"\\u12\"",
                     "\"\\u12zz\"", "\"a\nb\"", "01", "-", "1.", "1e", "1e400", "nul", "[1] x", "tru" })
            Assert.Throws<JsonError>(() => Json.Parse(bad));
        Assert.Throws<JsonError>(() => Json.Parse(new string('[', 600) + new string(']', 600)));
        var output = new Dictionary<string, object?>
        {
            ["s"] = "a\"\\\n\r\t\u0001è", ["d"] = 1.5, ["dec"] = 1.50m, ["n"] = 7, ["b"] = true, ["l"] = new List<object?> { 1L, "x" },
            ["u"] = Guid.Parse("00000000-0000-4000-8000-000000000001"), ["z"] = null,
        };
        Assert.Equal("{\"s\":\"a\\\"\\\\\\n\\r\\t\\u0001è\",\"d\":1.5,\"dec\":1.50,\"n\":7,\"b\":true,\"l\":[1,\"x\"],"
            + "\"u\":\"00000000-0000-4000-8000-000000000001\",\"z\":null}", Json.Write(output));
        Assert.Throws<JsonError>(() => Json.Write(double.NaN));
        Assert.Throws<JsonError>(() => Json.Write(double.PositiveInfinity));
''',
    "rt_api_errors": r'''
        var logged = new List<string>();
        var previous = ApiRouter.Log;
        ApiRouter.Log = (cid, e) => logged.Add(cid);
        try
        {
            var api = Synthetic();
            var r = await api.HandleAsync(Req("POST", "/boom", headers: new() { ["x-correlation-id"] = "abc-1" }));
            Assert.Equal(500, r.Status);
            Same(J("{'error': {'code': 'UNEXPECTED', 'message': 'Errore interno', 'correlationId': 'abc-1'}}"), BodyOf(r));
            Assert.Equal("abc-1", r.Headers["x-correlation-id"]);
            Assert.DoesNotContain("dettaglio", r.Text());
            Assert.Equal(new[] { "abc-1" }, logged);
            r = await api.HandleAsync(Req("POST", "/boom", headers: new() { ["x-correlation-id"] = "non valido!" }));
            Assert.NotEqual("non valido!", r.Headers["x-correlation-id"]);
        }
        finally
        {
            ApiRouter.Log = previous;
        }
        ApiRouter.Log("cid", new InvalidOperationException("prova del log predefinito"));
        Same(J("{'error': {'code': 'X', 'message': 'Richiesta non valida', 'correlationId': 'c', 'fields': {'a': 'b'}}}"),
            Errors.ErrorBody("VALIDATION", "X", "c", new Dictionary<string, string> { ["a"] = "b" }));
        Same(J("{'error': {'code': 'X', 'message': 'Richiesta non valida', 'correlationId': 'c'}}"),
            Errors.ErrorBody("VALIDATION", "X", "c", new Dictionary<string, string>()));
        var same = new ApiError("CONFLICT", "MIO");
        Assert.Same(same, ApiRouter.MapError(same));
        Assert.Empty(new ApiError("NOT_FOUND", "X").Fields);
        var e = ApiRouter.MapError(new ModelValidationException("T", new Dictionary<string, string> { ["limit"] = "tra 1 e 100" }));
        Assert.Equal(("VALIDATION", "INVALID_PAGE", "tra 1 e 100"), (e.Kind, e.Code, e.Fields["limit"]));
        e = ApiRouter.MapError(new ModelValidationException("T", new Dictionary<string, string> { ["Righe"] = "record collegati" }));
        Assert.Equal(("CONFLICT", "RELATED_RECORDS"), (e.Kind, e.Code));
        e = ApiRouter.MapError(new ModelValidationException("T", new Dictionary<string, string> { ["Righe"] = "record collegati", ["Nome"] = "obbligatorio" }));
        Assert.Equal("MODEL_RULE", e.Code);
        e = ApiRouter.MapError(new ModelValidationException("T", new Dictionary<string, string> { ["Nome"] = "obbligatorio" }));
        Assert.Equal(("UNPROCESSABLE", "MODEL_RULE"), (e.Kind, e.Code));
        Assert.Equal("UNPROCESSABLE", ApiRouter.MapError(new ModelValidationException("T", new Dictionary<string, string>())).Kind);
        Assert.Equal("TENANT_REQUIRED", ApiRouter.MapError(new TenantException("x")).Code);
        Assert.Equal("RECORD_NOT_FOUND", ApiRouter.MapError(new KeyNotFoundException("x")).Code);
        Assert.Equal("UNEXPECTED", ApiRouter.MapError(new InvalidOperationException("x", new Exception("y"))).Code);
        // kybes:mongo-begin
        Assert.Equal("DUPLICATE", ApiRouter.MapError(new Exception("x", new MongoException("E11000 duplicate key error"))).Code);
        Assert.Equal("UNEXPECTED", ApiRouter.MapError(new MongoException("altro")).Code);
        // kybes:mongo-end
        // kybes:sql-begin
        Assert.Equal("CONSTRAINT", ApiRouter.MapError(new DbUpdateException("x", new FakeDbException("23505"))).Code);
        Assert.Equal("UNEXPECTED", ApiRouter.MapError(new DbUpdateException("x", new FakeDbException("42P01"))).Code);
        Assert.Equal("UNEXPECTED", ApiRouter.MapError(new DbUpdateException("x", new FakeDbException(null))).Code);
        Assert.Equal("RETRY_LATER", ApiRouter.MapError(new DbUpdateException("x", new FakeDbException("40001"))).Code);
        // kybes:sql-end
        var resp = await Synthetic("", call => throw new ModelValidationException("T", new Dictionary<string, string> { ["Nome"] = "obbligatorio" }))
            .HandleAsync(Req("POST", "/boom"));
        Assert.Equal(422, resp.Status);
        Same(J("{'Nome': 'obbligatorio'}"), FieldsOf(resp));
        resp = await Synthetic("", call => throw new TenantException("x")).HandleAsync(Req("POST", "/boom"));
        Assert.Equal(403, resp.Status);
        Assert.Null(FieldsOf(resp));
        var custom = ApiResponse.Reply(201, J("{'a': 1}"), new Dictionary<string, string> { ["location"] = "/x" });
        Assert.Equal((201, "/x", "{\"a\":1}"), (custom.Status, custom.Headers["location"], custom.Text()));
        Assert.Equal("application/json", ApiResponse.Reply(200, null).Headers["content-type"]);
        Assert.Equal("null", ApiResponse.Reply(200, null).Text());
''',
    "rt_api_identity": r'''
        Assert.Empty(IdentityReader.ScopesOf(null));
        Assert.Equal(new[] { "a", "1" }, IdentityReader.ScopesOf(new List<object?> { "a", 1L }));
        Assert.Equal(new[] { "a", "b" }, IdentityReader.ScopesOf("[a b]"));
        Assert.Equal(new[] { "[a", "b" }, IdentityReader.ScopesOf("[a b"));
        Assert.Equal(new[] { "a", "b", "c" }, IdentityReader.ScopesOf("a,b c"));
        Assert.Empty(IdentityReader.ScopesOf(""));
        var claims = new Dictionary<string, object?> { [IdentityReader.ClaimSubject] = "u1", [IdentityReader.ClaimTenant] = "t1", [IdentityReader.ClaimScopes[0]] = "a b" };
        var i = IdentityReader.FromClaims(claims);
        Assert.Equal(("u1", "t1"), (i.Subject, i.Tenant));
        Assert.True(i.Scopes.SetEquals(new[] { "a", "b" }));
        Same(claims, i.Claims);
        i = IdentityReader.FromClaims(new Dictionary<string, object?> { [IdentityReader.ClaimSubject] = "", [IdentityReader.ClaimTenant] = null });
        Assert.Null(i.Subject);
        Assert.Null(i.Tenant);
        Assert.Empty(i.Scopes);
        var sub = IdentityReader.ClaimSubject;
        IReadOnlyDictionary<string, object?> Ev(string json) => (IReadOnlyDictionary<string, object?>)J(json.Replace("SUB", sub))!;
        Assert.Null(IdentityReader.FromLambda(Ev("{}")));
        Assert.Null(IdentityReader.FromLambda(Ev("{'requestContext': 'x'}")));
        Assert.Null(IdentityReader.FromLambda(Ev("{'requestContext': {'authorizer': 'x'}}")));
        Assert.Equal("a", IdentityReader.FromLambda(Ev("{'requestContext': {'authorizer': {'jwt': {'claims': {'SUB': 'a'}}}}}"))!.Subject);
        Assert.Equal("b", IdentityReader.FromLambda(Ev("{'requestContext': {'authorizer': {'jwt': {}, 'lambda': {'SUB': 'b'}}}}"))!.Subject);
        Assert.Equal("c", IdentityReader.FromLambda(Ev("{'requestContext': {'authorizer': {'claims': {'SUB': 'c'}}}}"))!.Subject);
        Assert.Equal("d", IdentityReader.FromLambda(Ev("{'requestContext': {'authorizer': {'SUB': 'd'}}}"))!.Subject);
        var withText = new Dictionary<string, object?> { ["requestContext"] = new Dictionary<string, object?> { ["authorizer"] = new Dictionary<string, object?>
            { ["claims"] = Json.Write(new Dictionary<string, object?> { [sub] = "e" }) } } };
        Assert.Equal("e", IdentityReader.FromLambda(withText)!.Subject);
        Assert.Null(IdentityReader.FromHeaders(new Dictionary<string, string>()));
        i = IdentityReader.FromHeaders(new Dictionary<string, string>
            { [IdentityReader.HeaderSubject] = "u", [IdentityReader.HeaderTenant] = "t", [IdentityReader.HeaderScopes] = "x y" })!;
        Assert.Equal(("u", "t"), (i.Subject, i.Tenant));
        Assert.True(i.Scopes.SetEquals(new[] { "x", "y" }));
        Assert.Null(IdentityReader.FromHeaders(new Dictionary<string, string> { [IdentityReader.HeaderSubject] = "u" })!.Tenant);
        var anon = Identity.Anonymous();
        Assert.Empty(anon.Scopes);
        Assert.Empty(anon.Claims);
        await Task.CompletedTask;
''',
    "rt_api_lambda": r'''
        var api = Synthetic();
        var sub = IdentityReader.ClaimSubject;
        var scp = IdentityReader.ClaimScopes[0];
        Dictionary<string, object?> Ev(string json) => (Dictionary<string, object?>)J(json.Replace("SUB", sub).Replace("SCP", scp))!;
        var v2 = Ev("{'version': '2.0', 'rawPath': '/items/7', 'rawQueryString': 'n=2&tag=a&tag=b', 'headers': {'Content-Type': 'application/json'},"
            + " 'requestContext': {'http': {'method': 'GET'}, 'authorizer': {'jwt': {'claims': {'SUB': 'u', 'SCP': 's.read'}}}}}");
        var stream = await LambdaAdapter.HandleAsync(api, new MemoryStream(Encoding.UTF8.GetBytes(Json.Write(v2))));
        var output = (Dictionary<string, object?>)Json.Parse(await new StreamReader(stream).ReadToEndAsync())!;
        Assert.Equal(200L, output["statusCode"]);
        Assert.Equal(false, output["isBase64Encoded"]);
        Same(J("{'n': 2, 'tag': ['a', 'b']}"), ((Dictionary<string, object?>)Json.Parse((string)output["body"]!)!)["query"]);
        var put = Ev("{'httpMethod': 'PUT', 'path': '/items/1', 'headers': {'content-type': 'application/json'}, 'isBase64Encoded': true, 'requestContext': {}}");
        put["body"] = Convert.ToBase64String(Encoding.UTF8.GetBytes("{\"nome\": \"ab\"}"));
        var resp = await api.HandleAsync(LambdaAdapter.ToRequest(put));
        Same(J("{'nome': 'ab'}"), BodyOf(resp)["body"]);
        var v1 = Ev("{'httpMethod': 'GET', 'path': '/items/7', 'multiValueQueryStringParameters': {'n': ['3']}, 'queryStringParameters': {'n': '3'},"
            + " 'requestContext': {'authorizer': {'claims': {'SUB': 'u', 'SCP': 's.read'}}}}");
        Same(J("{'n': 3}"), BodyOf(await api.HandleAsync(LambdaAdapter.ToRequest(v1)))["query"]);
        var single = LambdaAdapter.ToRequest(Ev("{'httpMethod': 'POST', 'queryStringParameters': {'a': 1}, 'body': '{}'}"));
        Same(J("{'a': ['1']}"), single.Query);
        Assert.Equal(("/", "{}"), (single.Path, Encoding.UTF8.GetString(single.Body!)));
        Assert.Null(single.Identity);
        Assert.Equal("/", LambdaAdapter.ToRequest(Ev("{'version': '2.0', 'rawPath': '', 'requestContext': {'http': {'method': 'GET'}}}")).Path);
        Assert.Empty(LambdaAdapter.ToRequest(Ev("{'httpMethod': 'GET'}")).Query);
        Same(J("{'statusCode': 204, 'headers': {}, 'isBase64Encoded': false, 'body': ''}"), LambdaAdapter.ToProxy(ApiResponse.Reply(204)));
''',
    "rt_api_http": r'''
        var api = Synthetic();
        var context = new DefaultHttpContext();
        context.Request.Method = "GET";
        context.Request.Path = "/items/4";
        context.Request.QueryString = new QueryString("?n=1&tag=a&tag=b");
        context.Request.Headers[IdentityReader.HeaderSubject] = "u";
        context.Request.Headers[IdentityReader.HeaderScopes] = "s.read";
        context.Request.Headers["x-multi"] = new Microsoft.Extensions.Primitives.StringValues(new[] { "a", "b" });
        var req = await AspNetAdapter.ToRequestAsync(context.Request);
        Assert.Equal("a, b", req.Headers["x-multi"]);
        Assert.Null(req.Body);
        context.Response.Body = new MemoryStream();
        await AspNetAdapter.WriteAsync(context.Response, await api.HandleAsync(req));
        Assert.Equal(200, context.Response.StatusCode);
        context.Response.Body.Position = 0;
        Same(J("{'n': 1, 'tag': ['a', 'b']}"), ((Dictionary<string, object?>)Json.Parse(await new StreamReader(context.Response.Body).ReadToEndAsync())!)["query"]);
        context = new DefaultHttpContext();
        context.Request.Method = "PUT";
        context.Request.Path = "/items/4";
        context.Request.ContentType = "application/json";
        context.Request.Body = new MemoryStream(Encoding.UTF8.GetBytes("{\"nome\": \"x\"}"));
        req = await AspNetAdapter.ToRequestAsync(context.Request);
        Same(J("{'nome': 'x'}"), Json.Parse(Encoding.UTF8.GetString(req.Body!)));
        context.Response.Body = new MemoryStream();
        await AspNetAdapter.WriteAsync(context.Response, ApiResponse.Reply(204));
        Assert.Equal(204, context.Response.StatusCode);
        Assert.Equal(0, context.Response.Body.Length);
''',
    "rt_api_framework": r'''
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseUrls("http://127.0.0.1:0");
        builder.Logging.ClearProviders();
        var app = builder.Build();
        app.MapKybesApi(Synthetic("/v1"));
        await app.StartAsync();
        try
        {
            using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };
            var request = new HttpRequestMessage(HttpMethod.Get, "/v1/items/7?n=1&tag=a&tag=b");
            request.Headers.Add(IdentityReader.HeaderSubject, "u");
            request.Headers.Add(IdentityReader.HeaderScopes, "s.read");
            var r = await client.SendAsync(request);
            Assert.Equal(200, (int)r.StatusCode);
            Same(J("{'n': 1, 'tag': ['a', 'b']}"), ((Dictionary<string, object?>)Json.Parse(await r.Content.ReadAsStringAsync())!)["query"]);
            r = await client.PutAsync("/v1/items/7", new StringContent("{\"nome\": \"x\"}", Encoding.UTF8, "application/json"));
            Same(J("{'nome': 'x'}"), ((Dictionary<string, object?>)Json.Parse(await r.Content.ReadAsStringAsync())!)["body"]);
            r = await client.DeleteAsync("/v1/items/7");
            Assert.Equal(405, (int)r.StatusCode);
            r = await client.PostAsync("/v1/opt", null);
            Assert.Equal(204, (int)r.StatusCode);
            r = await client.GetAsync("/altro");
            Assert.Equal(404, (int)r.StatusCode);
            Assert.Equal("ROUTE_NOT_FOUND", ((Dictionary<string, object?>)((Dictionary<string, object?>)Json.Parse(await r.Content.ReadAsStringAsync())!)["error"]!)["code"]);
        }
        finally
        {
            await app.StopAsync();
            await app.DisposeAsync();
        }
''',
    "rt_api_convert": r'''
        Assert.Null(ApiConvert.ToUuid(null));
        Assert.Null(ApiConvert.ToInt(null));
        Assert.Null(ApiConvert.ToBigint(null));
        Assert.Null(ApiConvert.ToDecimal(null));
        Assert.Null(ApiConvert.ToDate(null));
        Assert.Null(ApiConvert.ToDatetime(null));
        Assert.Null(ApiConvert.ToJsonText(null));
        Assert.Null(ApiConvert.UuidText(null));
        Assert.Null(ApiConvert.Text(null));
        Assert.Null(ApiConvert.DecimalText(null, 2));
        Assert.Null(ApiConvert.DateText(null));
        Assert.Null(ApiConvert.DatetimeText(null));
        Assert.Null(ApiConvert.JsonValue(null));
        Assert.Equal(Guid.Parse("00000000-0000-4000-8000-00000000000a"), ApiConvert.ToUuid("00000000-0000-4000-8000-00000000000A"));
        Assert.Equal("00000000-0000-4000-8000-00000000000a", ApiConvert.UuidText(Guid.Parse("00000000-0000-4000-8000-00000000000A")));
        Assert.Equal(7, ApiConvert.ToInt(7L));
        Assert.Equal(12345678901L, ApiConvert.ToBigint("12345678901"));
        Assert.Equal("12345678901", ApiConvert.Text(12345678901L));
        Assert.Equal(1.5m, ApiConvert.ToDecimal("1.5"));
        Assert.Equal("1.50", ApiConvert.DecimalText(1.5m, 2));
        Assert.Equal("3", ApiConvert.DecimalText(3m, 0));
        Assert.Equal("-7.12", ApiConvert.DecimalText(-7.129m, 2));
        Assert.Equal("0.00", ApiConvert.DecimalText(-0.001m, 2));
        Assert.Equal(new DateOnly(2026, 2, 3), ApiConvert.ToDate("2026-02-03"));
        Assert.Equal("2026-02-03", ApiConvert.DateText(new DateOnly(2026, 2, 3)));
        var utc = new DateTimeOffset(2026, 2, 3, 4, 5, 6, 123, TimeSpan.Zero);
        Assert.Equal(utc, ApiConvert.ToDatetime("2026-02-03T04:05:06.123456789Z"));
        Assert.Equal(utc, ApiConvert.ToDatetime("2026-02-03T06:05:06.123+02:00"));
        Assert.Equal(TimeSpan.Zero, ApiConvert.ToDatetime("2026-02-03T06:05:06.123+02:00")!.Value.Offset);
        Assert.Equal(utc.AddMilliseconds(-3), ApiConvert.ToDatetime("2026-02-02T22:35:06.12-05:30"));
        Assert.Equal(utc.AddMilliseconds(-123), ApiConvert.ToDatetime("2026-02-03T04:05:06Z"));
        Assert.Equal("2026-02-03T04:05:06.123Z", ApiConvert.DatetimeText(utc));
        Assert.Equal("2026-02-03T04:05:06.123Z", ApiConvert.DatetimeText(new DateTimeOffset(2026, 2, 3, 6, 5, 6, 123, TimeSpan.FromHours(2))));
        Assert.Equal("{\"a\":[1,true]}", ApiConvert.ToJsonText(J("{'a': [1, true]}")));
        Same(J("{'a': 1}"), ApiConvert.JsonValue("{\"a\": 1}"));
        Assert.Equal(new[] { 1, 2 }, ApiConvert.Each(J("[1, 2]"), x => ApiConvert.ToInt(x)!.Value));
        var page = ApiConvert.PageJson(new Page<string>(new[] { "a" }, "c", 5), x => new Dictionary<string, object?> { ["v"] = x });
        Same(J("{'items': [{'v': 'a'}], 'nextCursor': 'c', 'limit': 5}"), page);
        var pr = ApiConvert.Request(Q("limit", 3L, "cursor", "k", "sort", "-x"));
        Assert.Equal(((int?)3, "k", "-x"), (pr.Limit, pr.Cursor, pr.Sort));
        Assert.Null(ApiConvert.Request(Q()).Limit);
        await Task.CompletedTask;
''',
}

FAKE_DB = r'''
// kybes:sql-begin
/// <summary>Errore del database con SQLSTATE, per i test della traduzione degli errori.</summary>
internal sealed class FakeDbException : DbException
{
    private readonly string? state;

    public FakeDbException(string? state) : base("errore del database") { this.state = state; }

    public override string? SqlState => state;
}
// kybes:sql-end
'''


def _custom_body(ops: List[Operation], tables: Dict[str, Table]) -> str:
    custom = [o for o in ops if o.kind == "custom"]
    ctx = json.dumps(ops[0].context)
    o = []
    if custom:
        o += ["        var empty = KybesApi.Build(new ApiData(), new Recorder(), Array.Empty<string>());", "        Assert.Empty(empty.Routes);",
              '        Assert.Equal(404, (await empty.HandleAsync(Req("GET", "/qualsiasi"))).Status);',
              "        var missing = Assert.Throws<ArgumentException>(() => KybesApi.Build(new ApiData(), null));",
              f'        Assert.Contains("{custom[0].op_id}", missing.Message);']
        free = [x.context for x in ops if x.kind != "custom" and x.context not in {c.context for c in custom}]
        if free:
            o += [f"        var only = KybesApi.Build(new ApiData(), null, new[] {{ {json.dumps(free[0])} }});",
                  f"        Assert.All(only.Routes, r => Assert.Equal({json.dumps(free[0])}, r.Spec.Context));"]
        o += ["        var rec = new Recorder();", "        var full = KybesApi.Build(new ApiData(), rec);", f"        Assert.Equal({len(ops)}, full.Routes.Count);",
              '        Assert.Equal("/x", KybesApi.Build(new ApiData(), rec, null, "/x").BasePath);',
              f"        var one = KybesApi.Build(new ApiData(), rec, new[] {{ {ctx} }});",
              f'        var res = await full.Routes.First(r => r.Spec.Id == "{custom[0].op_id}").Handler!(new Call("x", Q(), Q(), null, Self, "c", null));',
              '        Same(J("{\'operation\': \'x\'}"), res);', "        Assert.Single(rec.Calls);"]
    else:
        o += ["        var empty = KybesApi.Build(new ApiData(), Array.Empty<string>());", "        Assert.Empty(empty.Routes);",
              '        Assert.Equal(404, (await empty.HandleAsync(Req("GET", "/qualsiasi"))).Status);',
              f"        Assert.Equal({len(ops)}, KybesApi.Build(new ApiData()).Routes.Count);",
              '        Assert.Equal("/x", KybesApi.Build(new ApiData(), null, "/x").BasePath);',
              f"        var one = KybesApi.Build(new ApiData(), new[] {{ {ctx} }});"]
    o += [f"        Assert.NotEmpty(one.Routes);", f"        Assert.All(one.Routes, r => Assert.Equal({ctx}, r.Spec.Context));",
          '        var call = new Call("op", Q(), Q(), null, Self, "cid", "t1", "/v1");',
          '        Assert.Equal(("op", "cid", "t1", Self, "/v1"), (call.Operation, call.CorrelationId, call.Tenant, call.Identity, call.BasePath));']
    if has_sql(tables):
        o += ["        var noSql = await Assert.ThrowsAsync<InvalidOperationException>(() => new ApiData().ReadAsync(null, db => Task.FromResult(1)));",
              '        Assert.Contains("SqlFor", noSql.Message);', "        KybesDb.Open().Dispose();",
              "        var data = new ApiData { SqlFor = _ => Fresh() };",
              "        Assert.Null(await data.ReadAsync(null, db => Task.FromResult(db.KybesTenant)));",
              "        Assert.Equal(KybesBuilders.TENANT_A, await data.ReadAsync(KybesBuilders.TENANT_A.ToString(), db => Task.FromResult(db.KybesTenant)));",
              "        Assert.Equal(5, await data.WriteAsync(Array.Empty<string>(), KybesBuilders.TENANT_A.ToString(), db => Task.FromResult(5)));"]
    if any(t.mongo for t in tables.values()):
        o += ["        var noMongo = await Assert.ThrowsAsync<InvalidOperationException>(() => new ApiData().MongoReadAsync(null, db => Task.FromResult(1)));",
              '        Assert.Contains("MongoClient", noMongo.Message);', "        var session = KybesMongo.Open();", "        try", "        {",
              "            var name = session.Db.DatabaseNamespace.DatabaseName;",
              "            var byTenant = new ApiData { MongoClient = KybesMongo.Client(), MongoDatabaseFor = t => name };",
              "            Assert.Equal(name, await byTenant.MongoReadAsync(null, db => Task.FromResult(db.Db.DatabaseNamespace.DatabaseName)));",
              "            var plain = new ApiData { MongoClient = KybesMongo.Client(), MongoDatabase = name };",
              "            Assert.Equal(name, await plain.MongoWriteAsync(null, db => Task.FromResult(db.Db.DatabaseNamespace.DatabaseName)));",
              "        }", "        finally", "        {", "            KybesMongo.Close(session);", "        }"]
    return "\n".join(o) + "\n"


def render(cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str, model_ns: str, api_ns: str, ctrl_ns: str) -> str:
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    bodies = dict(BODIES)
    bodies["rt_api_custom"] = _custom_body(ops, tables)
    o = [header("csharp", "kit").rstrip("\n"), "// <auto-generated />", HEAD.lstrip("\n").rstrip("\n")]
    for tc in cat.for_table(API_RT, "api"):
        title = tc.id + " · " + ", ".join(tc.reqs) + " · " + METHODS[tc.method] + ": " + tc.title
        o += ["", f"    [Fact(DisplayName = {json.dumps(title, ensure_ascii=False)})]", f"    public async Task {tc.kind}()", "    {",
              f"        // atteso: {tc.expected}", bodies[tc.kind].strip("\n"), "    }"]
    o.append("}")
    o.append(FAKE_DB.rstrip("\n"))
    text = "\n".join(o) + "\n"
    text = text.replace("__CTRL__", ctrl_ns).replace("__API__", api_ns).replace("__MODEL__", model_ns)
    return _strip_block(strip_sql(text, sql), "mongo", mongo)
