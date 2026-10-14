"""Test JUnit dei moduli comuni delle API Java, con operazioni sintetiche (indipendenti dagli schemi)."""
from __future__ import annotations

import json
from typing import Dict, List

from api_plan import Operation
from naming import header
from runtime_api_typescript import _strip_block
from schema import Table
from sqlonly import has_sql, strip_sql
from verification import API_RT, METHODS, Catalog

HEAD = r'''
import static org.junit.jupiter.api.Assertions.*;

import __API__.Api;
import __API__.ApiData;
import __API__.ApiError;
import __API__.ApiRequest;
import __API__.ApiResponse;
import __API__.Call;
import __API__.Convert;
import __API__.Errors;
import __API__.Handler;
import __API__.HttpServerAdapter;
import __API__.Identity;
import __API__.IdentityReader;
import __API__.Json;
import __API__.JsonSchema;
import __API__.KybesApi;
import __API__.LambdaAdapter;
import __API__.Route;
import __API__.Spec;
import __API__.SpringAdapter;
import com.sun.net.httpserver.HttpServer;
import java.io.ByteArrayInputStream;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.converter.ByteArrayHttpMessageConverter;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.web.servlet.function.HandlerFunction;
import org.springframework.web.servlet.function.RouterFunction;
import org.springframework.web.servlet.function.ServerRequest;
import org.springframework.web.servlet.function.ServerResponse;
import org.springframework.web.util.ServletRequestPathUtils;
// kybes:sql-begin
import jakarta.persistence.EntityManager;
import jakarta.persistence.EntityNotFoundException;
import jakarta.persistence.PersistenceException;
import java.sql.SQLException;
// kybes:sql-end
// kybes:mongo-begin
import com.mongodb.MongoException;
// kybes:mongo-end

/** Test di unità generati per i moduli comuni delle API. Specifica: docs/generated/verification/kybes-api-runtime.md. */
class KybesApiRuntimeTest {

    private static final Identity ME = new Identity("kybes-test", "t1", Set.of("s.read"), Map.of());
    private static final List<Spec> SPECS = List.of(
            spec("{'id': 'getItem', 'method': 'GET', 'path': '/items/{id}', 'context': 'uno', 'kind': 'custom', 'table': null, 'arg': null,"
                    + " 'status': 200, 'secured': true, 'scopes': ['s.read'], 'body': null, 'bodyRequired': false, 'params': ["
                    + "{'name': 'id', 'in': 'path', 'required': true, 'schema': {'type': 'integer'}},"
                    + "{'name': 'tag', 'in': 'query', 'required': false, 'schema': {'type': 'array', 'items': {'type': 'string'}}},"
                    + "{'name': 'n', 'in': 'query', 'required': true, 'schema': {'type': 'integer', 'minimum': 1}}]}"),
            spec("{'id': 'special', 'method': 'GET', 'path': '/items/special', 'context': 'uno', 'kind': 'custom', 'table': null, 'arg': null,"
                    + " 'status': 200, 'secured': false, 'scopes': [], 'params': [], 'body': null, 'bodyRequired': false}"),
            spec("{'id': 'putItem', 'method': 'PUT', 'path': '/items/{id}', 'context': 'due', 'kind': 'custom', 'table': null, 'arg': null,"
                    + " 'status': 200, 'secured': false, 'scopes': [], 'bodyRequired': true,"
                    + " 'params': [{'name': 'id', 'in': 'path', 'required': true, 'schema': {'type': 'integer'}}],"
                    + " 'body': {'type': 'object', 'required': ['nome'], 'properties': {'nome': {'type': 'string', 'maxLength': 3}},"
                    + " 'additionalProperties': false}}"),
            spec("{'id': 'postOpt', 'method': 'POST', 'path': '/opt', 'context': 'due', 'kind': 'custom', 'table': null, 'arg': null,"
                    + " 'status': 204, 'secured': false, 'scopes': [], 'params': [], 'body': {'type': 'object'}, 'bodyRequired': false}"),
            spec("{'id': 'boom', 'method': 'POST', 'path': '/boom', 'context': 'due', 'kind': 'custom', 'table': null, 'arg': null,"
                    + " 'status': 200, 'secured': false, 'scopes': [], 'params': [], 'body': null, 'bodyRequired': false}"));
    private static final Handler ECHO = call -> {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("op", call.operation());
        out.put("path", call.path());
        out.put("query", call.query());
        out.put("body", call.body());
        return out;
    };

    /** JSON scritto con gli apici singoli (più leggibile nei test). */
    private static Object j(String text) {
        return Json.parse(text.replace('\'', '"'));
    }

    private static Spec spec(String text) {
        return Spec.of(text.replace('\'', '"'));
    }

    private static Api synthetic(String basePath, Handler boom) {
        Map<String, Handler> handlers = new HashMap<>();
        handlers.put("getItem", ECHO);
        handlers.put("special", call -> ApiResponse.reply(202, Map.of("x", 1L), Map.of("location", call.basePath() + "/items/special")));
        handlers.put("putItem", ECHO);
        handlers.put("postOpt", ECHO);
        handlers.put("boom", boom);
        return new Api(SPECS, handlers, basePath);
    }

    private static Api synthetic() {
        return synthetic("", call -> {
            throw new IllegalStateException("dettaglio interno da non mostrare");
        });
    }

    private static Map<String, List<String>> q(String... kv) {
        Map<String, List<String>> out = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) out.computeIfAbsent(kv[i], k -> new ArrayList<>()).add(kv[i + 1]);
        return out;
    }

    private static ApiRequest req(String method, String path, Map<String, List<String>> query, Object body, Identity who, Map<String, String> headers) {
        Map<String, String> h = new LinkedHashMap<>();
        h.put("content-type", "application/json");
        h.putAll(headers);
        byte[] raw = body instanceof String s ? s.getBytes(StandardCharsets.UTF_8) : (byte[]) body;
        return new ApiRequest(method, path, query, h, raw, who);
    }

    private static ApiRequest req(String method, String path, Map<String, List<String>> query) {
        return req(method, path, query, null, ME, Map.of());
    }

    private static ApiRequest req(String method, String path) {
        return req(method, path, Map.of());
    }

    /** Corpo della risposta come lo legge un client. */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> body(ApiResponse r) {
        return (Map<String, Object>) Json.parse(r.text());
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> error(ApiResponse r) {
        return (Map<String, Object>) body(r).get("error");
    }

    private static Object fields(ApiResponse r) {
        return error(r).get("fields");
    }

    private static Map<String, String> validate(Object schema, Object value) {
        Map<String, String> errors = new LinkedHashMap<>();
        JsonSchema.validate(asMap(schema), value, "campo", errors);
        return errors;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object x) {
        return (Map<String, Object>) x;
    }
'''

