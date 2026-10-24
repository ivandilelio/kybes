"""Emettitore GraphQL Java (Spring for GraphQL): tipi, input, controller, DataLoader, configurazione."""
from __future__ import annotations

from typing import Dict, List

import graphql_plan as gql
from naming import header, member, method_name, repo_class
from schema import Table, camel, snake

L = "java"

GQL_TO_JAVA = {"ID": "String", "String": "String", "Int": "Integer", "Boolean": "Boolean",
               "Date": "LocalDate", "DateTime": "OffsetDateTime", "JSON": "Object"}

JAVA_IMPORTS = {"LocalDate": "java.time.LocalDate", "OffsetDateTime": "java.time.OffsetDateTime"}


def _java_type(gql_type: str, nullable: bool) -> str:
    return GQL_TO_JAVA.get(gql_type, gql_type)


def _java_boxed(gql_type: str) -> str:
    m = {"int": "Integer", "boolean": "Boolean", "long": "Long", "double": "Double"}
    jt = _java_type(gql_type, True)
    return m.get(jt, jt)


def _collect_imports(fields, pkg: str) -> List[str]:
    imps = set()
    for f in fields:
        jt = _java_type(f.gql_type, f.nullable) if hasattr(f, "nullable") else _java_type(f.gql_type, not f.required)
        if jt in JAVA_IMPORTS:
            imps.add(JAVA_IMPORTS[jt])
    return sorted(imps)


def _type_file(gt: gql.GqlType, t: Table, pkg: str) -> str:
    n = gt.name
    gql_pkg = f"{pkg}.graphql.generated"
    lines = [f"package {gql_pkg}.types;", ""]
    imps = _collect_imports([f for f in gt.fields if not f.is_relation], gql_pkg)
    for i in imps:
        lines.append(f"import {i};")
    if imps:
        lines.append("")
    lines += [f"public class {n}Type {{", ""]
    for f in gt.fields:
        if f.is_relation:
            continue
        jt = _java_type(f.gql_type, f.nullable)
        lines.append(f"    private {jt} {f.name};")
    lines += ["", f"    public {n}Type() {{}}", ""]
    # all-args constructor
    params = []
    for f in gt.fields:
        if f.is_relation:
            continue
        jt = _java_type(f.gql_type, f.nullable)
        params.append(f"{jt} {f.name}")
    lines.append(f"    public {n}Type({', '.join(params)}) {{")
    for f in gt.fields:
        if f.is_relation:
            continue
        lines.append(f"        this.{f.name} = {f.name};")
    lines += ["    }", ""]
    for f in gt.fields:
        if f.is_relation:
            continue
        jt = _java_type(f.gql_type, f.nullable)
        cap = f.name[0].upper() + f.name[1:]
        lines += [
            f"    public {jt} get{cap}() {{ return {f.name}; }}",
            f"    public void set{cap}({jt} {f.name}) {{ this.{f.name} = {f.name}; }}",
            "",
        ]
    lines.append("}")
    return "\n".join(lines) + "\n"


def _input_file(inp: gql.GqlInput, pkg: str) -> str:
    gql_pkg = f"{pkg}.graphql.generated"
    lines = [f"package {gql_pkg}.inputs;", ""]
    imps = _collect_imports(inp.fields, gql_pkg)
    for i in imps:
        lines.append(f"import {i};")
    if imps:
        lines.append("")
    lines += [f"public class {inp.name} {{", ""]
    for f in inp.fields:
        jt = _java_type(f.gql_type, not f.required)
        lines.append(f"    private {jt} {f.name};")
    lines += ["", f"    public {inp.name}() {{}}", ""]
    for f in inp.fields:
        jt = _java_type(f.gql_type, not f.required)
        cap = f.name[0].upper() + f.name[1:]
        lines += [
            f"    public {jt} get{cap}() {{ return {f.name}; }}",
            f"    public void set{cap}({jt} {f.name}) {{ this.{f.name} = {f.name}; }}",
            "",
        ]
    lines.append("}")
    return "\n".join(lines) + "\n"


