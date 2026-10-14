"""Test pytest dei moduli comuni delle API Python (validatore, router, identità, dati, adattatori, conversioni).

Usano operazioni sintetiche, così coprono ogni ramo dei moduli comuni qualunque siano gli schemi del progetto.
"""
from __future__ import annotations

from typing import Dict, List

from api_plan import Operation
from naming import header
from schema import Table
from sqlonly import has_sql, strip_sql
from verification import API_RT, METHODS, Catalog

HEAD = '''# ruff: noqa
"""Test di unità generati per i moduli comuni delle API. Specifica: docs/generated/verification/kybes-api-runtime.md."""
import asyncio
import base64
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from api.generated import ApiData, ApiError, ApiRequest, ApiResponse, Identity, build_api
from api.generated._convert import (date_text, datetime_text, decimal_text, text, to_date, to_datetime, to_decimal, to_int,
                                    to_uuid)
from api.generated._http import Call, error_body
from api.generated._identity import CLAIMS, HEADERS, from_claims, from_headers, from_lambda, scopes_of
from api.generated._router import Api, Route, map_error
from api.generated._schema import check_format, coerce, num, type_of, validate
from api.generated.asgi_adapter import asgi_app
from api.generated.fastapi_adapter import include_api
from api.generated.lambda_adapter import lambda_handler, to_proxy, to_request
from model.generated import ModelValidationError, TenantError
# kybes:sql-begin
from sqlalchemy.exc import IntegrityError
# kybes:sql-end
from kybes_builders import TENANT_A

ID = {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
SPECS = [
    {"id": "getItem", "method": "GET", "path": "/items/{id}", "context": "uno", "kind": "custom", "table": None, "arg": None, "status": 200,
     "secured": True, "scopes": ["s.read"], "body": None, "bodyRequired": False,
     "params": [ID, {"name": "tag", "in": "query", "required": False, "schema": {"type": "array", "items": {"type": "string"}}},
                {"name": "n", "in": "query", "required": True, "schema": {"type": "integer", "minimum": 1}}]},
    {"id": "special", "method": "GET", "path": "/items/special", "context": "uno", "kind": "custom", "table": None, "arg": None,
     "status": 200, "secured": False, "scopes": [], "params": [], "body": None, "bodyRequired": False},
    {"id": "putItem", "method": "PUT", "path": "/items/{id}", "context": "due", "kind": "custom", "table": None, "arg": None, "status": 200,
     "secured": False, "scopes": [], "params": [ID], "bodyRequired": True,
     "body": {"type": "object", "required": ["nome"], "properties": {"nome": {"type": "string", "maxLength": 3}}, "additionalProperties": False}},
    {"id": "postOpt", "method": "POST", "path": "/opt", "context": "due", "kind": "custom", "table": None, "arg": None, "status": 204,
     "secured": False, "scopes": [], "params": [], "body": {"type": "object"}, "bodyRequired": False},
    {"id": "boom", "method": "POST", "path": "/boom", "context": "due", "kind": "custom", "table": None, "arg": None, "status": 200,
     "secured": False, "scopes": [], "params": [], "body": None, "bodyRequired": False},
]
ME = Identity(subject="kybes-test", tenant="t1", scopes=frozenset({"s.read"}))


def echo(call: Call):
    return {"op": call.operation, "path": call.path, "query": call.query, "body": call.body}


def fail(call: Call):
    raise RuntimeError("dettaglio interno da non mostrare")


def synthetic(base_path: str = "") -> Api:
    handlers = {"getItem": echo, "special": lambda call: ApiResponse(202, {"x": 1}, {"location": call.base_path + "/items/special"}),
                "putItem": echo, "postOpt": echo, "boom": fail}
    return Api(SPECS, handlers, base_path)


def req(method, path, query=None, body=None, identity=ME, headers=None):
    hs = {"content-type": "application/json", **(headers or {})}
    return ApiRequest(method, path, query or {}, hs, body, identity)


class Conflict(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.sqlstate = code


class DuplicateKeyError(Exception):
    """Stesso nome dell'errore di pymongo per una chiave duplicata."""
'''