BODIES: Dict[str, List[str]] = {
    "rt_api_validate": r'''
        Object[][] cases = {
            {"{'type': 'string'}", "x", null}, {"{'type': 'string'}", 1L, "tipo atteso: string"}, {"{'type': 'integer'}", 2.0, null},
            {"{'type': 'integer'}", 2.5, "tipo atteso: integer"}, {"{'type': 'number'}", 3L, null}, {"{'type': 'boolean'}", 1L, "tipo atteso: boolean"},
            {"{'type': 'boolean'}", true, null}, {"{'type': 'integer'}", new BigInteger("99999999999999999999"), null},
            {"{'type': 'string'}", null, "nullo non ammesso"}, {"{'type': 'string', 'nullable': true}", null, null}, {"{}", null, null},
            {"{'enum': ['a', 'b']}", "c", "valore non ammesso"}, {"{'enum': ['a', 'b']}", "a", null}, {"{'enum': [{'a': 1}]}", j("{'a': 1}"), null},
            {"{'enum': [1, 2]}", 2.0, null}, {"{'enum': [1, 2]}", "1", "valore non ammesso"},
            {"{'type': 'string', 'minLength': 2}", "a", "lunghezza minima 2"}, {"{'type': 'string', 'maxLength': 2}", "àbc", "lunghezza massima 2"},
            {"{'type': 'string', 'maxLength': 2}", "àb", null}, {"{'type': 'string', 'pattern': '^[0-9]+$'}", "12a", "formato non valido"},
            {"{'type': 'string', 'pattern': '^[0-9]+$'}", "12", null},
            {"{'type': 'string', 'format': 'uuid'}", "x", "formato uuid"}, {"{'type': 'string', 'format': 'date'}", "2026-02-30", "formato date"},
            {"{'type': 'string', 'format': 'date-time'}", "2026-01-01T10:00:00Z", null},
            {"{'type': 'integer', 'minimum': 1}", 0L, "valore minimo 1"}, {"{'type': 'number', 'maximum': 1.5}", 2L, "valore massimo 1.5"},
            {"{'type': 'number', 'minimum': 1, 'maximum': 2}", 1.5, null},
            {"{'type': 'array', 'minItems': 1}", List.of(), "almeno 1 elementi"}, {"{'type': 'array', 'maxItems': 1}", List.of(1L, 2L), "al massimo 1 elementi"},
            {"{'type': 'array'}", List.of(1L), null}, {"{'type': 'object'}", List.of(), "tipo atteso: object"}, {"{'type': 'array'}", Map.of(), "tipo atteso: array"},
            {"{'type': 'string'}", UUID.randomUUID(), "tipo atteso: string"}, {"{'type': 'number'}", "x", "tipo atteso: number"},
            {"{'type': 'string', 'minLength': 2}", "ab", null}, {"{'type': 'array', 'minItems': 1}", List.of(1L), null},
            {"{'type': 'array', 'maxItems': 1}", List.of(1L), null}, {"{}", UUID.randomUUID(), null},
            {"{'type': 'string', 'pattern': '^[0-9]+$'}", "12\n", "formato non valido"}, {"{'type': 'string', 'pattern': '^(a|b)$|^c$'}", "c", null},
            {"{'type': 'string', 'format': 'uuid'}", "00000000-0000-4000-8000-00000000000a\n", "formato uuid"},
        };
        for (Object[] c : cases) {
            Map<String, String> expected = c[2] == null ? Map.of() : Map.of("campo", (String) c[2]);
            assertEquals(expected, validate(j((String) c[0]), c[1]), c[0] + " " + c[1]);
        }
        Object schema = j("{'type': 'object', 'required': ['a', 'b'], 'properties': {'a': {'type': 'array', 'items': {'type': 'integer'}},"
                + " 'o': {'type': 'object', 'properties': {'x': {'type': 'string'}}, 'additionalProperties': {'type': 'integer'}}},"
                + " 'additionalProperties': false}");
        Map<String, String> errors = new LinkedHashMap<>();
        JsonSchema.validate(asMap(schema), j("{'a': [1, 'x'], 'o': {'x': 1, 'y': 'z', 'w': 2}, 'k': 1}"), "", errors);
        assertEquals(j("{'b': 'obbligatorio', 'a[1]': 'tipo atteso: integer', 'o.x': 'tipo atteso: string', 'o.y': 'tipo atteso: integer', 'k': 'non ammesso'}"), errors);
        errors = new LinkedHashMap<>(Map.of("body", "già presente"));
        JsonSchema.validate(asMap(j("{'type': 'string'}")), 1L, "", errors);
        assertEquals(Map.of("body", "già presente"), errors);
        errors = new LinkedHashMap<>();
        JsonSchema.validate(asMap(j("{'type': 'object', 'properties': {}}")), j("{'libero': 1}"), "", errors);
        JsonSchema.validate(asMap(j("{'type': 'object'}")), j("{'libero': 1}"), "", errors);
        Map<String, String> taken = new LinkedHashMap<>(Map.of("p.a", "x", "p.x", "y"));
        JsonSchema.validate(asMap(j("{'type': 'object', 'required': ['a'], 'properties': {'a': {'type': 'string'}}, 'additionalProperties': false}")),
                j("{'x': 1}"), "p", taken);
        assertEquals(Map.of("p.a", "x", "p.x", "y"), taken);
        assertEquals(Map.of(), errors);
        assertEquals("2", JsonSchema.num(2.0));
        assertEquals("1.5", JsonSchema.num(1.5));
        assertEquals("100", JsonSchema.num(1e2));
        assertEquals("0", JsonSchema.num(0L));
        assertEquals("unknown", JsonSchema.typeOf(UUID.randomUUID()));
        for (String good : List.of("2026-01-01T00:00:00.123456789+02:00", "2026-12-31T23:59:59-05:30")) assertTrue(JsonSchema.checkFormat("date-time", good), good);
        for (String bad : List.of("2026-01-01 10:00:00Z", "2026-02-30T10:00:00Z", "2026-01-01T24:00:00Z", "2026-01-01T10:60:00Z",
                "2026-01-01T10:00:60Z", "2026-01-01T10:00:00+24:00", "2026-01-01T10:00:00+01:60")) assertFalse(JsonSchema.checkFormat("date-time", bad), bad);
        assertTrue(JsonSchema.checkFormat("uuid", "00000000-0000-4000-8000-00000000000A"));
        assertTrue(JsonSchema.checkFormat("date", "2024-02-29"));
        assertFalse(JsonSchema.checkFormat("date", "2026-1-1"));
        assertTrue(JsonSchema.checkFormat("date", "0050-01-01"));
        assertFalse(JsonSchema.checkFormat("date", "0000-01-01"), "l'anno 0 non esiste negli altri linguaggi");
        assertTrue(JsonSchema.jsPattern("^a\\$").matcher("a$").find());
''',
    "rt_api_coerce": r'''
        Map<String, Object> integer = asMap(j("{'type': 'integer'}"));
        assertEquals(new JsonSchema.Coerced(-12L, null), JsonSchema.coerce(integer, List.of("-12")));
        assertEquals(new JsonSchema.Coerced(new BigInteger("99999999999999999999"), null), JsonSchema.coerce(integer, List.of("99999999999999999999")));
        assertEquals(new JsonSchema.Coerced(null, "tipo atteso: integer"), JsonSchema.coerce(integer, List.of("1.5")));
        assertEquals(new JsonSchema.Coerced(150.0, null), JsonSchema.coerce(asMap(j("{'type': 'number'}")), List.of("1.5e2")));
        assertEquals(new JsonSchema.Coerced(null, "tipo atteso: number"), JsonSchema.coerce(asMap(j("{'type': 'number'}")), List.of("abc")));
        assertEquals(new JsonSchema.Coerced(true, null), JsonSchema.coerce(asMap(j("{'type': 'boolean'}")), List.of("true")));
        assertEquals(new JsonSchema.Coerced(false, null), JsonSchema.coerce(asMap(j("{'type': 'boolean'}")), List.of("false")));
        assertEquals(new JsonSchema.Coerced(null, "tipo atteso: boolean"), JsonSchema.coerce(asMap(j("{'type': 'boolean'}")), List.of("1")));
        assertEquals(new JsonSchema.Coerced("x", null), JsonSchema.coerce(asMap(j("{'type': 'string'}")), List.of("x")));
        assertEquals(new JsonSchema.Coerced(null, "un solo valore"), JsonSchema.coerce(asMap(j("{'type': 'string'}")), List.of("x", "y")));
        Map<String, Object> ints = asMap(j("{'type': 'array', 'items': {'type': 'integer'}}"));
        assertEquals(new JsonSchema.Coerced(List.of(1L, 2L), null), JsonSchema.coerce(ints, List.of("1", "2")));
        assertEquals(new JsonSchema.Coerced(null, "tipo atteso: integer"), JsonSchema.coerce(ints, List.of("1", "x")));
        assertEquals(new JsonSchema.Coerced(List.of(), null), JsonSchema.coerce(asMap(j("{'type': 'array'}")), List.of()));
        assertEquals(new JsonSchema.Coerced(List.of("a"), null), JsonSchema.coerce(asMap(j("{'type': 'array'}")), List.of("a")));
        assertEquals(new JsonSchema.Coerced(null, "tipo atteso: number"), JsonSchema.coerce(asMap(j("{'type': 'number'}")), List.of("1e400")));
        assertEquals(new JsonSchema.Coerced(null, "tipo atteso: integer"), JsonSchema.coerce(integer, List.of("1\n")));
        assertEquals(j("{'a': ['1', '3'], 'b': [''], 'c': ['x y', '%zz']}"), ApiRequest.parseQuery("a=1&&b&a=3&c=x+y&c=%zz"));
        assertEquals(Map.of(), ApiRequest.parseQuery(null));
        assertEquals("a+b c", ApiRequest.decode("a+b%20c", false));
''',
    "rt_api_route": r'''
        Api api = synthetic();
        ApiResponse r = api.handle(req("GET", "/items/special"));
        assertEquals(202, r.status(), "il segmento fisso vince sul parametro");
        assertEquals(j("{'x': 1}"), body(r));
        assertEquals(List.of("application/json", "/items/special"), List.of(r.headers().get("content-type"), r.headers().get("location")));
        r = api.handle(req("GET", "/items/%zz", q("n", "1")));
        assertEquals(List.of(400, j("{'id': 'tipo atteso: integer'}")), List.of(r.status(), fields(r)));
        r = api.handle(req("GET", "/items/7", q("n", "2", "tag", "a", "tag", "b")));
        assertEquals(200, r.status());
        assertEquals(j("{'op': 'getItem', 'path': {'id': 7}, 'query': {'n': 2, 'tag': ['a', 'b']}, 'body': null}"), body(r));
        r = api.handle(req("GET", "/items/%37", q("n", "1")));
        assertEquals(j("{'id': 7}"), body(r).get("path"));
        r = api.handle(req("GET", "/items/x", q("n", "0", "altro", "1")));
        assertEquals(400, r.status());
        assertEquals(j("{'altro': 'parametro sconosciuto', 'id': 'tipo atteso: integer', 'n': 'valore minimo 1'}"), fields(r));
        r = api.handle(req("GET", "/items/7"));
        assertEquals(j("{'n': 'obbligatorio'}"), fields(r));
        r = api.handle(req("GET", "/items/x", q("n", "x", "tag", "a"), null, null, Map.of()));
        assertEquals(401, r.status());
        assertEquals("IDENTITY_REQUIRED", error(r).get("code"));
        r = api.handle(req("GET", "/nessuno"));
        assertEquals(404, r.status());
        assertEquals("ROUTE_NOT_FOUND", error(r).get("code"));
        assertEquals(404, api.handle(req("GET", "/items")).status());
        r = api.handle(req("DELETE", "/items/7"));
        assertEquals(405, r.status());
        assertEquals("GET, PUT", r.headers().get("allow"));
        assertEquals("METHOD_NOT_ALLOWED", error(r).get("code"));
        r = api.handle(req("get", "/items/7", q("n", "1"), null, new Identity("u", null, Set.of(), Map.of()), Map.of()));
        assertEquals(403, r.status());
        assertEquals("SCOPE_REQUIRED", error(r).get("code"));
        Api based = synthetic("/v1/", call -> null);
        assertEquals("/v1", based.basePath());
        assertEquals("/v1/items/special", based.handle(req("GET", "/v1/items/special")).headers().get("location"));
        assertEquals(404, based.handle(req("GET", "/v1")).status());
        assertEquals(202, based.handle(req("GET", "/items/special")).status());
        assertEquals(404, based.handle(req("GET", "/v1x/items/special")).status());
        Route route = new Route(SPECS.get(0), ECHO);
        assertSame(ECHO, route.handler());
        assertNull(route.match(List.of("items")));
        assertNull(route.match(List.of("altro", "1")));
        assertEquals(Map.of("id", "1"), route.match(List.of("items", "1")));
        Api sorted = new Api(List.of(SPECS.get(1), SPECS.get(0), SPECS.get(4), SPECS.get(3)), Map.of("getItem", ECHO), "");
        List<String> ids = new ArrayList<>();
        for (Route x : sorted.routes()) ids.add(x.spec().id());
        assertEquals(List.of("boom", "postOpt", "special", "getItem"), ids);
''',
    "rt_api_body": r'''
        Api api = synthetic();
        ApiResponse r = api.handle(req("PUT", "/items/1", Map.of(), "{\"nome\": \"abc\"}", ME, Map.of("content-type", "text/plain")));
        assertEquals(415, r.status());
        assertEquals("JSON_REQUIRED", error(r).get("code"));
        r = api.handle(req("PUT", "/items/1", Map.of(), "{\"nome\": \"abc\"}", ME, Map.of("content-type", "Application/JSON; charset=utf-8")));
        assertEquals(200, r.status());
        assertEquals(j("{'nome': 'abc'}"), body(r).get("body"));
        for (Object raw : List.of("{", "{\"nome\": NaN}", new byte[] {(byte) 0xff}, "{\"nome\": 1e400}", new byte[] {(byte) 0xef, (byte) 0xbb, (byte) 0xbf, '{', '}'})) {
            r = api.handle(req("PUT", "/items/1", Map.of(), raw, ME, Map.of()));
            assertEquals(400, r.status());
            assertEquals(j("{'body': 'JSON non valido'}"), fields(r));
        }
        r = api.handle(req("PUT", "/items/1", Map.of(), "{\"nome\": \"abcd\", \"x\": 1}", ME, Map.of()));
        assertEquals(j("{'nome': 'lunghezza massima 3', 'x': 'non ammesso'}"), fields(r));
        r = api.handle(req("PUT", "/items/1", Map.of(), "[]", ME, Map.of()));
        assertEquals(j("{'body': 'tipo atteso: object'}"), fields(r));
        r = api.handle(req("PUT", "/items/1", q("body", "1")));
        assertEquals(j("{'body': 'parametro sconosciuto'}"), fields(r));
        r = api.handle(req("PUT", "/items/1", q("body", "1"), "{", ME, Map.of()));
        assertEquals(j("{'body': 'parametro sconosciuto'}"), fields(r));
        r = api.handle(req("GET", "/items/special", q("body", "1"), "{}", ME, Map.of()));
        assertEquals(j("{'body': 'parametro sconosciuto'}"), fields(r));
        r = api.handle(req("PUT", "/items/1"));
        assertEquals(400, r.status());
        assertEquals(j("{'body': 'obbligatorio'}"), fields(r));
        r = api.handle(req("POST", "/opt"));
        assertEquals(204, r.status());
        assertFalse(r.hasBody());
        assertEquals("", r.text());
        assertEquals(204, api.handle(req("POST", "/opt", Map.of(), "{\"x\": 1.5}", ME, Map.of())).status());
        r = synthetic("", call -> ApiResponse.reply(204)).handle(req("POST", "/boom"));
        assertEquals(204, r.status());
        assertFalse(r.headers().containsKey("content-type"));
        assertEquals(204, api.handle(req("POST", "/opt", Map.of(), new byte[0], ME, Map.of())).status());
        r = api.handle(req("GET", "/items/special", Map.of(), "{}", ME, Map.of()));
        assertEquals(400, r.status());
        assertEquals(j("{'body': 'corpo non ammesso'}"), fields(r));
        r = api.handle(new ApiRequest("PUT", "/items/1", Map.of(), Map.of(), "{}".getBytes(StandardCharsets.UTF_8), null));
        assertEquals(415, r.status());
        // JSON: lettura e scrittura
        Map<String, Object> parsed = asMap(Json.parse(" {\"a\" : [1, -2.5, 1E+3, true, false, null, {}, [ ]], \"b\": \"x\\\"\\\\\\/\\b\\f\\n\\r\\t\\u00e8\"} "));
        assertEquals(Arrays.asList(1L, -2.5, 1000.0, true, false, null, Map.of(), List.of()), parsed.get("a"));
        assertEquals("x\"\\/\b\f\n\r\tè", parsed.get("b"));
        assertEquals(new BigInteger("123456789012345678901234567890"), Json.parse("123456789012345678901234567890"));
        assertEquals(0L, Json.parse("-0"));
        assertEquals(1.5e-3, Json.parse("1.5e-3"));
        for (String bad : List.of("", "{", "[1,]", "{\"a\" 1}", "{\"a\": 1,}", "{1: 2}", "[1 2]", "\"a", "\"\\x\"", "\"\\u12\"",
                "\"\\u12zz\"", "\"a\nb\"", "01", "-", "1.", "1e", "1e400", "nul", "[1] x", "tru")) {
            assertThrows(Json.JsonException.class, () -> Json.parse(bad), bad);
        }
        assertThrows(Json.JsonException.class, () -> Json.parse("[".repeat(600) + "]".repeat(600)));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("s", "a\"\\\n\r\t\u0001è");
        out.put("d", 1.5);
        out.put("dec", new BigDecimal("1.50"));
        out.put("n", 7);
        out.put("b", true);
        out.put("l", List.of(1L, "x"));
        out.put("u", UUID.fromString("00000000-0000-4000-8000-000000000001"));
        out.put("z", null);
        assertEquals("{\"s\":\"a\\\"\\\\\\n\\r\\t\\u0001è\",\"d\":1.5,\"dec\":1.50,\"n\":7,\"b\":true,\"l\":[1,\"x\"],"
                + "\"u\":\"00000000-0000-4000-8000-000000000001\",\"z\":null}", Json.write(out));
        assertThrows(Json.JsonException.class, () -> Json.write(Double.NaN));
        assertThrows(Json.JsonException.class, () -> Json.write(Double.POSITIVE_INFINITY));
''',
    "rt_api_errors": r'''
        Api api = synthetic();
        ApiResponse r = api.handle(req("POST", "/boom", Map.of(), null, ME, Map.of("x-correlation-id", "abc-1")));
        assertEquals(500, r.status());
        assertEquals(j("{'error': {'code': 'UNEXPECTED', 'message': 'Errore interno', 'correlationId': 'abc-1'}}"), body(r));
        assertEquals("abc-1", r.headers().get("x-correlation-id"));
        assertFalse(r.text().contains("dettaglio"));
        r = api.handle(req("POST", "/boom", Map.of(), null, ME, Map.of("x-correlation-id", "non valido!")));
        assertNotEquals("non valido!", r.headers().get("x-correlation-id"));
        assertEquals(j("{'error': {'code': 'X', 'message': 'Richiesta non valida', 'correlationId': 'c', 'fields': {'a': 'b'}}}"),
                j(Json.write(Errors.errorBody("VALIDATION", "X", "c", Map.of("a", "b")))));
        assertEquals(j("{'error': {'code': 'X', 'message': 'Richiesta non valida', 'correlationId': 'c'}}"),
                j(Json.write(Errors.errorBody("VALIDATION", "X", "c", Map.of()))));
        ApiError same = new ApiError("CONFLICT", "MIO");
        assertSame(same, Api.mapError(same));
        assertEquals(Map.of(), new ApiError("NOT_FOUND", "X").fields());
        ApiError e = Api.mapError(new __MGEN__.ModelValidationException("T", Map.of("limit", "tra 1 e 100")));
        assertEquals(List.of("VALIDATION", "INVALID_PAGE", Map.of("limit", "tra 1 e 100")), List.of(e.kind(), e.code(), e.fields()));
        e = Api.mapError(new __MGEN__.ModelValidationException("T", Map.of("Righe", "record collegati")));
        assertEquals(List.of("CONFLICT", "RELATED_RECORDS"), List.of(e.kind(), e.code()));
        e = Api.mapError(new __MGEN__.ModelValidationException("T", Map.of("Righe", "record collegati", "Nome", "obbligatorio")));
        assertEquals("MODEL_RULE", e.code());
        e = Api.mapError(new __MGEN__.ModelValidationException("T", Map.of("Nome", "obbligatorio")));
        assertEquals(List.of("UNPROCESSABLE", "MODEL_RULE"), List.of(e.kind(), e.code()));
        assertEquals("UNPROCESSABLE", Api.mapError(new __MGEN__.ModelValidationException("T", Map.of())).kind());
        assertEquals("TENANT_REQUIRED", Api.mapError(new __MGEN__.Tenancy.TenantException("x")).code());
        assertEquals("UNEXPECTED", Api.mapError(new IllegalStateException("x", new RuntimeException("y"))).code());
        // kybes:mongo-begin
        assertEquals("DUPLICATE", Api.mapError(new RuntimeException(new MongoException(11000, "dup"))).code());
        assertEquals("UNEXPECTED", Api.mapError(new MongoException(2, "altro")).code());
        // kybes:mongo-end
        // kybes:sql-begin
        assertEquals("RECORD_NOT_FOUND", Api.mapError(new EntityNotFoundException("x")).code());
        assertEquals("CONSTRAINT", Api.mapError(new PersistenceException("x", new SQLException("dup", "23505"))).code());
        assertEquals("UNEXPECTED", Api.mapError(new PersistenceException("x", new SQLException("tabella", "42P01"))).code());
        assertEquals("UNEXPECTED", Api.mapError(new PersistenceException("x", new SQLException("senza stato"))).code());
        assertEquals("RETRY_LATER", Api.mapError(new PersistenceException("x", new SQLException("conflitto", "40001"))).code());
        // kybes:sql-end
        r = synthetic("", call -> {
            throw new __MGEN__.ModelValidationException("T", Map.of("Nome", "obbligatorio"));
        }).handle(req("POST", "/boom"));
        assertEquals(422, r.status());
        assertEquals(j("{'Nome': 'obbligatorio'}"), fields(r));
        r = synthetic("", call -> {
            throw new __MGEN__.Tenancy.TenantException("x");
        }).handle(req("POST", "/boom"));
        assertEquals(403, r.status());
        assertNull(fields(r));
        ApiResponse custom = ApiResponse.reply(201, Map.of("a", 1L), Map.of("location", "/x"));
        assertEquals(List.of(201, "/x", "{\"a\":1}"), List.of(custom.status(), custom.headers().get("location"), custom.text()));
        assertEquals("application/json", ApiResponse.reply(200, null).headers().get("content-type"));
        assertEquals("null", ApiResponse.reply(200, null).text());
''',
    "rt_api_identity": r'''
        assertEquals(List.of(), IdentityReader.scopesOf(null));
        assertEquals(List.of("a", "1"), IdentityReader.scopesOf(List.of("a", 1)));
        assertEquals(List.of("a", "b"), IdentityReader.scopesOf("[a b]"));
        assertEquals(List.of("[a", "b"), IdentityReader.scopesOf("[a b"));
        assertEquals(List.of("a", "b", "c"), IdentityReader.scopesOf("a,b c"));
        assertEquals(List.of(), IdentityReader.scopesOf(""));
        Map<String, Object> claims = new HashMap<>();
        claims.put(IdentityReader.CLAIM_SUBJECT, "u1");
        claims.put(IdentityReader.CLAIM_TENANT, "t1");
        claims.put(IdentityReader.CLAIM_SCOPES.get(0), "a b");
        Identity i = IdentityReader.fromClaims(claims);
        assertEquals(List.of("u1", "t1", Set.of("a", "b"), claims), List.of(i.subject(), i.tenant(), i.scopes(), i.claims()));
        claims = new HashMap<>();
        claims.put(IdentityReader.CLAIM_SUBJECT, "");
        claims.put(IdentityReader.CLAIM_TENANT, null);
        i = IdentityReader.fromClaims(claims);
        assertNull(i.subject());
        assertNull(i.tenant());
        assertTrue(i.scopes().isEmpty());
        assertNull(IdentityReader.fromLambda(Map.of()));
        assertNull(IdentityReader.fromLambda(Map.of("requestContext", "x")));
        assertNull(IdentityReader.fromLambda(Map.of("requestContext", Map.of("authorizer", "x"))));
        String sub = IdentityReader.CLAIM_SUBJECT;
        assertEquals("a", IdentityReader.fromLambda(Map.of("requestContext", Map.of("authorizer", Map.of("jwt", Map.of("claims", Map.of(sub, "a")))))).subject());
        assertEquals("b", IdentityReader.fromLambda(Map.of("requestContext", Map.of("authorizer", Map.of("jwt", Map.of(), "lambda", Map.of(sub, "b"))))).subject());
        assertEquals("c", IdentityReader.fromLambda(Map.of("requestContext", Map.of("authorizer", Map.of("claims", Map.of(sub, "c"))))).subject());
        assertEquals("d", IdentityReader.fromLambda(Map.of("requestContext", Map.of("authorizer", Map.of(sub, "d")))).subject());
        assertEquals("e", IdentityReader.fromLambda(Map.of("requestContext", Map.of("authorizer", Map.of("claims", Json.write(Map.of(sub, "e")))))).subject());
        assertNull(IdentityReader.fromHeaders(Map.of()));
        i = IdentityReader.fromHeaders(Map.of(IdentityReader.HEADER_SUBJECT, "u", IdentityReader.HEADER_TENANT, "t", IdentityReader.HEADER_SCOPES, "x y"));
        assertEquals(List.of("u", "t", Set.of("x", "y")), List.of(i.subject(), i.tenant(), i.scopes()));
        assertNull(IdentityReader.fromHeaders(Map.of(IdentityReader.HEADER_SUBJECT, "u")).tenant());
        Identity anon = Identity.anonymous();
        assertEquals(List.of(Set.of(), Map.of()), List.of(anon.scopes(), anon.claims()));
''',
    "rt_api_lambda": r'''
        Api api = synthetic();
        String sub = IdentityReader.CLAIM_SUBJECT;
        String scp = IdentityReader.CLAIM_SCOPES.get(0);
        Map<String, Object> v2 = new HashMap<>();
        v2.put("version", "2.0");
        v2.put("rawPath", "/items/7");
        v2.put("rawQueryString", "n=2&tag=a&tag=b");
        v2.put("headers", Map.of("Content-Type", "application/json"));
        v2.put("requestContext", Map.of("http", Map.of("method", "GET"), "authorizer", Map.of("jwt", Map.of("claims", Map.of(sub, "u", scp, "s.read")))));
        Map<String, Object> out = LambdaAdapter.handle(api, v2);
        assertEquals(200, out.get("statusCode"));
        assertEquals(false, out.get("isBase64Encoded"));
        assertEquals(j("{'n': 2, 'tag': ['a', 'b']}"), asMap(Json.parse((String) out.get("body"))).get("query"));
        Map<String, Object> put = new HashMap<>();
        put.put("httpMethod", "PUT");
        put.put("path", "/items/1");
        put.put("headers", Map.of("content-type", "application/json"));
        put.put("body", Base64.getEncoder().encodeToString("{\"nome\": \"ab\"}".getBytes(StandardCharsets.UTF_8)));
        put.put("isBase64Encoded", true);
        put.put("requestContext", Map.of());
        assertEquals(j("{'nome': 'ab'}"), asMap(Json.parse((String) LambdaAdapter.handle(api, put).get("body"))).get("body"));
        Map<String, Object> v1 = new HashMap<>();
        v1.put("httpMethod", "GET");
        v1.put("path", "/items/7");
        v1.put("multiValueQueryStringParameters", Map.of("n", List.of("3")));
        v1.put("queryStringParameters", Map.of("n", "3"));
        v1.put("requestContext", Map.of("authorizer", Map.of("claims", Map.of(sub, "u", scp, "s.read"))));
        assertEquals(j("{'n': 3}"), asMap(Json.parse((String) LambdaAdapter.handle(api, v1).get("body"))).get("query"));
        Map<String, Object> single = new HashMap<>();
        single.put("httpMethod", "POST");
        single.put("queryStringParameters", Map.of("a", "1"));
        single.put("body", "{}");
        ApiRequest s = LambdaAdapter.toRequest(single);
        assertEquals(List.of(Map.of("a", List.of("1")), "/", "{}"), List.of(s.query(), s.path(), new String(s.body(), StandardCharsets.UTF_8)));
        assertNull(s.identity());
        Map<String, Object> bare = new HashMap<>();
        bare.put("version", "2.0");
        bare.put("rawPath", "");
        bare.put("requestContext", Map.of("http", Map.of("method", "GET")));
        assertEquals("/", LambdaAdapter.toRequest(bare).path());
        assertEquals(Map.of(), LambdaAdapter.toRequest(Map.of("httpMethod", "GET")).query());
        assertEquals(j("{'statusCode': 204, 'headers': {}, 'isBase64Encoded': false, 'body': ''}"), j(Json.write(LambdaAdapter.toProxy(ApiResponse.reply(204)))));
''',
    "rt_api_http": r'''
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", HttpServerAdapter.handler(synthetic()));
        server.start();
        try {
            String base = "http://127.0.0.1:" + server.getAddress().getPort();
            HttpClient client = HttpClient.newHttpClient();
            HttpResponse<String> r = client.send(HttpRequest.newBuilder(URI.create(base + "/items/4?n=1&tag=a&tag=b"))
                    .header(IdentityReader.HEADER_SUBJECT, "u").header(IdentityReader.HEADER_SCOPES, "s.read").build(), HttpResponse.BodyHandlers.ofString());
            assertEquals(200, r.statusCode());
            assertEquals(j("{'n': 1, 'tag': ['a', 'b']}"), asMap(Json.parse(r.body())).get("query"));
            assertTrue(r.headers().firstValue("x-correlation-id").isPresent());
            r = client.send(HttpRequest.newBuilder(URI.create(base + "/items/4")).header("content-type", "application/json").header("x-multi", "a")
                    .PUT(HttpRequest.BodyPublishers.ofString("{\"nome\": \"x\"}")).build(), HttpResponse.BodyHandlers.ofString());
            assertEquals(j("{'nome': 'x'}"), asMap(Json.parse(r.body())).get("body"));
            r = client.send(HttpRequest.newBuilder(URI.create(base + "/opt")).POST(HttpRequest.BodyPublishers.noBody()).build(), HttpResponse.BodyHandlers.ofString());
            assertEquals(204, r.statusCode());
            assertEquals("", r.body());
        } finally {
            server.stop(0);
        }
''',
    "rt_api_framework": r'''
        RouterFunction<ServerResponse> routes = SpringAdapter.routes(synthetic("/v1", call -> null));
        MockHttpServletRequest http = new MockHttpServletRequest("GET", "/v1/items/7");
        http.setQueryString("n=1&tag=a&tag=b");
        http.addHeader(IdentityReader.HEADER_SUBJECT, "u");
        http.addHeader(IdentityReader.HEADER_SCOPES, "s.read");
        http.addHeader("x-multi", "a");
        http.addHeader("x-multi", "b");
        ServletRequestPathUtils.parseAndCache(http);
        ServerRequest request = ServerRequest.create(http, List.of(new ByteArrayHttpMessageConverter()));
        ServerResponse resp = routes.route(request).orElseThrow().handle(request);
        assertEquals(200, resp.statusCode().value());
        assertNotNull(resp.headers().getFirst("x-correlation-id"));
        MockHttpServletResponse out = new MockHttpServletResponse();
        resp.writeTo(http, out, () -> List.of(new ByteArrayHttpMessageConverter()));
        assertEquals(j("{'n': 1, 'tag': ['a', 'b']}"), asMap(Json.parse(out.getContentAsString())).get("query"));
        http = new MockHttpServletRequest("PUT", "/v1/items/7");
        http.setContentType("application/json");
        http.addHeader("content-type", "application/json");
        http.setContent("{\"nome\": \"x\"}".getBytes(StandardCharsets.UTF_8));
        ServletRequestPathUtils.parseAndCache(http);
        request = ServerRequest.create(http, List.of(new ByteArrayHttpMessageConverter()));
        assertEquals(j("{'nome': 'x'}"), Json.parse(new String(SpringAdapter.toRequest(request).body(), StandardCharsets.UTF_8)));
        http = new MockHttpServletRequest("POST", "/v1/opt");
        ServletRequestPathUtils.parseAndCache(http);
        request = ServerRequest.create(http, List.of(new ByteArrayHttpMessageConverter()));
        Optional<HandlerFunction<ServerResponse>> found = routes.route(request);
        assertEquals(204, found.orElseThrow().handle(request).statusCode().value());
        http = new MockHttpServletRequest("GET", "/altro");
        ServletRequestPathUtils.parseAndCache(http);
        request = ServerRequest.create(http, List.of(new ByteArrayHttpMessageConverter()));
        resp = routes.route(request).orElseThrow().handle(request);
        assertEquals(404, resp.statusCode().value(), "percorso sconosciuto: 404 del nucleo, come gli altri adattatori");
        assertEquals(500, SpringAdapter.toResponse(ApiResponse.reply(500, Map.of())).statusCode().value());
''',
    "rt_api_convert": r'''
        assertNull(Convert.toUuid(null));
        assertNull(Convert.toInt(null));
        assertNull(Convert.toBigint(null));
        assertNull(Convert.toDecimal(null));
        assertNull(Convert.toDate(null));
        assertNull(Convert.toDatetime(null));
        assertNull(Convert.toJsonText(null));
        assertNull(Convert.uuidText(null));
        assertNull(Convert.text(null));
        assertNull(Convert.decimalText(null, 2));
        assertNull(Convert.dateText(null));
        assertNull(Convert.datetimeText(null));
        assertNull(Convert.jsonValue(null));
        assertEquals(UUID.fromString("00000000-0000-4000-8000-00000000000a"), Convert.toUuid("00000000-0000-4000-8000-00000000000A"));
        assertEquals("00000000-0000-4000-8000-00000000000a", Convert.uuidText(UUID.fromString("00000000-0000-4000-8000-00000000000A")));
        assertEquals(Integer.valueOf(7), Convert.toInt(7L));
        assertEquals(Long.valueOf(12345678901L), Convert.toBigint("12345678901"));
        assertEquals("12345678901", Convert.text(12345678901L));
        assertEquals(new BigDecimal("1.5"), Convert.toDecimal("1.5"));
        assertEquals("1.50", Convert.decimalText(new BigDecimal("1.5"), 2));
        assertEquals("3", Convert.decimalText(new BigDecimal("3"), 0));
        assertEquals("-7.12", Convert.decimalText(new BigDecimal("-007.129"), 2));
        assertEquals("0.00", Convert.decimalText(new BigDecimal("-0.001"), 2));
        assertEquals(LocalDate.of(2026, 2, 3), Convert.toDate("2026-02-03"));
        assertEquals("2026-02-03", Convert.dateText(LocalDate.of(2026, 2, 3)));
        OffsetDateTime utc = OffsetDateTime.of(2026, 2, 3, 4, 5, 6, 123_000_000, ZoneOffset.UTC);
        assertEquals(utc.toInstant(), Convert.toDatetime("2026-02-03T04:05:06.123456789Z").toInstant());
        assertEquals(utc.toInstant(), Convert.toDatetime("2026-02-03T06:05:06.123+02:00").toInstant());
        assertEquals(utc.toInstant().minusMillis(3), Convert.toDatetime("2026-02-02T22:35:06.12-05:30").toInstant());
        assertEquals(utc.toInstant().minusMillis(123), Convert.toDatetime("2026-02-03T04:05:06Z").toInstant());
        assertEquals("2026-02-03T04:05:06.123Z", Convert.datetimeText(utc));
        assertEquals("2026-02-03T04:05:06.123Z", Convert.datetimeText(Convert.toDatetime("2026-02-03T06:05:06.123+02:00")));
        assertEquals("{\"a\":[1,true]}", Convert.toJsonText(j("{'a': [1, true]}")));
        assertEquals(j("{'a': 1}"), Convert.jsonValue("{\"a\": 1}"));
        assertEquals(List.of(1, 2), Convert.each(List.of(1L, 2L), Convert::toInt));
        Map<String, Object> page = Convert.page(new __MGEN__.Paging.Page<>(List.of("a"), "c", 5), x -> Map.of("v", x));
        assertEquals(j("{'items': [{'v': 'a'}], 'nextCursor': 'c', 'limit': 5}"), j(Json.write(page)));
        __MGEN__.Paging.PageRequest pr = Convert.request(Map.of("limit", 3L, "cursor", "k", "sort", "-x"));
        assertEquals(List.of(3, "k", "-x"), List.of(pr.limit(), pr.cursor(), pr.sort()));
        assertNull(Convert.request(Map.of()).limit());
''',
}


