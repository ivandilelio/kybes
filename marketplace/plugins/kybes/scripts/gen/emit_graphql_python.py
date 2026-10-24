"""Emettitore GraphQL Python (Strawberry): tipi, resolver, DataLoader, app ASGI."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import graphql_plan as gql
from api_plan import prop
from naming import header, member, method_name, repo_class
from schema import Table, camel, snake
from sqlonly import has_sql

L = "python"


def _py_type(gql_type: str, nullable: bool) -> str:
    m = {"ID": "strawberry.ID", "String": "str", "Int": "int", "Boolean": "bool",
         "Date": "date", "DateTime": "datetime", "JSON": "strawberry.scalars.JSON"}
    base = m.get(gql_type, gql_type)
    return f"Optional[{base}]" if nullable else base


def _to_json(c, expr: str) -> str:
    if c.type == "uuid":
        return f"str({expr})" if not c.nullable else f"str({expr}) if {expr} is not None else None"
    if c.type in ("bigint", "decimal"):
        return f"str({expr})" if not c.nullable else f"str({expr}) if {expr} is not None else None"
    if c.type == "date":
        return expr
    if c.type == "datetime":
        return expr
    return expr


def _types_file(tables: Dict[str, Table], schema: gql.GqlSchema) -> str:
    lines = [
        'from __future__ import annotations',
        '',
        'from datetime import date, datetime',
        'from typing import List, Optional',
        '',
        'import strawberry',
        'from strawberry import relay',
        '',
        '',
        '@strawberry.type',
        'class PageInfo:',
        '    has_next_page: bool',
        '    has_previous_page: bool',
        '    start_cursor: Optional[str] = None',
        '    end_cursor: Optional[str] = None',
        '',
    ]

    for gt in schema.types:
        t = tables[gt.table]
        lines += [
            '',
            f'@strawberry.type(description={gt.description!r})',
            f'class {gt.name}Type:',
        ]
        for f in gt.fields:
            if f.is_relation:
                continue
            pt = _py_type(f.gql_type, f.nullable)
            lines.append(f'    {snake(f.name)}: {pt}')
        lines.append('')

        lines += [
            '',
            f'@strawberry.type',
            f'class {gt.name}Edge:',
            '    cursor: str',
            f'    node: {gt.name}Type',
            '',
            '',
            f'@strawberry.type',
            f'class {gt.name}Connection:',
            f'    edges: List[{gt.name}Edge]',
            '    page_info: PageInfo',
            '    total_count: Optional[int] = None',
            '',
        ]

    for inp in schema.inputs:
        lines += [
            '',
            f'@strawberry.input',
            f'class {inp.name}:',
        ]
        for f in inp.fields:
            pt = _py_type(f.gql_type, not f.required)
            if not f.required:
                lines.append(f'    {snake(f.name)}: {pt} = strawberry.UNSET')
            else:
                lines.append(f'    {snake(f.name)}: {pt}')
        lines.append('')

    return '\n'.join(lines) + '\n'


def _dataloaders_file(tables: Dict[str, Table], schema: gql.GqlSchema) -> str:
    lines = [
        'from __future__ import annotations',
        '',
        'from typing import Any, Dict, List, Optional',
        '',
        'from strawberry.dataloader import DataLoader',
        '',
        '',
        'class Loaders:',
        '    """DataLoader per sessione: crea un\'istanza per request."""',
        '',
        '    def __init__(self, session_factory):',
        '        self._sf = session_factory',
    ]

    for gt in schema.types:
        t = tables[gt.table]
        for f in gt.fields:
            if not f.is_relation or f.is_connection:
                continue
            if f.relation_kind != "many_to_one":
                continue
            loader_name = f'{snake(gt.table)}_{snake(f.name)}_loader'
            target = f.relation_target
            fk = f.column_name
            lines += [
                f'        self.{loader_name} = DataLoader(load_fn=self._load_{snake(gt.table)}_{snake(f.name)})',
            ]

    lines += ['', '    # --- batch load functions ---', '']

    for gt in schema.types:
        t = tables[gt.table]
        for f in gt.fields:
            if not f.is_relation or f.is_connection:
                continue
            if f.relation_kind != "many_to_one":
                continue
            target = f.relation_target
            fk = f.column_name
            fn_name = f'_load_{snake(gt.table)}_{snake(f.name)}'
            lines += [
                f'    async def {fn_name}(self, keys: List[Any]) -> List[Optional[Any]]:',
                f'        from {snake(target)} import {repo_class(L, target)}',
                f'        repo = {repo_class(L, target)}(self._sf())',
                f'        results: Dict[Any, Any] = {{}}',
                f'        for k in set(keys):',
                f'            if k is not None:',
                f'                obj = repo.get_by_id(k)',
                f'                if obj is not None:',
                f'                    results[k] = obj',
                f'        return [results.get(k) for k in keys]',
                '',
            ]

    return '\n'.join(lines) + '\n'


