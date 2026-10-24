"""Emettitore GraphQL C# (HotChocolate): tipi, resolver, DataLoader, setup DI."""
from __future__ import annotations

from typing import Dict, List

import graphql_plan as gql
from naming import header, member, method_name, repo_class
from schema import Table, camel, snake

L = "csharp"

CS_TYPE = {"ID": "string", "String": "string", "Int": "int", "Boolean": "bool",
           "Date": "DateOnly", "DateTime": "DateTimeOffset", "JSON": "object"}


def _cs_type(gql_type: str, nullable: bool) -> str:
    base = CS_TYPE.get(gql_type, gql_type + "Type")
    if nullable and base not in ("string", "object"):
        return base + "?"
    if nullable and base in ("string", "object"):
        return base + "?"
    return base


def _to_type_expr(t: Table, var: str) -> List[str]:
    assigns = []
    for c in t.columns:
        if c.tenant:
            continue
        m = member(L, c.name)
        assigns.append(f"            {m} = {var}.{m}")
    return assigns


def _type_file(gt: gql.GqlType, t: Table, ns: str) -> str:
    lines = [
        f"namespace {ns}.Types;",
        "",
        "using HotChocolate;",
        "",
        f'/// <summary>{gt.description or gt.name}</summary>',
        f"public class {gt.name}Type",
        "{",
    ]
    for f in gt.fields:
        if f.is_relation:
            continue
        ct = _cs_type(f.gql_type, f.nullable)
        lines.append(f"    public {ct} {member(L, f.name)} {{ get; set; }}")
    lines += ["}", ""]

    lines += [
        f"public class {gt.name}Edge",
        "{",
        "    public string Cursor { get; set; } = \"\";",
        f"    public {gt.name}Type Node {{ get; set; }} = null!;",
        "}",
        "",
        f"public class {gt.name}Connection",
        "{",
        f"    public List<{gt.name}Edge> Edges {{ get; set; }} = new();",
        "    public PageInfoType PageInfo { get; set; } = new();",
        "    public int? TotalCount { get; set; }",
        "}",
        "",
    ]
    return "\n".join(lines)


def _page_info_file(ns: str) -> str:
    return "\n".join([
        f"namespace {ns}.Types;",
        "",
        "public class PageInfoType",
        "{",
        "    public bool HasNextPage { get; set; }",
        "    public bool HasPreviousPage { get; set; }",
        "    public string? StartCursor { get; set; }",
        "    public string? EndCursor { get; set; }",
        "}",
        "",
    ])


def _input_file(inp: gql.GqlInput, ns: str) -> str:
    lines = [
        f"namespace {ns}.Inputs;",
        "",
        f"public class {inp.name}",
        "{",
    ]
    for f in inp.fields:
        ct = _cs_type(f.gql_type, not f.required)
        lines.append(f"    public {ct} {f.name[0].upper() + f.name[1:]} {{ get; set; }}")
    lines += ["}", ""]
    return "\n".join(lines)


def _auth_lines(secured: bool, scopes: List[str], roles: List[str]) -> List[str]:
    if not secured and not scopes and not roles:
        return []
    out: List[str] = []
    if secured:
        out.append('        var identity = context.GetGlobalState<Identity>("identity");')
        out.append('        if (identity?.Subject == null) throw new GraphQLException("IDENTITY_REQUIRED");')
    if scopes:
        sc = ", ".join(f'"{s}"' for s in scopes)
        out.append(f'        var _reqScopes = new HashSet<string>(new[] {{ {sc} }});')
        out.append('        if (!_reqScopes.IsSubsetOf(identity!.Scopes)) throw new GraphQLException("SCOPE_REQUIRED");')
    if roles:
        rl = ", ".join(f'"{r}"' for r in roles)
        out.append(f'        var _reqRoles = new HashSet<string>(new[] {{ {rl} }});')
        out.append('        if (!_reqRoles.Overlaps(identity!.Scopes)) throw new GraphQLException("ROLE_REQUIRED");')
    return out