BODIES: Dict[str, List[str]] = {
    "rt_api_validate": [
        "    cases = [",
        "        ({'type': 'string'}, 'x', None), ({'type': 'string'}, 1, 'tipo atteso: string'), ({'type': 'integer'}, 2.0, None),",
        "        ({'type': 'integer'}, 2.5, 'tipo atteso: integer'), ({'type': 'number'}, 3, None), ({'type': 'boolean'}, 1, 'tipo atteso: boolean'),",
        "        ({'type': 'string'}, None, 'nullo non ammesso'), ({'type': 'string', 'nullable': True}, None, None), ({}, None, None),",
        "        ({'enum': ['a', 'b']}, 'c', 'valore non ammesso'), ({'enum': ['a', 'b']}, 'a', None),",
        "        ({'type': 'string', 'minLength': 2}, 'a', 'lunghezza minima 2'), ({'type': 'string', 'maxLength': 2}, 'àbc', 'lunghezza massima 2'),",
        "        ({'type': 'string', 'maxLength': 2}, 'àb', None), ({'type': 'string', 'pattern': '^[0-9]+$'}, '12a', 'formato non valido'),",
        "        ({'type': 'string', 'format': 'uuid'}, 'x', 'formato uuid'), ({'type': 'string', 'format': 'date'}, '2026-02-30', 'formato date'),",
        "        ({'type': 'string', 'format': 'date-time'}, '2026-01-01T10:00:00Z', None),",
        "        ({'type': 'integer', 'minimum': 1}, 0, 'valore minimo 1'), ({'type': 'number', 'maximum': 1.5}, 2, 'valore massimo 1.5'),",
        "        ({'type': 'number', 'minimum': 1, 'maximum': 2}, 1.5, None),",
        "        ({'type': 'array', 'minItems': 1}, [], 'almeno 1 elementi'), ({'type': 'array', 'maxItems': 1}, [1, 2], 'al massimo 1 elementi'),",
        "        ({'type': 'array'}, [1], None), ({'type': 'object'}, [], 'tipo atteso: object'), ({'type': 'array'}, {}, 'tipo atteso: array'),",
        "        ({'type': 'string', 'pattern': '^[0-9]+$'}, '12\\n', 'formato non valido'), ({'type': 'string', 'pattern': '^(a|b)$|^c$'}, 'c', None),",
        "        ({'type': 'string', 'pattern': '^a\\\\$'}, 'a$', None), ({'type': 'string', 'format': 'uuid'}, '00000000-0000-4000-8000-00000000000a\\n', 'formato uuid'),",
        "    ]",
        "    for schema, value, rule in cases:",
        "        errors = {}",
        "        validate(schema, value, 'campo', errors)",
        "        assert errors == ({} if rule is None else {'campo': rule}), (schema, value)",
        "    # annidati: percorsi con punto e indice, una sola regola per campo, proprietà richieste e aggiuntive",
        "    schema = {'type': 'object', 'required': ['a', 'b'], 'properties': {'a': {'type': 'array', 'items': {'type': 'integer'}},",
        "              'o': {'type': 'object', 'properties': {'x': {'type': 'string'}}, 'additionalProperties': {'type': 'integer'}}},",
        "              'additionalProperties': False}",
        "    errors = {}",
        "    validate(schema, {'a': [1, 'x'], 'o': {'x': 1, 'y': 'z', 'w': 2}, 'k': 1}, '', errors)",
        "    assert errors == {'b': 'obbligatorio', 'a[1]': 'tipo atteso: integer', 'o.x': 'tipo atteso: string', 'o.y': 'tipo atteso: integer', 'k': 'non ammesso'}",
        "    errors = {'body': 'già presente'}",
        "    validate({'type': 'string'}, 1, '', errors)",
        "    assert errors == {'body': 'già presente'}",
        "    errors = {}",
        "    validate({'type': 'object', 'properties': {}}, {'libero': 1}, '', errors)",
        "    assert errors == {}",
        "    assert num(2.0) == '2' and num(1.5) == '1.5' and type_of(object()) == 'unknown'",
        "    for good in ('2026-01-01T00:00:00.123456789+02:00', '2026-12-31T23:59:59-05:30'):",
        "        assert check_format('date-time', good), good",
        "    for bad in ('2026-01-01 10:00:00Z', '2026-02-30T10:00:00Z', '2026-01-01T24:00:00Z', '2026-01-01T10:60:00Z',",
        "                '2026-01-01T10:00:60Z', '2026-01-01T10:00:00+24:00', '2026-01-01T10:00:00+01:60'):",
        "        assert not check_format('date-time', bad), bad",
        "    assert check_format('uuid', '00000000-0000-4000-8000-00000000000A') and check_format('date', '2024-02-29')",
        "    assert not check_format('date', '2026-1-1')",
    ],
    "rt_api_coerce": [
        "    assert coerce({'type': 'integer'}, ['-12']) == (-12, None)",
        "    assert coerce({'type': 'integer'}, ['1.5']) == (None, 'tipo atteso: integer')",
        "    assert coerce({'type': 'number'}, ['1.5e2']) == (150.0, None)",
        "    assert coerce({'type': 'number'}, ['abc']) == (None, 'tipo atteso: number')",
        "    assert coerce({'type': 'boolean'}, ['true']) == (True, None) and coerce({'type': 'boolean'}, ['false']) == (False, None)",
        "    assert coerce({'type': 'boolean'}, ['1']) == (None, 'tipo atteso: boolean')",
        "    assert coerce({'type': 'string'}, ['x']) == ('x', None)",
        "    assert coerce({'type': 'string'}, ['x', 'y']) == (None, 'un solo valore')",
        "    assert coerce({'type': 'array', 'items': {'type': 'integer'}}, ['1', '2']) == ([1, 2], None)",
        "    assert coerce({'type': 'array', 'items': {'type': 'integer'}}, ['1', 'x']) == (None, 'tipo atteso: integer')",
        "    assert coerce({'type': 'array'}, []) == ([], None)",
        "    assert coerce({'type': 'number'}, ['1e400']) == (None, 'tipo atteso: number')",
        "    assert coerce({'type': 'integer'}, ['1\\n']) == (None, 'tipo atteso: integer')",
    ],
    "rt_api_route": [
        "    api = synthetic()",
        "    r = api.handle(req('GET', '/items/special'))",
        "    assert r.status == 202 and r.body == {'x': 1}, 'il segmento fisso vince sul parametro'",
        "    assert r.headers['content-type'] == 'application/json' and r.headers['location'] == '/items/special'",
        "    r = api.handle(req('GET', '/items/%zz', {'n': ['1']}))",
        "    assert r.status == 400 and r.body['error']['fields'] == {'id': 'tipo atteso: integer'}",
        "    r = api.handle(req('GET', '/items/7', {'n': ['2'], 'tag': ['a', 'b']}))",
        "    assert r.status == 200 and r.body == {'op': 'getItem', 'path': {'id': 7}, 'query': {'n': 2, 'tag': ['a', 'b']}, 'body': None}",
        "    r = api.handle(req('GET', '/items/%37', {'n': ['1']}))",
        "    assert r.body['path'] == {'id': 7}",
        "    r = api.handle(req('GET', '/items/x', {'n': ['0'], 'altro': ['1']}))",
        "    assert r.status == 400 and r.body['error']['fields'] == {'altro': 'parametro sconosciuto', 'id': 'tipo atteso: integer', 'n': 'valore minimo 1'}",
        "    r = api.handle(req('GET', '/items/7'))",
        "    assert r.status == 400 and r.body['error']['fields'] == {'n': 'obbligatorio'}",
        "    r = api.handle(req('GET', '/nessuno'))",
        "    assert r.status == 404 and r.body['error']['code'] == 'ROUTE_NOT_FOUND'",
        "    r = api.handle(req('GET', '/items'))",
        "    assert r.status == 404",
        "    r = api.handle(req('DELETE', '/items/7'))",
        "    assert r.status == 405 and r.headers['allow'] == 'GET, PUT' and r.body['error']['code'] == 'METHOD_NOT_ALLOWED'",
        "    r = api.handle(req('GET', '/items/7', {'n': ['1']}, identity=None))",
        "    assert r.status == 401 and r.body['error']['code'] == 'IDENTITY_REQUIRED'",
        "    r = api.handle(req('GET', '/items/7', {'n': ['1']}, identity=Identity(subject='x')))",
        "    assert r.status == 403 and r.body['error']['code'] == 'SCOPE_REQUIRED'",
        "    based = synthetic('/v1/')",
        "    assert based.handle(req('GET', '/v1/items/special')).headers['location'] == '/v1/items/special'",
        "    assert based.handle(req('GET', '/v1')).status == 404",
        "    assert based.handle(req('GET', '/items/special')).status == 202",
        "    route = Route(SPECS[0], echo)",
        "    assert route.match(['items']) is None and route.match(['altro', '1']) is None and route.match(['items', '1']) == {'id': '1'}",
    ],
    "rt_api_body": [
        "    api = synthetic()",
        "    r = api.handle(req('PUT', '/items/1', body=b'{\"nome\": \"abc\"}', headers={'content-type': 'text/plain'}))",
        "    assert r.status == 415 and r.body['error']['code'] == 'JSON_REQUIRED'",
        "    r = api.handle(req('PUT', '/items/1', body=b'{\"nome\": \"abc\"}', headers={'content-type': 'Application/JSON; charset=utf-8'}))",
        "    assert r.status == 200 and r.body['body'] == {'nome': 'abc'}",
        "    for raw in (b'{', b'{\"nome\": NaN}', b'\\xff', b'{\"nome\": 1e400}', b'\\xef\\xbb\\xbf{}', '{}'.encode('utf-16')):",
        "        r = api.handle(req('PUT', '/items/1', body=raw))",
        "        assert r.status == 400 and r.body['error']['fields'] == {'body': 'JSON non valido'}, raw",
        "    r = api.handle(req('PUT', '/items/1', body=b'{\"nome\": \"abcd\", \"x\": 1}'))",
        "    assert r.status == 400 and r.body['error']['fields'] == {'nome': 'lunghezza massima 3', 'x': 'non ammesso'}",
        "    r = api.handle(req('PUT', '/items/1', body=b'[]'))",
        "    assert r.body['error']['fields'] == {'body': 'tipo atteso: object'}",
        "    r = api.handle(req('PUT', '/items/1'))",
        "    assert r.status == 400 and r.body['error']['fields'] == {'body': 'obbligatorio'}",
        "    r = api.handle(req('POST', '/opt'))",
        "    assert r.status == 204 and r.body is None",
        "    r = api.handle(req('POST', '/opt', body=b'{\"x\": 1.5}'))",
        "    assert r.status == 204",
        "    r = Api(SPECS, {**{s['id']: echo for s in SPECS}, 'boom': lambda call: ApiResponse(204)}).handle(req('POST', '/boom'))",
        "    assert r.status == 204 and 'content-type' not in r.headers",
        "    r = api.handle(req('GET', '/items/special', body=b'{}'))",
        "    assert r.status == 400 and r.body['error']['fields'] == {'body': 'corpo non ammesso'}",
    ],
    "rt_api_errors": [
        "    api = synthetic()",
        "    r = api.handle(req('POST', '/boom', headers={'x-correlation-id': 'abc-1'}))",
        "    assert r.status == 500 and r.body == error_body('INTERNAL', 'UNEXPECTED', 'abc-1') and r.headers['x-correlation-id'] == 'abc-1'",
        "    assert 'dettaglio' not in json.dumps(r.body)",
        "    r = api.handle(req('POST', '/boom', headers={'x-correlation-id': 'non valido!'}))",
        "    assert r.headers['x-correlation-id'] != 'non valido!' and uuid.UUID(r.headers['x-correlation-id'])",
        "    assert error_body('VALIDATION', 'X', 'c', {'a': 'b'}) == {'error': {'code': 'X', 'message': 'Richiesta non valida', 'correlationId': 'c', 'fields': {'a': 'b'}}}",
        "    same = ApiError('CONFLICT', 'MIO')",
        "    assert map_error(same) is same and ApiError('NOT_FOUND', 'X').fields == {}",
        "    e = map_error(ModelValidationError('T', {'limit': 'tra 1 e 100'}))",
        "    assert (e.kind, e.code, e.fields) == ('VALIDATION', 'INVALID_PAGE', {'limit': 'tra 1 e 100'})",
        "    e = map_error(ModelValidationError('T', {'Righe': 'record collegati'}))",
        "    assert (e.kind, e.code) == ('CONFLICT', 'RELATED_RECORDS')",
        "    e = map_error(ModelValidationError('T', {'Nome': 'obbligatorio'}))",
        "    assert (e.kind, e.code) == ('UNPROCESSABLE', 'MODEL_RULE')",
        "    assert map_error(ModelValidationError('T', {})).kind == 'UNPROCESSABLE'",
        "    assert map_error(TenantError('x')).code == 'TENANT_REQUIRED'",
        "    assert map_error(DuplicateKeyError('x')).code == 'DUPLICATE'",
        "    assert map_error(ValueError('x')).code == 'UNEXPECTED'",
        "    # kybes:sql-begin",
        "    assert map_error(IntegrityError('stmt', {}, Exception('x'))).code == 'CONSTRAINT'",
        "    assert map_error(Conflict('40001')).code == 'RETRY_LATER'",
        "    # kybes:sql-end",
        "    # gli errori di modello, conflitto e validazione mostrano i campi; gli altri no",
        "    handlers = {'getItem': echo, 'special': echo, 'putItem': echo, 'postOpt': echo,",
        "                'boom': lambda call: (_ for _ in ()).throw(ModelValidationError('T', {'Nome': 'obbligatorio'}))}",
        "    r = Api(SPECS, handlers).handle(req('POST', '/boom'))",
        "    assert r.status == 422 and r.body['error']['fields'] == {'Nome': 'obbligatorio'}",
        "    handlers['boom'] = lambda call: (_ for _ in ()).throw(TenantError('x'))",
        "    r = Api(SPECS, handlers).handle(req('POST', '/boom'))",
        "    assert r.status == 403 and 'fields' not in r.body['error']",
    ],
    "rt_api_identity": [
        "    assert list(scopes_of(None)) == [] and list(scopes_of(['a', 1])) == ['a', '1']",
        "    assert list(scopes_of('[a b]')) == ['a', 'b'] and list(scopes_of('a,b c')) == ['a', 'b', 'c']",
        "    sub, ten, scp = CLAIMS['subject'], CLAIMS['tenant'], CLAIMS['scopes'][0]",
        "    i = from_claims({sub: 'u1', ten: 't1', scp: 'a b'})",
        "    assert (i.subject, i.tenant, i.scopes) == ('u1', 't1', frozenset({'a', 'b'}))",
        "    i = from_claims({sub: '', ten: None})",
        "    assert i.subject is None and i.tenant is None and i.scopes == frozenset()",
        "    assert from_lambda({}) is None and from_lambda({'requestContext': {'authorizer': 'x'}}) is None",
        "    assert from_lambda({'requestContext': {'authorizer': {'jwt': {'claims': {sub: 'a'}}}}}).subject == 'a'",
        "    assert from_lambda({'requestContext': {'authorizer': {'lambda': {sub: 'b'}}}}).subject == 'b'",
        "    assert from_lambda({'requestContext': {'authorizer': {'claims': {sub: 'c'}}}}).subject == 'c'",
        "    assert from_lambda({'requestContext': {'authorizer': {sub: 'd'}}}).subject == 'd'",
        "    assert from_lambda({'requestContext': {'authorizer': {'claims': json.dumps({sub: 'e'})}}}).subject == 'e'",
        "    assert from_headers({}) is None",
        "    i = from_headers({HEADERS['subject']: 'u', HEADERS['tenant']: 't', HEADERS['scopes']: 'x y'})",
        "    assert (i.subject, i.tenant, i.scopes) == ('u', 't', frozenset({'x', 'y'}))",
        "    assert from_headers({HEADERS['subject']: 'u'}).tenant is None",
        "    assert Call('x', {}, {}, None, Identity(tenant='t'), 'c').tenant == 't'",
    ],
    "rt_api_lambda": [
        "    handler = lambda_handler(synthetic())",
        "    v2 = {'version': '2.0', 'rawPath': '/items/7', 'rawQueryString': 'n=2&tag=a&tag=b', 'headers': {'Content-Type': 'application/json'},",
        "          'requestContext': {'http': {'method': 'GET'}, 'authorizer': {'jwt': {'claims': {CLAIMS['subject']: 'u', CLAIMS['scopes'][0]: 's.read'}}}}}",
        "    out = handler(v2, None)",
        "    assert out['statusCode'] == 200 and out['isBase64Encoded'] is False",
        "    assert json.loads(out['body'])['query'] == {'n': 2, 'tag': ['a', 'b']} and out['headers']['content-type'] == 'application/json'",
        "    put = {'httpMethod': 'PUT', 'path': '/items/1', 'headers': {'content-type': 'application/json'},",
        "           'body': base64.b64encode(b'{\"nome\": \"ab\"}').decode(), 'isBase64Encoded': True, 'requestContext': {}}",
        "    assert json.loads(handler(put)['body'])['body'] == {'nome': 'ab'}",
        "    v1 = {'httpMethod': 'GET', 'path': '/items/7', 'multiValueQueryStringParameters': {'n': ['3']}, 'queryStringParameters': {'n': '3'},",
        "          'requestContext': {'authorizer': {'claims': {CLAIMS['subject']: 'u', CLAIMS['scopes'][0]: 's.read'}}}}",
        "    assert json.loads(handler(v1)['body'])['query'] == {'n': 3}",
        "    single = to_request({'httpMethod': 'POST', 'queryStringParameters': {'a': '1'}, 'body': '{}'})",
        "    assert single.query == {'a': ['1']} and single.path == '/' and single.body == b'{}' and single.identity is None",
        "    assert to_request({'version': '2.0', 'requestContext': {'http': {'method': 'GET'}}}).path == '/'",
        "    assert to_proxy(ApiResponse(204)) == {'statusCode': 204, 'headers': {}, 'isBase64Encoded': False, 'body': ''}",
    ],
    "rt_api_http": [
        "    app = asgi_app(synthetic())",
        "    sent = []",
        "",
        "    async def send(msg):",
        "        sent.append(msg)",
        "",
        "    def receiver(messages):",
        "        it = iter(messages)",
        "",
        "        async def receive():",
        "            return next(it)",
        "        return receive",
        "",
        "    asyncio.run(app({'type': 'lifespan'}, receiver([{'type': 'lifespan.startup'}, {'type': 'lifespan.shutdown'}]), send))",
        "    assert [m['type'] for m in sent] == ['lifespan.startup.complete', 'lifespan.shutdown.complete']",
        "    sent.clear()",
        "    scope = {'type': 'http', 'method': 'PUT', 'path': '/items/4', 'query_string': b'',",
        "             'headers': [(b'content-type', b'application/json'), (HEADERS['subject'].encode(), b'u')]}",
        "    asyncio.run(app(scope, receiver([{'body': b'{\"nome\":', 'more_body': True}, {'body': b' \"x\"}'}]), send))",
        "    assert sent[0]['status'] == 200 and json.loads(sent[1]['body'])['body'] == {'nome': 'x'}",
        "    sent.clear()",
        "    asyncio.run(app({'type': 'http', 'method': 'POST', 'path': '/opt'}, receiver([{'type': 'http.request'}]), send))",
        "    assert sent[0]['status'] == 204 and sent[1]['body'] == b''",
        "    sent.clear()",
        "    scope = {'type': 'http', 'method': 'GET', 'path': '/items/a/b', 'raw_path': b'/items/a%2Fb', 'query_string': b''}",
        "    asyncio.run(app(scope, receiver([{'type': 'http.request'}]), send))",
        "    assert sent[0]['status'] == 401, 'a%2Fb resta un solo segmento: il percorso grezzo si decodifica una volta'",
    ],
    "rt_api_framework": [
        "    pytest.importorskip('httpx')",
        "    from fastapi import FastAPI",
        "    from fastapi.testclient import TestClient",
        "    app = include_api(FastAPI(), synthetic())",
        "    assert {r.operation_id for r in app.routes if getattr(r, 'operation_id', None)} == {'getItem', 'special', 'putItem', 'postOpt', 'boom'}",
        "    client = TestClient(app)",
        "    r = client.get('/items/7?n=1&tag=a&tag=b', headers={HEADERS['subject']: 'u', HEADERS['scopes']: 's.read'})",
        "    assert r.status_code == 200 and r.json()['query'] == {'n': 1, 'tag': ['a', 'b']}",
        "    r = client.put('/items/7', content=b'{\"nome\": \"x\"}', headers={'content-type': 'application/json'})",
        "    assert r.status_code == 200 and r.json()['body'] == {'nome': 'x'}",
        "    r = client.delete('/items/7')",
        "    assert r.status_code == 405 and r.json()['error']['code'] == 'METHOD_NOT_ALLOWED'",
        "    r = client.get('/nessuno')",
        "    assert r.status_code == 404 and r.json()['error']['code'] == 'ROUTE_NOT_FOUND'",
        "    assert client.post('/opt').status_code == 204",
    ],
    "rt_api_convert": [
        "    for f in (to_uuid, to_int, to_decimal, to_date, to_datetime, text, date_text, datetime_text):",
        "        assert f(None) is None",
        "    assert decimal_text(None, 2) is None and decimal_text(Decimal('1.5'), 2) == '1.50' and decimal_text(3, 0) == '3'",
        "    assert decimal_text(Decimal('-7.129'), 2) == '-7.12' and decimal_text(Decimal('-0.001'), 2) == '0.00'",
        "    assert to_uuid('00000000-0000-4000-8000-00000000000A') == uuid.UUID('00000000-0000-4000-8000-00000000000a')",
        "    assert to_int('9007199254740993') == 9007199254740993 and to_decimal('12.30') == Decimal('12.30')",
        "    assert to_date('2026-02-03') == date(2026, 2, 3) and date_text(date(2026, 2, 3)) == '2026-02-03'",
        "    utc = datetime(2026, 2, 3, 4, 5, 6, 123000, tzinfo=timezone.utc)",
        "    assert to_datetime('2026-02-03T04:05:06.123456789Z') == utc, 'al millisecondo, come negli altri linguaggi'",
        "    assert to_datetime('2026-02-03T06:05:06.123456+02:00') == utc",
        "    assert to_datetime('2026-02-02T22:35:06.12-05:30') == utc - timedelta(milliseconds=3)",
        "    assert to_datetime('2026-02-03T04:05:06Z') == utc.replace(microsecond=0)",
        "    assert datetime_text(utc) == '2026-02-03T04:05:06.123Z'",
        "    assert datetime_text(utc.astimezone(timezone(timedelta(hours=2)))) == '2026-02-03T04:05:06.123Z'",
        "    assert datetime_text(datetime(2026, 2, 3, 4, 5, 6)) == '2026-02-03T04:05:06.000Z'",
        "    assert text(uuid.UUID(int=1)) == '00000000-0000-0000-0000-000000000001' and text(7) == '7'",
    ],
}