def _custom_body(ops: List[Operation], tables: Dict[str, Table]) -> str:
    custom = [o for o in ops if o.kind == "custom"]
    o = []
    if custom:
        o += ["        Api empty = KybesApi.build(new ApiData(), new KybesApiSupport.Recorder(), List.of());",
              "        assertEquals(List.of(), empty.routes());", '        assertEquals(404, empty.handle(req("GET", "/qualsiasi")).status());',
              f'        IllegalArgumentException missing = assertThrows(IllegalArgumentException.class, () -> KybesApi.build(new ApiData(), null));',
              f'        assertTrue(missing.getMessage().contains("{custom[0].op_id}"));']
        free = [x.context for x in ops if x.kind != "custom" and x.context not in {c.context for c in custom}]
        if free:
            o += [f'        Api only = KybesApi.build(new ApiData(), null, List.of({json.dumps(free[0])}));',
                  f'        assertTrue(only.routes().stream().allMatch(r -> r.spec().context().equals({json.dumps(free[0])})));']
        o += ["        KybesApiSupport.Recorder rec = new KybesApiSupport.Recorder();",
              "        Api full = KybesApi.build(new ApiData(), rec);", f"        assertEquals({len(ops)}, full.routes().size());",
              '        assertEquals("/x", KybesApi.build(new ApiData(), rec, null, "/x").basePath());']
        first = custom[0]
        o += [f'        Object res = full.routes().stream().filter(r -> r.spec().id().equals("{first.op_id}")).findFirst().orElseThrow()',
              '                .handler().handle(new Call("x", Map.of(), Map.of(), null, ME, "c", null, ""));',
              '        assertEquals(Map.of("operation", "x"), res);', '        assertEquals(1, rec.calls.size());']
    else:
        o += ["        Api empty = KybesApi.build(new ApiData(), List.of());", "        assertEquals(List.of(), empty.routes());",
              '        assertEquals(404, empty.handle(req("GET", "/qualsiasi")).status());',
              f"        assertEquals({len(ops)}, KybesApi.build(new ApiData()).routes().size());",
              '        assertEquals("/x", KybesApi.build(new ApiData(), null, "/x").basePath());']
    ctx = json.dumps(ops[0].context)
    o += [f"        Api one = KybesApi.build(new ApiData(){', new KybesApiSupport.Recorder()' if custom else ''}, List.of({ctx}));",
          f"        assertTrue(!one.routes().isEmpty() && one.routes().stream().allMatch(r -> r.spec().context().equals({ctx})));"]
    o += ["        Call call = new Call(\"op\", Map.of(), Map.of(), null, ME, \"cid\", \"t1\", \"/v1\");",
          '        assertEquals(List.of("op", "cid", "t1", ME, "/v1"), List.of(call.operation(), call.correlationId(), call.tenant(), call.identity(), call.basePath()));']
    if has_sql(tables):
        o += ["        IllegalStateException noSql = assertThrows(IllegalStateException.class, () -> new ApiData().read(null, em -> 1));",
              '        assertTrue(noSql.getMessage().contains("emf"));', "        KybesDb.reset();",
              "        ApiData data = new ApiData().sqlFor(t -> KybesDb.emf());",
              "        assertEquals(Boolean.TRUE, data.read(null, em -> em.isOpen()));",
              "        assertEquals(String.valueOf(KybesBuilders.TENANT_A), data.read(String.valueOf(KybesBuilders.TENANT_A), "
              "(EntityManager em) -> String.valueOf(__MGEN__.Tenancy.of(em))));",
              "        assertEquals(5, (int) new ApiData().emf(KybesDb.emf()).write(List.of(), null, em -> 5));"]
    if any(t.mongo for t in tables.values()):
        o += ["        IllegalStateException noMongo = assertThrows(IllegalStateException.class, () -> new ApiData().mongoRead(null, em -> 1));",
              '        assertTrue(noMongo.getMessage().contains("mongo"));',
              "        __MGEN__.MongoSession ms = KybesMongo.open();", "        try {",
              "            String name = ms.db().getName();",
              "            ApiData byTenant = new ApiData().mongo(KybesMongo.client(), null).mongoDatabaseFor(t -> name);",
              "            assertEquals(name, byTenant.mongoRead(null, em -> em.db().getName()));",
              "            assertEquals(name, new ApiData().mongo(KybesMongo.client(), name).mongoWrite(null, em -> em.db().getName()));",
              "        } finally {", "            KybesMongo.close(ms);", "        }"]
    return "\n".join(o) + "\n"


def render(cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str, model_pkg: str, api_pkg: str) -> str:
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    bodies = dict(BODIES)
    bodies["rt_api_custom"] = _custom_body(ops, tables)
    o = [header("java", "kit").rstrip("\n"), f"package {model_pkg}.generated;", HEAD]
    for tc in cat.for_table(API_RT, "api"):
        title = tc.id + " · " + ", ".join(tc.reqs) + " · " + METHODS[tc.method] + ": " + tc.title
        name = tc.kind
        throws = " throws Exception" if tc.kind in ("rt_api_http", "rt_api_framework") else ""
        o += ["", "    @Test", f"    @DisplayName({json.dumps(title, ensure_ascii=False)})", f"    void {name}(){throws} {{",
              f"        // atteso: {tc.expected}", bodies[tc.kind].strip("\n"), "    }"]
    o.append("}")
    text = "\n".join(o) + "\n"
    text = text.replace("__API__", api_pkg + ".generated").replace("__MGEN__", model_pkg + ".generated")
    return _strip_block(strip_sql(text, sql), "mongo", mongo)