def _resolver_file(t: Table, n: str, schema: gql.GqlSchema, ns: str) -> str:
    repo = repo_class(L, n)
    queries = [q for q in schema.queries if q.table == n]
    mutations = [m for m in schema.mutations if m.table == n]
    secured = t.api.secured if t.api else False
    lines = [
        f"namespace {ns}.Resolvers;",
        "",
        f"using {ns}.Types;",
        f"using {ns}.Inputs;",
        "using HotChocolate;",
        "",
    ]

    if queries:
        lines += [
            "[ExtendObjectType(typeof(Query))]",
            f"public class {n}Queries",
            "{",
        ]
        for q in queries:
            ret = f"{n}Type?" if q.kind == "get" else f"{n}Connection"
            args_sig = _cs_args(q.args)
            if args_sig:
                args_sig = ", " + args_sig
            auth = _auth_lines(secured, q.scopes, q.roles)
            ctx_param = ", IResolverContext context" if auth else ""
            lines.append(f"    public async Task<{ret}> {q.name[0].upper() + q.name[1:]}([Service] {repo} repo{args_sig}{ctx_param})")
            lines.append("    {")
            lines += auth
            if q.kind == "get":
                lines += [
                    f"        var obj = await repo.{method_name(L, 'get_by_id')}(id);",
                    "        if (obj == null) return null;",
                    f"        return new {n}Type",
                    "        {",
                ] + [f"        {a}," for a in _to_type_expr(t, "obj")] + [
                    "        };",
                ]
            elif q.kind == "list":
                lines += [
                    f"        var page = await repo.{method_name(L, 'list_page')}(first ?? {t.pagination.default_limit}, after, sort);",
                    f"        return ToConnection_{n}(page, after);",
                ]
            elif q.kind == "query":
                qobj = next(x for x in t.queries if x.name == q.arg)
                mk = {"page": "query_page", "list": "query_list", "one": "query_one"}[qobj.returns]
                mname = method_name(L, f"{mk}:{q.arg}")
                repo_args = ", ".join(c.param[0].upper() + c.param[1:] if c.param else "" for c in qobj.where if c.param)
                if q.is_connection:
                    extra = f", first ?? {t.pagination.default_limit}, after"
                    lines += [
                        f"        var page = await repo.{mname}({repo_args}{extra});",
                        f"        return ToConnection_{n}(page, after);",
                    ]
                elif qobj.returns == "list":
                    lines += [
                        f"        var items = await repo.{mname}({repo_args});",
                        f"        return items.Select(r => new {n}Type",
                        "        {",
                    ] + [f"        {a}," for a in _to_type_expr(t, "r")] + [
                        "        }).ToList();",
                    ]
                else:
                    lines += [
                        f"        var obj = await repo.{mname}({repo_args});",
                        "        if (obj == null) return null;",
                        f"        return new {n}Type",
                        "        {",
                    ] + [f"        {a}," for a in _to_type_expr(t, "obj")] + [
                        "        };",
                    ]
            lines += ["    }", ""]
        lines += [
            f"    private static {n}Connection ToConnection_{n}(dynamic page, string? after)",
            "    {",
            f"        var edges = new List<{n}Edge>();",
            "        foreach (var r in page.Items)",
            "        {",
            f"            edges.Add(new {n}Edge",
            "            {",
            "                Cursor = page.NextCursor ?? \"\",",
            f"                Node = new {n}Type",
            "                {",
        ] + [f"                {a}," for a in _to_type_expr(t, "r")] + [
            "                }",
            "            });",
            "        }",
            f"        return new {n}Connection",
            "        {",
            "            Edges = edges,",
            "            PageInfo = new PageInfoType",
            "            {",
            "                HasNextPage = page.NextCursor != null,",
            "                HasPreviousPage = after != null,",
            "                StartCursor = edges.FirstOrDefault()?.Cursor,",
            "                EndCursor = edges.LastOrDefault()?.Cursor,",
            "            }",
            "        };",
            "    }",
            "}",
            "",
        ]

    if mutations:
        lines += [
            "[ExtendObjectType(typeof(Mutation))]",
            f"public class {n}Mutations",
            "{",
        ]
        for m in mutations:
            args_sig = _cs_args(m.args)
            if args_sig:
                args_sig = ", " + args_sig
            m_auth = _auth_lines(secured, m.scopes, m.roles)
            m_ctx = ", IResolverContext context" if m_auth else ""
            if m.kind == "create":
                lines += [
                    f"    public async Task<{n}Type> {m.name[0].upper() + m.name[1:]}([Service] {repo} repo{args_sig}{m_ctx})",
                    "    {",
                ] + m_auth + [
                    f"        var obj = await repo.{method_name(L, 'create')}(input);",
                    f"        return new {n}Type",
                    "        {",
                ] + [f"        {a}," for a in _to_type_expr(t, "obj")] + [
                    "        };",
                    "    }",
                    "",
                ]
            elif m.kind == "update":
                lines += [
                    f"    public async Task<{n}Type> {m.name[0].upper() + m.name[1:]}([Service] {repo} repo{args_sig}{m_ctx})",
                    "    {",
                ] + m_auth + [
                    f"        var obj = await repo.{method_name(L, 'update')}(id, input);",
                    f"        return new {n}Type",
                    "        {",
                ] + [f"        {a}," for a in _to_type_expr(t, "obj")] + [
                    "        };",
                    "    }",
                    "",
                ]
            elif m.kind == "delete":
                lines += [
                    f"    public async Task<bool> {m.name[0].upper() + m.name[1:]}([Service] {repo} repo{args_sig}{m_ctx})",
                    "    {",
                ] + m_auth + [
                    f"        await repo.{method_name(L, 'delete')}(id);",
                    "        return true;",
                    "    }",
                    "",
                ]
        lines += ["}", ""]

    return "\n".join(lines)


