"""Emettitore GraphQL TypeScript (type-graphql + graphql-yoga): tipi, resolver, DataLoader, server."""
from __future__ import annotations

from typing import Dict, List

import graphql_plan as gql
from naming import header, member, method_name, repo_class
from schema import Table, camel, snake

L = "typescript"

TS_MAP = {"ID": "string", "String": "string", "Int": "number", "Boolean": "boolean",
          "Date": "string", "DateTime": "string", "JSON": "any"}

GQL_DECORATOR_MAP = {"ID": "() => ID", "String": "() => String", "Int": "() => Int",
                     "Boolean": "() => Boolean", "Date": "() => String", "DateTime": "() => String",
                     "JSON": "() => GraphQLJSON"}


def _ts_type(gql_type: str, nullable: bool) -> str:
    base = TS_MAP.get(gql_type, gql_type + "Type")
    return f"{base} | null" if nullable else base


def _field_dec(gql_type: str, nullable: bool) -> str:
    base = GQL_DECORATOR_MAP.get(gql_type, f"() => {gql_type}Type")
    opts = ", { nullable: true }" if nullable else ""
    return f"@Field({base}{opts})"


def _types_file(tables: Dict[str, Table], schema: gql.GqlSchema) -> str:
    lines = [
        'import { ObjectType, Field, ID, Int } from "type-graphql";',
        'import GraphQLJSON from "graphql-type-json";',
        '',
    ]

    lines += [
        '@ObjectType()',
        'export class PageInfo {',
        '  @Field() hasNextPage!: boolean;',
        '  @Field() hasPreviousPage!: boolean;',
        '  @Field(() => String, { nullable: true }) startCursor!: string | null;',
        '  @Field(() => String, { nullable: true }) endCursor!: string | null;',
        '}',
        '',
    ]

    for gt in schema.types:
        desc = f'@ObjectType({{ description: {gt.description!r} }})' if gt.description else '@ObjectType()'
        lines.append(desc)
        lines.append(f'export class {gt.name}Type {{')
        for f in gt.fields:
            if f.is_relation:
                continue
            dec = _field_dec(f.gql_type, f.nullable)
            ts = _ts_type(f.gql_type, f.nullable)
            lines.append(f'  {dec} {camel(f.name)}!: {ts};')
        lines += ['}', '']

        lines += [
            f'@ObjectType()',
            f'export class {gt.name}Edge {{',
            f'  @Field() cursor!: string;',
            f'  @Field(() => {gt.name}Type) node!: {gt.name}Type;',
            '}',
            '',
            f'@ObjectType()',
            f'export class {gt.name}Connection {{',
            f'  @Field(() => [{gt.name}Edge]) edges!: {gt.name}Edge[];',
            f'  @Field(() => PageInfo) pageInfo!: PageInfo;',
            f'  @Field(() => Int, {{ nullable: true }}) totalCount?: number | null;',
            '}',
            '',
        ]

    return '\n'.join(lines) + '\n'


def _inputs_file(schema: gql.GqlSchema) -> str:
    lines = [
        'import { InputType, Field, ID, Int } from "type-graphql";',
        'import GraphQLJSON from "graphql-type-json";',
        '',
    ]

    for inp in schema.inputs:
        lines.append('@InputType()')
        lines.append(f'export class {inp.name} {{')
        for f in inp.fields:
            dec = _field_dec(f.gql_type, not f.required)
            ts = _ts_type(f.gql_type, not f.required)
            lines.append(f'  {dec} {camel(f.name)}{"?" if not f.required else ""}!: {ts};')
        lines += ['}', '']

    return '\n'.join(lines) + '\n'