def _to_type_expr(t: Table, var: str) -> str:
    args = []
    for c in t.columns:
        if c.tenant:
            continue
        src = f"{var}.{member(L, c.name)}()"
        if c.type == "uuid":
            src = f"{src} != null ? {src}.toString() : null" if c.nullable else f"{src}.toString()"
        elif c.type in ("bigint", "decimal"):
            src = f"{src} != null ? {src}.toString() : null" if c.nullable else f"{src}.toString()"
        args.append(src)
    return ", ".join(args)


def _auth_check_call(secured: bool, scopes: List[str], roles: List[str]) -> List[str]:
    """Return Java lines that call checkAuth with the right literals."""
    if not secured and not scopes and not roles:
        return []
    sc = "java.util.List.of(" + ", ".join(f'"{s}"' for s in scopes) + ")" if scopes else "java.util.List.of()"
    rl = "java.util.List.of(" + ", ".join(f'"{r}"' for r in roles) + ")" if roles else "java.util.List.of()"
    return [f"        checkAuth(env, {str(secured).lower()}, {sc}, {rl});"]


def _controller_file(gt: gql.GqlType, t: Table, tables: Dict[str, Table],
                      schema: gql.GqlSchema, pkg: str) -> str:
    n = gt.name
    gql_pkg = f"{pkg}.graphql.generated"
    repo = repo_class(L, n)
    lines = [
        f"package {gql_pkg}.resolvers;",
        "",
        "import java.util.List;",
        "import java.util.Optional;",
        "import java.util.concurrent.CompletableFuture;",
        "import java.util.stream.Collectors;",
        "",
        "import org.dataloader.DataLoader;",
        "import org.springframework.graphql.data.method.annotation.Argument;",
        "import org.springframework.graphql.data.method.annotation.MutationMapping;",
        "import org.springframework.graphql.data.method.annotation.QueryMapping;",
        "import org.springframework.graphql.data.method.annotation.SchemaMapping;",
        "import org.springframework.stereotype.Controller;",
        "import graphql.schema.DataFetchingEnvironment;",
        "",
        f"import {pkg}.{repo};",
        f"import {gql_pkg}.types.{n}Type;",
    ]
    # check if we need connection/edge imports
    queries_for_table = [q for q in schema.queries if q.table == n]
    mutations_for_table = [m for m in schema.mutations if m.table == n]
    has_conn = any(q.is_connection for q in queries_for_table)
    if has_conn:
        lines.append(f"import {gql_pkg}.types.{n}Edge;")
        lines.append(f"import {gql_pkg}.types.{n}Connection;")
        lines.append(f"import {gql_pkg}.types.PageInfo;")
    for m in mutations_for_table:
        if m.kind == "create":
            lines.append(f"import {gql_pkg}.inputs.Create{n}Input;")
        elif m.kind == "update":
            lines.append(f"import {gql_pkg}.inputs.Update{n}Input;")
    # relation targets
    rel_targets = set()
    for f in gt.fields:
        if f.is_relation and f.relation_kind == "many_to_one":
            rel_targets.add(f.relation_target)
    for rt in sorted(rel_targets):
        lines.append(f"import {gql_pkg}.types.{rt}Type;")

    needs_auth = t.api.secured or any(q.scopes or q.roles for q in queries_for_table) or any(m.scopes or m.roles for m in mutations_for_table)

    lines += [
        "",
        "@Controller",
        f"public class {n}Controller {{",
        "",
        f"    private final {repo} repo;",
        "",
        f"    public {n}Controller({repo} repo) {{",
        f"        this.repo = repo;",
        "    }",
        "",
    ]

    if needs_auth:
        lines += [
            "    @SuppressWarnings(\"unchecked\")",
            "    private static void checkAuth(DataFetchingEnvironment env, boolean secured, java.util.List<String> scopes, java.util.List<String> roles) {",
            "        var ctx = env.getGraphQlContext();",
            "        var identity = ctx.getOrDefault(\"identity\", null);",
            "        if (identity == null) {",
            "            if (secured || !scopes.isEmpty() || !roles.isEmpty()) throw new graphql.GraphqlErrorException.Builder().message(\"IDENTITY_REQUIRED\").build();",
            "            return;",
            "        }",
            "        var idScopes = ((java.util.Set<String>) ((java.util.Map<String, Object>) identity).getOrDefault(\"scopes\", java.util.Set.of()));",
            "        if (!scopes.isEmpty() && !idScopes.containsAll(scopes)) throw new graphql.GraphqlErrorException.Builder().message(\"SCOPE_REQUIRED\").build();",
            "        if (!roles.isEmpty() && java.util.Collections.disjoint(idScopes, roles)) throw new graphql.GraphqlErrorException.Builder().message(\"ROLE_REQUIRED\").build();",
            "    }",
            "",
        ]

    for q in queries_for_table:
        auth = _auth_check_call(t.api.secured, q.scopes, q.roles)
        env_param = ", DataFetchingEnvironment env" if auth else ""
        if q.kind == "get":
            lines += [
                "    @QueryMapping",
                f"    public {n}Type {q.name}(@Argument String id{env_param}) {{",
            ] + auth + [
                f"        var obj = repo.{method_name(L, 'get_by_id')}(id);",
                f"        return obj == null ? null : new {n}Type({_to_type_expr(t, 'obj')});",
                "    }",
                "",
            ]
        elif q.kind == "list":
            lines += [
                "    @QueryMapping",
                f"    public {n}Connection {q.name}(@Argument Integer first, @Argument String after, @Argument String sort{env_param}) {{",
            ] + auth + [
                f"        int limit = first != null ? first : {t.pagination.default_limit};",
                f"        var page = repo.{method_name(L, 'list_page')}(limit, after, sort);",
                f"        var edges = page.items().stream()",
                f"            .map(r -> new {n}Edge(page.nextCursor() != null ? page.nextCursor() : \"\", new {n}Type({_to_type_expr(t, 'r')})))",
                f"            .collect(Collectors.toList());",
                f"        var pi = new PageInfo(page.nextCursor() != null, after != null,",
                f"            edges.isEmpty() ? null : edges.get(0).getCursor(),",
                f"            edges.isEmpty() ? null : edges.get(edges.size() - 1).getCursor());",
                f"        return new {n}Connection(edges, pi, null);",
                "    }",
                "",
            ]
        elif q.kind == "query":
            qobj = next(x for x in t.queries if x.name == q.arg)
            mk = {"page": "query_page", "list": "query_list", "one": "query_one"}[qobj.returns]
            mname = method_name(L, f"{mk}:{q.arg}")
            repo_args = ", ".join(camel(c.param) for c in qobj.where if c.param)
            arg_defs = ", ".join(
                f"@Argument {_java_type(a.gql_type, not a.required)} {a.name}"
                for a in q.args if a.name not in ("first", "after")
            )
            if q.is_connection:
                page_args = "@Argument Integer first, @Argument String after"
                all_args = f"{arg_defs}, {page_args}" if arg_defs else page_args
                call_args = f"{repo_args}, limit, after" if repo_args else "limit, after"
                lines += [
                    "    @QueryMapping",
                    f"    public {n}Connection {q.name}({all_args}{env_param}) {{",
                ] + auth + [
                    f"        int limit = first != null ? first : {t.pagination.default_limit};",
                    f"        var page = repo.{mname}({call_args});",
                    f"        var edges = page.items().stream()",
                    f"            .map(r -> new {n}Edge(page.nextCursor() != null ? page.nextCursor() : \"\", new {n}Type({_to_type_expr(t, 'r')})))",
                    f"            .collect(Collectors.toList());",
                    f"        var pi = new PageInfo(page.nextCursor() != null, false, null, null);",
                    f"        return new {n}Connection(edges, pi, null);",
                    "    }",
                    "",
                ]
            elif qobj.returns == "list":
                lines += [
                    "    @QueryMapping",
                    f"    public List<{n}Type> {q.name}({arg_defs}{env_param}) {{",
                ] + auth + [
                    f"        return repo.{mname}({repo_args}).stream()",
                    f"            .map(r -> new {n}Type({_to_type_expr(t, 'r')}))",
                    f"            .collect(Collectors.toList());",
                    "    }",
                    "",
                ]
            else:
                lines += [
                    "    @QueryMapping",
                    f"    public {n}Type {q.name}({arg_defs}{env_param}) {{",
                ] + auth + [
                    f"        var obj = repo.{mname}({repo_args});",
                    f"        return obj == null ? null : new {n}Type({_to_type_expr(t, 'obj')});",
                    "    }",
                    "",
                ]

    for m in mutations_for_table:
        auth = _auth_check_call(t.api.secured, m.scopes, m.roles)
        env_param = ", DataFetchingEnvironment env" if auth else ""
        if m.kind == "create":
            assign_args = []
            for c in t.columns:
                if c.tenant or (c.primary_key and c.auto) or c.generated:
                    continue
                assign_args.append(f"input.get{c.name}()")
            lines += [
                "    @MutationMapping",
                f"    public {n}Type {m.name}(@Argument Create{n}Input input{env_param}) {{",
            ] + auth + [
                f"        var obj = repo.{method_name(L, 'create')}({', '.join(assign_args)});",
                f"        return new {n}Type({_to_type_expr(t, 'obj')});",
                "    }",
                "",
            ]
        elif m.kind == "update":
            lines += [
                "    @MutationMapping",
                f"    public {n}Type {m.name}(@Argument String id, @Argument Update{n}Input input{env_param}) {{",
            ] + auth + [
                f"        var obj = repo.{method_name(L, 'update')}(id, input);",
                f"        return new {n}Type({_to_type_expr(t, 'obj')});",
                "    }",
                "",
            ]
        elif m.kind == "delete":
            lines += [
                "    @MutationMapping",
                f"    public Boolean {m.name}(@Argument String id{env_param}) {{",
            ] + auth + [
                f"        repo.{method_name(L, 'delete')}(id);",
                f"        return true;",
                "    }",
                "",
            ]

    # SchemaMapping for relations
    for f in gt.fields:
        if not f.is_relation:
            continue
        if f.relation_kind == "many_to_one":
            target = f.relation_target
            tt = tables.get(target)
            if tt is None:
                continue
            lines += [
                f"    @SchemaMapping(typeName = \"{n}\", field = \"{f.name}\")",
                f"    public CompletableFuture<{target}Type> {f.name}({n}Type parent, DataLoader<String, {target}Type> loader) {{",
                f"        String fk = parent.get{f.column_name}();",
                f"        return fk == null ? CompletableFuture.completedFuture(null) : loader.load(fk);",
                "    }",
                "",
            ]

    lines.append("}")
    return "\n".join(lines) + "\n"