def _dataloader_file(gt: gql.GqlType, t: Table, tables: Dict[str, Table], ns: str) -> str:
    loaders = []
    for f in gt.fields:
        if not f.is_relation or f.is_connection or f.relation_kind != "many_to_one":
            continue
        target = f.relation_target
        tt = tables[target]
        loader_name = f"{gt.name}{f.name[0].upper() + f.name[1:]}DataLoader"
        repo = repo_class(L, target)
        loaders.append((loader_name, repo, target, f))

    if not loaders:
        return ""

    lines = [
        f"namespace {ns}.DataLoaders;",
        "",
        f"using {ns}.Types;",
        "using GreenDonut;",
        "",
    ]
    for loader_name, repo, target, f in loaders:
        pk_type = _cs_type("ID", False)
        lines += [
            f"public class {loader_name} : BatchDataLoader<{pk_type}, {target}Type>",
            "{",
            f"    private readonly {repo} _repo;",
            "",
            f"    public {loader_name}({repo} repo, IBatchScheduler scheduler, DataLoaderOptions? options = null)",
            "        : base(scheduler, options)",
            "    {",
            "        _repo = repo;",
            "    }",
            "",
            f"    protected override async Task<IReadOnlyDictionary<{pk_type}, {target}Type>> LoadBatchAsync(",
            f"        IReadOnlyList<{pk_type}> keys, CancellationToken ct)",
            "    {",
            f"        var dict = new Dictionary<{pk_type}, {target}Type>();",
            "        foreach (var k in keys)",
            "        {",
            f"            var obj = await _repo.{method_name(L, 'get_by_id')}(k);",
            "            if (obj != null)",
            "            {",
            f"                dict[k] = new {target}Type",
            "                {",
        ] + [f"                {a}," for a in _to_type_expr(tables[target], "obj")] + [
            "                };",
            "            }",
            "        }",
            "        return dict;",
            "    }",
            "}",
            "",
        ]
    return "\n".join(lines)


def _setup_file(schema: gql.GqlSchema, tables: Dict[str, Table], ns: str) -> str:
    lines = [
        f"namespace {ns};",
        "",
        f"using {ns}.Resolvers;",
        f"using {ns}.DataLoaders;",
        "using HotChocolate;",
        "",
        "public static class GraphQLSetup",
        "{",
        "    public static IServiceCollection AddKybesGraphQL(this IServiceCollection services)",
        "    {",
        "        services",
        "            .AddGraphQLServer()",
        "            .AddQueryType<Query>()",
    ]
    has_mutations = bool(schema.mutations)
    if has_mutations:
        lines.append("            .AddMutationType<Mutation>()")
    for gt in schema.types:
        lines.append(f"            .AddTypeExtension<{gt.name}Queries>()")
    if has_mutations:
        for gt in schema.types:
            muts = [m for m in schema.mutations if m.table == gt.table]
            if muts:
                lines.append(f"            .AddTypeExtension<{gt.name}Mutations>()")
    for gt in schema.types:
        t = tables[gt.table]
        for f in gt.fields:
            if f.is_relation and not f.is_connection and f.relation_kind == "many_to_one":
                loader = f"{gt.name}{f.name[0].upper() + f.name[1:]}DataLoader"
                lines.append(f"            .AddDataLoader<{loader}>()")
    lines += [
        "            ;",
        "        return services;",
        "    }",
        "}",
        "",
        "public class Query { }",
        "",
    ]
    if has_mutations:
        lines += ["public class Mutation { }", ""]
    return "\n".join(lines)


def _cs_args(args: list) -> str:
    parts = []
    for a in args:
        ct = _cs_type(a.gql_type, not a.required)
        name = a.name
        if name == "input":
            ct = a.gql_type
        default = "" if a.required else " = null"
        parts.append(f"{ct} {name}{default}")
    return ", ".join(parts)


def emit(tables: Dict[str, Table], schema: gql.GqlSchema, opts: Dict) -> Dict[str, str]:
    ns = opts.get("namespace", "App.Model") + ".GraphQL"
    h = header(L, "schemas/db/*.yaml")
    files: Dict[str, str] = {}

    files["generated/Types/PageInfoType.cs"] = h + _page_info_file(ns)

    for gt in schema.types:
        t = tables[gt.table]
        files[f"generated/Types/{gt.name}Type.cs"] = h + _type_file(gt, t, ns)

    for inp in schema.inputs:
        files[f"generated/Inputs/{inp.name}.cs"] = h + _input_file(inp, ns)

    for gt in schema.types:
        t = tables[gt.table]
        content = _resolver_file(t, gt.name, schema, ns)
        if content.strip():
            files[f"generated/Resolvers/{gt.name}Resolvers.cs"] = h + content

        dl = _dataloader_file(gt, t, tables, ns)
        if dl.strip():
            files[f"generated/DataLoaders/{gt.name}DataLoader.cs"] = h + dl

    files["generated/GraphQLSetup.cs"] = h + _setup_file(schema, tables, ns)

    return files