def _dataloaders_file(tables: Dict[str, Table], schema: gql.GqlSchema) -> str:
    lines = [
        'import DataLoader from "dataloader";',
        '',
        'export interface LoaderContext { sessionFactory: () => any; }',
        '',
        'export class Loaders {',
        '  private ctx: LoaderContext;',
        '',
    ]

    loader_fields: list[str] = []
    loader_inits: list[str] = []
    batch_methods: list[str] = []

    for gt in schema.types:
        t = tables[gt.table]
        for f in gt.fields:
            if not f.is_relation or f.is_connection or f.relation_kind != "many_to_one":
                continue
            prop_name = f'{camel(gt.table)}{f.relation_target}Loader'
            target = f.relation_target
            loader_fields.append(f'  {prop_name}: DataLoader<any, any>;')
            loader_inits.append(f'    this.{prop_name} = new DataLoader((keys) => this.batch{gt.table}{f.relation_target}(keys));')
            repo = repo_class(L, target)
            mname = method_name(L, "get_by_id")
            batch_methods += [
                f'  private async batch{gt.table}{f.relation_target}(keys: readonly any[]): Promise<any[]> {{',
                f'    const session = this.ctx.sessionFactory();',
                f'    const repo = new (require("./../{target}").{repo})(session);',
                f'    const map = new Map<any, any>();',
                f'    for (const k of new Set(keys)) {{',
                f'      if (k != null) {{ const obj = repo.{mname}(k); if (obj) map.set(k, obj); }}',
                f'    }}',
                f'    return keys.map((k) => map.get(k) ?? null);',
                f'  }}',
                '',
            ]

    for lf in loader_fields:
        lines.append(lf)
    lines += ['', '  constructor(ctx: LoaderContext) {', '    this.ctx = ctx;']
    for li in loader_inits:
        lines.append(li)
    lines += ['  }', '']
    lines += batch_methods
    lines += ['}', '']

    return '\n'.join(lines) + '\n'


def _to_type_expr(t: Table, var: str) -> str:
    assigns = []
    for c in t.columns:
        if c.tenant:
            continue
        m = member(L, c.name)
        src = f'{var}.{m}'
        if c.type in ("uuid", "bigint", "decimal"):
            val = f'String({src})' if not c.nullable else f'{src} != null ? String({src}) : null'
        else:
            val = src
        assigns.append(f'{m}: {val}')
    return ', '.join(assigns)