def _dataloader_file(gt: gql.GqlType, t: Table, tables: Dict[str, Table], pkg: str) -> str:
    n = gt.name
    gql_pkg = f"{pkg}.graphql.generated"
    rel_fields = [f for f in gt.fields if f.is_relation and f.relation_kind == "many_to_one"]
    if not rel_fields:
        return ""
    lines = [
        f"package {gql_pkg}.dataloaders;",
        "",
        "import java.util.Map;",
        "import java.util.Set;",
        "import java.util.concurrent.CompletableFuture;",
        "import java.util.concurrent.CompletionStage;",
        "import java.util.function.Function;",
        "import java.util.stream.Collectors;",
        "",
        "import org.dataloader.MappedBatchLoader;",
        "",
    ]
    targets_seen = set()
    for f in rel_fields:
        target = f.relation_target
        if target in targets_seen:
            continue
        targets_seen.add(target)
        tt = tables.get(target)
        if tt is None:
            continue
        lines += [
            f"import {pkg}.{repo_class(L, target)};",
            f"import {gql_pkg}.types.{target}Type;",
        ]
    lines += [
        "",
        f"public class {n}DataLoaders {{",
        "",
    ]
    for f in rel_fields:
        target = f.relation_target
        tt = tables.get(target)
        if tt is None:
            continue
        loader_name = f"{camel(f.name)}Loader"
        repo = repo_class(L, target)
        lines += [
            f"    public static MappedBatchLoader<String, {target}Type> {loader_name}({repo} repo) {{",
            f"        return keys -> CompletableFuture.supplyAsync(() -> {{",
            f"            Map<String, {target}Type> map = new java.util.HashMap<>();",
            f"            for (String k : keys) {{",
            f"                var obj = repo.{method_name(L, 'get_by_id')}(k);",
            f"                if (obj != null) map.put(k, new {target}Type({_to_type_expr(tt, 'obj')}));",
            f"            }}",
            f"            return map;",
            f"        }});",
            "    }",
            "",
        ]
    lines.append("}")
    return "\n".join(lines) + "\n"