def _to_type_expr(t: Table, var: str) -> str:
    fields = []
    for c in t.columns:
        if c.tenant:
            continue
        src = f'{var}.{member(L, c.name)}'
        val = _to_json(c, src)
        fields.append(f'{snake(c.name)}={val}')
    return ', '.join(fields)


def _resolvers_file(tables: Dict[str, Table], schema: gql.GqlSchema) -> str:
    lines = [
        'from __future__ import annotations',
        '',
        'from typing import List, Optional',
        '',
        'import strawberry',
        '',
        'from .types import *',
        'from .dataloaders import Loaders',
        '',
        '',
        'def _check_auth(info, secured: bool = False, scopes: list = None, roles: list = None):',
        '    identity = info.context.get("identity")',
        '    if secured and (identity is None or not getattr(identity, "subject", None)):',
        '        raise PermissionError("IDENTITY_REQUIRED")',
        '    if scopes and (identity is None or not set(scopes).issubset(getattr(identity, "scopes", set()))):',
        '        raise PermissionError("SCOPE_REQUIRED")',
        '    if roles and (identity is None or not (set(roles) & getattr(identity, "scopes", set()))):',
        '        raise PermissionError("ROLE_REQUIRED")',
        '',
        '',
    ]

    resolve_fns = []
    for gt in schema.types:
        t = tables[gt.table]
        n = gt.table
        for f in gt.fields:
            if not f.is_relation:
                continue
            if f.relation_kind == "many_to_one":
                fn = f'resolve_{snake(n)}_{snake(f.name)}'
                resolve_fns.append(fn)
                target = f.relation_target
                tt = tables[target]
                lines += [
                    f'async def {fn}(parent: {n}Type, info) -> Optional[{target}Type]:',
                    f'    loaders: Loaders = info.context["loaders"]',
                    f'    fk = parent.{snake(f.column_name)}',
                    f'    if fk is None:',
                    f'        return None',
                    f'    obj = await loaders.{snake(n)}_{snake(f.name)}_loader.load(fk)',
                    f'    if obj is None:',
                    f'        return None',
                    f'    return {target}Type({_to_type_expr(tt, "obj")})',
                    '',
                    '',
                ]

    # Connection helper
    lines += [
        'def _to_connection(items, cursor, has_next, total=None):',
        '    """Converte una pagina del repository in una Connection Relay."""',
        '    edges = []',
        '    for i, item in enumerate(items):',
        '        c = cursor + str(i) if cursor else str(i)',
        '        edges.append(type(item).__name__.replace("Type", "") + "Edge")',
        '    # usa la funzione specifica per ogni tipo',
        '    return items, cursor, has_next, total',
        '',
        '',
    ]

    lines.append('@strawberry.type')
    lines.append('class Query:')
    for q in schema.queries:
        t = tables[q.table]
        n = q.table
        args_def = ', '.join(
            f'{snake(a.name)}: {_py_type(a.gql_type, not a.required)} = None'
            if not a.required else f'{snake(a.name)}: {_py_type(a.gql_type, False)}'
            for a in q.args
        )
        if args_def:
            args_def = ', ' + args_def

        secured = tables[q.table].api.secured
        auth_call = f'        _check_auth(info, secured={secured}, scopes={q.scopes!r}, roles={q.roles!r})'

        if q.kind == "get":
            lines += [
                f'    @strawberry.field(description={q.description!r})',
                f'    def {snake(q.name)}(self, info{args_def}) -> Optional[{n}Type]:',
                auth_call,
                f'        session = info.context["session_factory"]()',
                f'        from {snake(n)} import {repo_class(L, n)}',
                f'        repo = {repo_class(L, n)}(session)',
                f'        obj = repo.{method_name(L, "get_by_id")}(id)',
                f'        if obj is None:',
                f'            return None',
                f'        return {n}Type({_to_type_expr(t, "obj")})',
                '',
            ]
        elif q.kind == "list":
            limit_expr = f'first if first is not None else {t.pagination.default_limit}'
            lines += [
                f'    @strawberry.field(description={q.description!r})',
                f'    def {snake(q.name)}(self, info{args_def}) -> {n}Connection:',
                auth_call,
                f'        session = info.context["session_factory"]()',
                f'        from {snake(n)} import {repo_class(L, n)}',
                f'        repo = {repo_class(L, n)}(session)',
                f'        page = repo.{method_name(L, "list_page")}(limit={limit_expr}, cursor=after, sort=sort)',
                f'        edges = [{n}Edge(cursor=page.next_cursor or "", node={n}Type({_to_type_expr(t, "r")})) for r in page.items]',
                f'        pi = PageInfo(has_next_page=page.next_cursor is not None, has_previous_page=after is not None,',
                f'                      start_cursor=edges[0].cursor if edges else None, end_cursor=edges[-1].cursor if edges else None)',
                f'        return {n}Connection(edges=edges, page_info=pi)',
                '',
            ]
        elif q.kind == "query":
            qobj = next(x for x in t.queries if x.name == q.arg)
            mk = {"page": "query_page", "list": "query_list", "one": "query_one"}[qobj.returns]
            mname = method_name(L, f"{mk}:{q.arg}")
            repo_args = ', '.join(snake(c.param) for c in qobj.where if c.param)
            if q.is_connection:
                if repo_args:
                    repo_args += f', limit=first if first is not None else {t.pagination.default_limit}, cursor=after'
                else:
                    repo_args = f'limit=first if first is not None else {t.pagination.default_limit}, cursor=after'
                lines += [
                    f'    @strawberry.field(description={q.description!r})',
                    f'    def {snake(q.name)}(self, info{args_def}) -> {n}Connection:',
                    auth_call,
                    f'        session = info.context["session_factory"]()',
                    f'        from {snake(n)} import {repo_class(L, n)}',
                    f'        repo = {repo_class(L, n)}(session)',
                    f'        page = repo.{mname}({repo_args})',
                    f'        edges = [{n}Edge(cursor=page.next_cursor or "", node={n}Type({_to_type_expr(t, "r")})) for r in page.items]',
                    f'        pi = PageInfo(has_next_page=page.next_cursor is not None, has_previous_page=False)',
                    f'        return {n}Connection(edges=edges, page_info=pi)',
                    '',
                ]
            elif qobj.returns == "list":
                lines += [
                    f'    @strawberry.field(description={q.description!r})',
                    f'    def {snake(q.name)}(self, info{args_def}) -> List[{n}Type]:',
                    auth_call,
                    f'        session = info.context["session_factory"]()',
                    f'        from {snake(n)} import {repo_class(L, n)}',
                    f'        repo = {repo_class(L, n)}(session)',
                    f'        return [{n}Type({_to_type_expr(t, "r")}) for r in repo.{mname}({repo_args})]',
                    '',
                ]
            else:
                lines += [
                    f'    @strawberry.field(description={q.description!r})',
                    f'    def {snake(q.name)}(self, info{args_def}) -> Optional[{n}Type]:',
                    auth_call,
                    f'        session = info.context["session_factory"]()',
                    f'        from {snake(n)} import {repo_class(L, n)}',
                    f'        repo = {repo_class(L, n)}(session)',
                    f'        obj = repo.{mname}({repo_args})',
                    f'        if obj is None:',
                    f'            return None',
                    f'        return {n}Type({_to_type_expr(t, "obj")})',
                    '',
                ]

    lines.append('')
    lines.append('')

    if schema.mutations:
        lines.append('@strawberry.type')
        lines.append('class Mutation:')
        for m in schema.mutations:
            t = tables[m.table]
            n = m.table
            secured = tables[m.table].api.secured
            m_auth = f'        _check_auth(info, secured={secured}, scopes={m.scopes!r}, roles={m.roles!r})'
            args_def = ', '.join(
                f'{snake(a.name)}: {a.gql_type}' if a.gql_type.startswith('Create') or a.gql_type.startswith('Update')
                else f'{snake(a.name)}: {_py_type(a.gql_type, not a.required)}'
                for a in m.args
            )
            if args_def:
                args_def = ', ' + args_def

            if m.kind == "create":
                assign = []
                for c in t.columns:
                    if c.tenant or (c.primary_key and c.auto) or c.generated:
                        continue
                    sn = snake(c.name)
                    assign.append(f'{member(L, c.name)}=input.{sn}')
                lines += [
                    f'    @strawberry.mutation(description={m.description!r})',
                    f'    def {snake(m.name)}(self, info{args_def}) -> {n}Type:',
                    m_auth,
                    f'        session = info.context["session_factory"]()',
                    f'        from {snake(n)} import {repo_class(L, n)}',
                    f'        repo = {repo_class(L, n)}(session)',
                    f'        obj = repo.{method_name(L, "create")}({", ".join(assign)})',
                    f'        return {n}Type({_to_type_expr(t, "obj")})',
                    '',
                ]
            elif m.kind == "update":
                lines += [
                    f'    @strawberry.mutation(description={m.description!r})',
                    f'    def {snake(m.name)}(self, info{args_def}) -> {n}Type:',
                    m_auth,
                    f'        session = info.context["session_factory"]()',
                    f'        from {snake(n)} import {repo_class(L, n)}',
                    f'        repo = {repo_class(L, n)}(session)',
                    f'        changes = {{k: v for k, v in vars(input).items() if v is not strawberry.UNSET}}',
                    f'        obj = repo.{method_name(L, "update")}(id, **changes)',
                    f'        return {n}Type({_to_type_expr(t, "obj")})',
                    '',
                ]
            elif m.kind == "delete":
                lines += [
                    f'    @strawberry.mutation(description={m.description!r})',
                    f'    def {snake(m.name)}(self, info{args_def}) -> bool:',
                    m_auth,
                    f'        session = info.context["session_factory"]()',
                    f'        from {snake(n)} import {repo_class(L, n)}',
                    f'        repo = {repo_class(L, n)}(session)',
                    f'        repo.{method_name(L, "delete")}(id)',
                    f'        return True',
                    '',
                ]

    return '\n'.join(lines) + '\n'