def _resolvers_file(tables: Dict[str, Table], schema: gql.GqlSchema) -> str:
    type_imports = ', '.join(
        f'{gt.name}Type, {gt.name}Connection, {gt.name}Edge, PageInfo'
        for gt in schema.types
    )
    input_imports = ', '.join(inp.name for inp in schema.inputs)

    lines = [
        'import { Resolver, Query, Mutation, Arg, Ctx, Int } from "type-graphql";',
        f'import {{ {type_imports} }} from "./types";',
    ]
    if input_imports:
        lines.append(f'import {{ {input_imports} }} from "./inputs";')
    lines += [
        'import { Loaders } from "./dataloaders";',
        '',
        'interface GqlContext { sessionFactory: () => any; loaders: Loaders; }',
        '',
    ]

    lines.append('@Resolver()')
    lines.append('export class QueryResolver {')

    for q in schema.queries:
        t = tables[q.table]
        n = q.table
        mname_get = method_name(L, "get_by_id")
        mname_list = method_name(L, "list_page")
        repo = repo_class(L, n)

        if q.kind == "get":
            lines += [
                f'  @Query(() => {n}Type, {{ nullable: true }})',
                f'  {camel(q.name)}(@Arg("id") id: string, @Ctx() ctx: GqlContext): {n}Type | null {{',
                f'    const session = ctx.sessionFactory();',
                f'    const repo = new (require("./../{n}").{repo})(session);',
                f'    const obj = repo.{mname_get}(id);',
                f'    if (!obj) return null;',
                f'    return {{ {_to_type_expr(t, "obj")} }} as {n}Type;',
                '  }',
                '',
            ]
        elif q.kind == "list":
            lines += [
                f'  @Query(() => {n}Connection)',
                f'  {camel(q.name)}(',
                f'    @Arg("first", () => Int, {{ nullable: true }}) first: number | null,',
                f'    @Arg("after", {{ nullable: true }}) after: string | null,',
                f'    @Arg("sort", {{ nullable: true }}) sort: string | null,',
                f'    @Ctx() ctx: GqlContext',
                f'  ): {n}Connection {{',
                f'    const session = ctx.sessionFactory();',
                f'    const repo = new (require("./../{n}").{repo})(session);',
                f'    const page = repo.{mname_list}({{ limit: first ?? {t.pagination.default_limit}, cursor: after, sort }});',
                f'    const edges = page.items.map((r: any) => ({{ cursor: page.nextCursor ?? "", node: {{ {_to_type_expr(t, "r")} }} }}));',
                f'    return {{',
                f'      edges,',
                f'      pageInfo: {{ hasNextPage: page.nextCursor != null, hasPreviousPage: after != null,',
                f'                   startCursor: edges[0]?.cursor ?? null, endCursor: edges[edges.length - 1]?.cursor ?? null }},',
                f'    }} as {n}Connection;',
                '  }',
                '',
            ]
        elif q.kind == "query":
            qobj = next(x for x in t.queries if x.name == q.arg)
            mk = {"page": "query_page", "list": "query_list", "one": "query_one"}[qobj.returns]
            mn = method_name(L, f"{mk}:{q.arg}")
            q_args_dec = []
            q_args_call = []
            for c in qobj.where:
                if not c.param:
                    continue
                q_args_dec.append(f'    @Arg("{camel(c.param)}") {camel(c.param)}: any,')
                q_args_call.append(camel(c.param))
            if q.is_connection:
                q_args_dec += [
                    f'    @Arg("first", () => Int, {{ nullable: true }}) first: number | null,',
                    f'    @Arg("after", {{ nullable: true }}) after: string | null,',
                ]
                call_args = ', '.join(q_args_call + [f'{{ limit: first ?? {t.pagination.default_limit}, cursor: after }}'])
                lines += [
                    f'  @Query(() => {n}Connection)',
                    f'  {camel(q.name)}(',
                ] + q_args_dec + [
                    f'    @Ctx() ctx: GqlContext',
                    f'  ): {n}Connection {{',
                    f'    const session = ctx.sessionFactory();',
                    f'    const repo = new (require("./../{n}").{repo})(session);',
                    f'    const page = repo.{mn}({call_args});',
                    f'    const edges = page.items.map((r: any) => ({{ cursor: page.nextCursor ?? "", node: {{ {_to_type_expr(t, "r")} }} }}));',
                    f'    return {{ edges, pageInfo: {{ hasNextPage: page.nextCursor != null, hasPreviousPage: false, startCursor: edges[0]?.cursor ?? null, endCursor: edges[edges.length - 1]?.cursor ?? null }} }} as {n}Connection;',
                    '  }',
                    '',
                ]
            elif qobj.returns == "list":
                call_args = ', '.join(q_args_call)
                lines += [
                    f'  @Query(() => [{n}Type])',
                    f'  {camel(q.name)}(',
                ] + q_args_dec + [
                    f'    @Ctx() ctx: GqlContext',
                    f'  ): {n}Type[] {{',
                    f'    const session = ctx.sessionFactory();',
                    f'    const repo = new (require("./../{n}").{repo})(session);',
                    f'    return repo.{mn}({call_args}).map((r: any) => ({{ {_to_type_expr(t, "r")} }}));',
                    '  }',
                    '',
                ]
            else:
                call_args = ', '.join(q_args_call)
                lines += [
                    f'  @Query(() => {n}Type, {{ nullable: true }})',
                    f'  {camel(q.name)}(',
                ] + q_args_dec + [
                    f'    @Ctx() ctx: GqlContext',
                    f'  ): {n}Type | null {{',
                    f'    const session = ctx.sessionFactory();',
                    f'    const repo = new (require("./../{n}").{repo})(session);',
                    f'    const obj = repo.{mn}({call_args});',
                    f'    return obj ? {{ {_to_type_expr(t, "obj")} }} as {n}Type : null;',
                    '  }',
                    '',
                ]

    lines += ['}', '']

    if schema.mutations:
        lines.append('@Resolver()')
        lines.append('export class MutationResolver {')
        for m in schema.mutations:
            t = tables[m.table]
            n = m.table
            repo = repo_class(L, n)

            if m.kind == "create":
                lines += [
                    f'  @Mutation(() => {n}Type)',
                    f'  {camel(m.name)}(@Arg("input") input: Create{n}Input, @Ctx() ctx: GqlContext): {n}Type {{',
                    f'    const session = ctx.sessionFactory();',
                    f'    const repo = new (require("./../{n}").{repo})(session);',
                    f'    const obj = repo.{method_name(L, "create")}(input);',
                    f'    return {{ {_to_type_expr(t, "obj")} }} as {n}Type;',
                    '  }',
                    '',
                ]
            elif m.kind == "update":
                lines += [
                    f'  @Mutation(() => {n}Type)',
                    f'  {camel(m.name)}(@Arg("id") id: string, @Arg("input") input: Update{n}Input, @Ctx() ctx: GqlContext): {n}Type {{',
                    f'    const session = ctx.sessionFactory();',
                    f'    const repo = new (require("./../{n}").{repo})(session);',
                    f'    const obj = repo.{method_name(L, "update")}(id, input);',
                    f'    return {{ {_to_type_expr(t, "obj")} }} as {n}Type;',
                    '  }',
                    '',
                ]
            elif m.kind == "delete":
                lines += [
                    f'  @Mutation(() => Boolean)',
                    f'  {camel(m.name)}(@Arg("id") id: string, @Ctx() ctx: GqlContext): boolean {{',
                    f'    const session = ctx.sessionFactory();',
                    f'    const repo = new (require("./../{n}").{repo})(session);',
                    f'    repo.{method_name(L, "delete")}(id);',
                    f'    return true;',
                    '  }',
                    '',
                ]
        lines += ['}', '']

    return '\n'.join(lines) + '\n'