def _connection_types(schema: gql.GqlSchema, pkg: str) -> str:
    gql_pkg = f"{pkg}.graphql.generated"
    lines = [
        f"package {gql_pkg}.types;",
        "",
        "import java.util.List;",
        "",
    ]
    lines += [
        "public class PageInfo {",
        "    private boolean hasNextPage;",
        "    private boolean hasPreviousPage;",
        "    private String startCursor;",
        "    private String endCursor;",
        "",
        "    public PageInfo() {}",
        "    public PageInfo(boolean hasNextPage, boolean hasPreviousPage, String startCursor, String endCursor) {",
        "        this.hasNextPage = hasNextPage;",
        "        this.hasPreviousPage = hasPreviousPage;",
        "        this.startCursor = startCursor;",
        "        this.endCursor = endCursor;",
        "    }",
        "",
        "    public boolean isHasNextPage() { return hasNextPage; }",
        "    public void setHasNextPage(boolean v) { hasNextPage = v; }",
        "    public boolean isHasPreviousPage() { return hasPreviousPage; }",
        "    public void setHasPreviousPage(boolean v) { hasPreviousPage = v; }",
        "    public String getStartCursor() { return startCursor; }",
        "    public void setStartCursor(String v) { startCursor = v; }",
        "    public String getEndCursor() { return endCursor; }",
        "    public void setEndCursor(String v) { endCursor = v; }",
        "}",
    ]
    return "\n".join(lines) + "\n"