def _custom_body(ops: List[Operation]) -> List[str]:
    custom = [o for o in ops if o.kind == "custom"]
    o = ["    # filtro per contesto: solo le operazioni scelte (nessuna: ogni percorso dà 404)",
         "    empty = build_api(ApiData(), None, contexts=[])", "    assert empty.routes == []",
         "    assert empty.handle(req('GET', '/qualsiasi')).status == 404"]
    if custom:
        first = custom[0]
        o += [f"    with pytest.raises(TypeError, match={first.op_id!r}):", "        build_api(ApiData(), object())",
              ]
        free = [x.context for x in ops if x.kind != "custom" and x.context not in {c.context for c in custom}]
        if free:
            o += [f"    only = build_api(ApiData(), object(), contexts=[{free[0]!r}])",
                  f"    assert {{r.spec['context'] for r in only.routes}} == {{{free[0]!r}}}"]
    o += ["    full = build_api(ApiData(), type('Tutti', (), {'__getattr__': lambda self, name: (lambda call: None)})())",
          f"    assert len(full.routes) == {len(ops)}"]
    return o


def _data_body(tables: Dict[str, Table]) -> List[str]:
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    o = []
    if sql:
        o += ["    with pytest.raises(RuntimeError):", "        with ApiData().read(None):", "            pass",
              "    data = ApiData(sql_for=lambda tenant: session_factory, levels=isolation_levels)",
              "    with data.read(None) as s:", "        assert s is not None",
              "    with data.read(str(TENANT_A)) as s:", "        from model.generated import tenant_of",
              "        assert str(tenant_of(s)) == str(TENANT_A)",
              "    assert data.write([], None, lambda s: 5) == 5"]
    if mongo:
        o += ["    with pytest.raises(RuntimeError):", "        with ApiData().mongo_read(None):", "            pass",
              "    data = ApiData(mongo_client=mongo_client, mongo_database_for=lambda tenant: mongo_db.name)",
              "    with data.mongo_read(None) as ms:", "        assert ms.db.name == mongo_db.name",
              "    plain = ApiData(mongo_client=mongo_client, mongo_database=mongo_db.name)",
              "    assert plain.mongo_write(None, lambda ms: ms.db.name) == mongo_db.name"]
    return o


def render(cat: Catalog, tables: Dict[str, Table], ops: List[Operation], asil: str) -> str:
    sql, mongo = has_sql(tables), any(t.mongo for t in tables.values())
    fx = (["session_factory", "isolation_levels"] if sql else []) + (["mongo_client", "mongo_db"] if mongo else [])
    bodies = dict(BODIES)
    bodies["rt_api_custom"] = _custom_body(ops) + _data_body(tables)
    o = [header("python", "kit").rstrip("\n") + "\n" + strip_sql(HEAD, sql)]
    for tc in cat.for_table(API_RT, "api"):
        args = ", ".join(fx) if tc.kind == "rt_api_custom" else ""
        o += ["", f"def test_{tc.slug}({args}):", f'    r"""{tc.id} · {", ".join(tc.reqs)} · {METHODS[tc.method]}: {tc.title}. Atteso: {tc.expected}."""']
        o += [x for x in strip_sql("\n".join(bodies[tc.kind]), sql).split("\n")]
        o.append("")
    return "\n".join(o).rstrip("\n") + "\n"