def _app_file(schema: gql.GqlSchema) -> str:
    has_mutation = bool(schema.mutations)
    lines = [
        'from __future__ import annotations',
        '',
        'import strawberry',
        'from strawberry.asgi import GraphQL',
        '',
        'from .resolvers import Query' + (', Mutation' if has_mutation else ''),
        'from .dataloaders import Loaders',
        '',
        '',
        'def create_schema():',
        '    return strawberry.Schema(',
        '        query=Query,',
    ]
    if has_mutation:
        lines.append('        mutation=Mutation,')
    lines += [
        '    )',
        '',
        '',
        'def create_app(session_factory):',
        '    """App ASGI con context che inietta la sessione e i DataLoader."""',
        '    schema = create_schema()',
        '',
        '    async def get_context():',
        '        return {"session_factory": session_factory, "loaders": Loaders(session_factory)}',
        '',
        '    return GraphQL(schema, context_getter=get_context)',
        '',
    ]
    return '\n'.join(lines) + '\n'


def emit(tables: Dict[str, Table], schema: gql.GqlSchema, opts: Dict):
    h = header(L, "schemas/db/*.yaml")
    files = {}
    files['generated/types.py'] = h + _types_file(tables, schema)
    files['generated/dataloaders.py'] = h + _dataloaders_file(tables, schema)
    files['generated/resolvers.py'] = h + _resolvers_file(tables, schema)
    files['generated/app.py'] = h + _app_file(schema)
    files['generated/__init__.py'] = (h + '"""Pacchetto GraphQL generato: tipi Strawberry, resolver, DataLoader e app ASGI."""\n'
                                      'from .app import create_app, create_schema\n')
    files['__init__.py'] = (h.rstrip('\n') + '\n'
                            '"""Pacchetto GraphQL: Strawberry types, resolver e app ASGI (vedi schemas/generated/schema.graphql)."""\n')
    return files