def _edge_file(name: str, pkg: str) -> str:
    gql_pkg = f"{pkg}.graphql.generated"
    return "\n".join([
        f"package {gql_pkg}.types;",
        "",
        f"public class {name}Edge {{",
        "    private String cursor;",
        f"    private {name}Type node;",
        "",
        f"    public {name}Edge() {{}}",
        f"    public {name}Edge(String cursor, {name}Type node) {{ this.cursor = cursor; this.node = node; }}",
        "",
        f"    public String getCursor() {{ return cursor; }}",
        f"    public void setCursor(String v) {{ cursor = v; }}",
        f"    public {name}Type getNode() {{ return node; }}",
        f"    public void setNode({name}Type v) {{ node = v; }}",
        "}",
    ]) + "\n"


def _connection_file(name: str, pkg: str) -> str:
    gql_pkg = f"{pkg}.graphql.generated"
    return "\n".join([
        f"package {gql_pkg}.types;",
        "",
        "import java.util.List;",
        "",
        f"public class {name}Connection {{",
        f"    private List<{name}Edge> edges;",
        "    private PageInfo pageInfo;",
        "    private Integer totalCount;",
        "",
        f"    public {name}Connection() {{}}",
        f"    public {name}Connection(List<{name}Edge> edges, PageInfo pageInfo, Integer totalCount) {{",
        "        this.edges = edges; this.pageInfo = pageInfo; this.totalCount = totalCount;",
        "    }",
        "",
        f"    public List<{name}Edge> getEdges() {{ return edges; }}",
        f"    public void setEdges(List<{name}Edge> v) {{ edges = v; }}",
        "    public PageInfo getPageInfo() { return pageInfo; }",
        "    public void setPageInfo(PageInfo v) { pageInfo = v; }",
        "    public Integer getTotalCount() { return totalCount; }",
        "    public void setTotalCount(Integer v) { totalCount = v; }",
        "}",
    ]) + "\n"