def _app_file(schema: gql.GqlSchema) -> str:
    resolvers = ['QueryResolver']
    if schema.mutations:
        resolvers.append('MutationResolver')
    resolver_imports = ', '.join(resolvers)

    lines = [
        'import "reflect-metadata";',
        'import { buildSchema } from "type-graphql";',
        'import { createYoga } from "graphql-yoga";',
        f'import {{ {resolver_imports} }} from "./resolvers";',
        'import { Loaders } from "./dataloaders";',
        '',
        'export async function createGraphQLSchema() {',
        '  return buildSchema({',
        f'    resolvers: [{", ".join(resolvers)}],',
        '    validate: false,',
        '  });',
        '}',
        '',
        'export async function createApp(sessionFactory: () => any) {',
        '  const schema = await createGraphQLSchema();',
        '  return createYoga({',
        '    schema,',
        '    context: () => ({',
        '      sessionFactory,',
        '      loaders: new Loaders({ sessionFactory }),',
        '    }),',
        '  });',
        '}',
        '',
    ]
    return '\n'.join(lines) + '\n'


def emit(tables: Dict[str, Table], schema: gql.GqlSchema, opts: Dict) -> Dict[str, str]:
    h = header(L, "schemas/db/*.yaml")
    files: Dict[str, str] = {}
    files['generated/types.ts'] = h + _types_file(tables, schema)
    files['generated/inputs.ts'] = h + _inputs_file(schema)
    files['generated/dataloaders.ts'] = h + _dataloaders_file(tables, schema)
    files['generated/resolvers.ts'] = h + _resolvers_file(tables, schema)
    files['generated/app.ts'] = h + _app_file(schema)
    files['generated/index.ts'] = (h + 'export { createApp, createGraphQLSchema } from "./app";\n'
                                   'export { QueryResolver' + (', MutationResolver' if schema.mutations else '') + ' } from "./resolvers";\n')
    files['index.ts'] = (h.rstrip('\n') + '\n'
                         '/** Pacchetto GraphQL: type-graphql types, resolver e server yoga (vedi schemas/generated/schema.graphql). */\n'
                         'export { createApp, createGraphQLSchema } from "./generated";\n')
    return files