def _config_file(schema: gql.GqlSchema, tables: Dict[str, Table], pkg: str) -> str:
    gql_pkg = f"{pkg}.graphql.generated"
    lines = [
        f"package {gql_pkg};",
        "",
        "import org.dataloader.DataLoaderRegistry;",
        "import org.dataloader.DataLoader;",
        "import org.springframework.context.annotation.Bean;",
        "import org.springframework.context.annotation.Configuration;",
        "import org.springframework.graphql.execution.RuntimeWiringConfigurer;",
        "",
    ]
    for gt in schema.types:
        rel_fields = [f for f in gt.fields if f.is_relation and f.relation_kind == "many_to_one"]
        if rel_fields:
            lines.append(f"import {gql_pkg}.dataloaders.{gt.name}DataLoaders;")
    targets_seen = set()
    for gt in schema.types:
        for f in gt.fields:
            if f.is_relation and f.relation_kind == "many_to_one" and f.relation_target not in targets_seen:
                targets_seen.add(f.relation_target)
                lines.append(f"import {pkg}.{repo_class(L, f.relation_target)};")
    lines += [
        "",
        "@Configuration",
        "public class GraphQLConfig {",
        "",
    ]
    # DataLoaderRegistry bean
    repo_params = set()
    for gt in schema.types:
        for f in gt.fields:
            if f.is_relation and f.relation_kind == "many_to_one":
                repo_params.add(f.relation_target)
    params = ", ".join(f"{repo_class(L, r)} {camel(r)}Repo" for r in sorted(repo_params))
    lines += [
        "    @Bean",
        f"    public DataLoaderRegistry dataLoaderRegistry({params}) {{",
        "        DataLoaderRegistry registry = new DataLoaderRegistry();",
    ]
    for gt in schema.types:
        for f in gt.fields:
            if not f.is_relation or f.relation_kind != "many_to_one":
                continue
            target = f.relation_target
            loader_name = f"{camel(f.name)}Loader"
            reg_key = f"{gt.name}.{f.name}"
            lines.append(f"        registry.register(\"{reg_key}\", DataLoader.newMappedDataLoader({gt.name}DataLoaders.{loader_name}({camel(target)}Repo)));")
    lines += [
        "        return registry;",
        "    }",
        "}",
    ]
    return "\n".join(lines) + "\n"


def emit(tables: Dict[str, Table], schema: gql.GqlSchema, opts: Dict):
    pkg = opts["package"]
    h = header(L, "schemas/db/*.yaml")
    files = {}
    files["generated/types/PageInfo.java"] = h + _connection_types(schema, pkg)
    for gt in schema.types:
        t = tables[gt.table]
        n = gt.name
        files[f"generated/types/{n}Type.java"] = h + _type_file(gt, t, pkg)
        files[f"generated/types/{n}Edge.java"] = h + _edge_file(n, pkg)
        files[f"generated/types/{n}Connection.java"] = h + _connection_file(n, pkg)
        files[f"generated/resolvers/{n}Controller.java"] = h + _controller_file(gt, t, tables, schema, pkg)
        dl = _dataloader_file(gt, t, tables, pkg)
        if dl:
            files[f"generated/dataloaders/{n}DataLoaders.java"] = h + dl
    for inp in schema.inputs:
        files[f"generated/inputs/{inp.name}.java"] = h + _input_file(inp, pkg)
    files["generated/GraphQLConfig.java"] = h + _config_file(schema, tables, pkg)
    return files
