"""Piano neutro delle API GraphQL: tipi, query, mutazioni e schema SDL dal modello YAML.

Fonti:
  - il blocco api degli schemi delle tabelle -> tipi, query CRUD, relazioni
  - le stesse colonne e relazioni del modello -> campi e connessioni Relay

Il risultato serve a tutti gli emettitori GraphQL: ogni linguaggio riceve la stessa
struttura di tipi e operazioni e genera il codice appropriato per la sua libreria.

Convenzioni del contratto (uguali in tutti i linguaggi):
  uuid -> ID, bigint e decimal come stringhe (scalari custom), date e datetime come
  scalari custom Date/DateTime, json come scalare JSON.  Le relazioni sono campi
  di primo livello (many_to_one -> campo nullable, one_to_many -> Connection).
  Paginazione Relay con cursori opachi, mappati alla paginazione a cursore esistente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from schema import Table, camel, snake, tenant_column


GQL_SCALARS = {"uuid": "ID", "string": "String", "text": "String", "int": "Int",
               "bigint": "String", "decimal": "String", "bool": "Boolean",
               "date": "Date", "datetime": "DateTime", "json": "JSON"}

CUSTOM_SCALARS = {"Date", "DateTime", "JSON"}


@dataclass
class GqlField:
    name: str
    gql_type: str
    nullable: bool
    description: str = ""
    is_id: bool = False
    is_relation: bool = False
    is_connection: bool = False
    relation_target: str = ""
    relation_kind: str = ""
    column_name: str = ""


@dataclass
class GqlInputField:
    name: str
    gql_type: str
    required: bool
    description: str = ""


@dataclass
class GqlType:
    name: str
    table: str
    fields: List[GqlField]
    description: str = ""


@dataclass
class GqlInput:
    name: str
    table: str
    fields: List[GqlInputField]
    kind: str = ""


@dataclass
class GqlQuery:
    name: str
    return_type: str
    args: List[GqlInputField]
    table: str
    kind: str
    arg: str = ""
    description: str = ""
    is_connection: bool = False


@dataclass
class GqlMutation:
    name: str
    return_type: str
    args: List[GqlInputField]
    table: str
    kind: str
    description: str = ""


@dataclass
class GqlSchema:
    types: List[GqlType]
    inputs: List[GqlInput]
    queries: List[GqlQuery]
    mutations: List[GqlMutation]
    custom_scalars: List[str]


def _gql_type(c) -> str:
    return GQL_SCALARS.get(c.type, "String")


def _field_type_str(f: GqlField) -> str:
    if f.is_connection:
        return f"{f.relation_target}Connection!"
    t = f.gql_type
    bang = "" if f.nullable else "!"
    return f"{t}{bang}"


def _input_field_str(f: GqlInputField) -> str:
    bang = "!" if f.required else ""
    return f"{f.gql_type}{bang}"


def type_fields(t: Table, tables: Dict[str, Table]) -> List[GqlField]:
    fields = []
    tc = tenant_column(t)
    for c in t.columns:
        if c.tenant:
            continue
        gtype = _gql_type(c)
        fields.append(GqlField(
            name=camel(c.name),
            gql_type=gtype,
            nullable=c.nullable,
            description=c.description,
            is_id=c.primary_key,
            column_name=c.name,
        ))
    if t.api:
        for r in t.relations:
            if r.name not in (t.api.relations + t.api.expandable):
                if r.name not in [rn for rn in t.api.relations]:
                    pass
            if r.kind == "many_to_one":
                target = tables.get(r.target)
                if target:
                    fields.append(GqlField(
                        name=camel(r.name),
                        gql_type=r.target,
                        nullable=True,
                        is_relation=True,
                        relation_target=r.target,
                        relation_kind=r.kind,
                        column_name=r.foreign_key,
                    ))
            elif r.kind == "one_to_many":
                fields.append(GqlField(
                    name=camel(r.name),
                    gql_type=f"{r.target}Connection",
                    nullable=False,
                    is_relation=True,
                    is_connection=True,
                    relation_target=r.target,
                    relation_kind=r.kind,
                ))
    return fields


def create_input_fields(t: Table) -> List[GqlInputField]:
    fields = []
    for c in t.columns:
        if c.tenant or (c.primary_key and c.auto) or c.generated:
            continue
        if c.primary_key:
            fields.append(GqlInputField(name=camel(c.name), gql_type=_gql_type(c),
                                        required=True, description=c.description))
            continue
        fields.append(GqlInputField(
            name=camel(c.name),
            gql_type=_gql_type(c),
            required=c.required and c.default is None,
            description=c.description,
        ))
    return fields


def update_input_fields(t: Table) -> List[GqlInputField]:
    fields = []
    for c in t.columns:
        if c.tenant or c.primary_key or c.generated:
            continue
        fields.append(GqlInputField(
            name=camel(c.name),
            gql_type=_gql_type(c),
            required=False,
            description=c.description,
        ))
    return fields


def build(tables: Dict[str, Table]) -> GqlSchema:
    types, inputs, queries, mutations = [], [], [], []
    used_scalars = set()

    for n, t in tables.items():
        if not t.api:
            continue
        a = t.api

        flds = type_fields(t, tables)
        for f in flds:
            if f.gql_type in CUSTOM_SCALARS:
                used_scalars.add(f.gql_type)
        types.append(GqlType(name=n, table=n, fields=flds, description=t.description or ""))

        if "list" in a.operations:
            args = [
                GqlInputField("first", "Int", False, "numero massimo di risultati"),
                GqlInputField("after", "String", False, "cursore della pagina successiva"),
                GqlInputField("sort", "String", False, "ordinamento"),
            ]
            queries.append(GqlQuery(
                name=f"all{n}",
                return_type=f"{n}Connection",
                args=args,
                table=n,
                kind="list",
                is_connection=True,
                description=f"pagina di {n} con cursore Relay",
            ))

        if "get" in a.operations:
            pk_type = _gql_type(t.pk)
            queries.append(GqlQuery(
                name=camel(n),
                return_type=n,
                args=[GqlInputField("id", pk_type, True, "chiave primaria")],
                table=n,
                kind="get",
                description=f"un record di {n} per chiave",
            ))

        for qn in a.queries:
            q = next(x for x in t.queries if x.name == qn)
            args = []
            for c in q.where:
                if not c.param:
                    continue
                col = t.col(c.column)
                gtype = _gql_type(col)
                if c.op == "in":
                    gtype = f"[{gtype}!]"
                elif c.op == "prefix":
                    gtype = "String"
                args.append(GqlInputField(camel(c.param), gtype, True))
            is_conn = q.returns == "page"
            if is_conn:
                args += [
                    GqlInputField("first", "Int", False),
                    GqlInputField("after", "String", False),
                ]
            ret = f"{n}Connection" if is_conn else (f"[{n}!]!" if q.returns == "list" else n)
            queries.append(GqlQuery(
                name=f"{camel(n)}{q.name}",
                return_type=ret,
                args=args,
                table=n,
                kind="query",
                arg=q.name,
                is_connection=is_conn,
                description=f"query {q.name}",
            ))

        if "create" in a.operations:
            cf = create_input_fields(t)
            inputs.append(GqlInput(name=f"Create{n}Input", table=n, fields=cf, kind="create"))
            mutations.append(GqlMutation(
                name=f"create{n}",
                return_type=f"{n}!",
                args=[GqlInputField("input", f"Create{n}Input", True)],
                table=n,
                kind="create",
                description=f"crea un record di {n}",
            ))

        if "update" in a.operations:
            uf = update_input_fields(t)
            inputs.append(GqlInput(name=f"Update{n}Input", table=n, fields=uf, kind="update"))
            pk_type = _gql_type(t.pk)
            mutations.append(GqlMutation(
                name=f"update{n}",
                return_type=f"{n}!",
                args=[
                    GqlInputField("id", pk_type, True),
                    GqlInputField("input", f"Update{n}Input", True),
                ],
                table=n,
                kind="update",
                description=f"aggiorna un record di {n}",
            ))

        if "delete" in a.operations:
            pk_type = _gql_type(t.pk)
            mutations.append(GqlMutation(
                name=f"delete{n}",
                return_type="Boolean!",
                args=[GqlInputField("id", pk_type, True)],
                table=n,
                kind="delete",
                description=f"elimina un record di {n}",
            ))

    return GqlSchema(
        types=types,
        inputs=inputs,
        queries=queries,
        mutations=mutations,
        custom_scalars=sorted(used_scalars),
    )


def render_sdl(schema: GqlSchema) -> str:
    lines = [f"# {_MARKER}. NON MODIFICARE: generato da schemas/db/*.yaml.", ""]

    for s in schema.custom_scalars:
        lines.append(f"scalar {s}")
    if schema.custom_scalars:
        lines.append("")

    lines += [
        "type PageInfo {",
        "  hasNextPage: Boolean!",
        "  hasPreviousPage: Boolean!",
        "  startCursor: String",
        "  endCursor: String",
        "}",
        "",
    ]

    emitted_connections = set()
    for t in schema.types:
        if t.description:
            lines.append(f'"""{t.description}"""')
        lines.append(f"type {t.name} {{")
        for f in t.fields:
            if f.is_connection:
                emitted_connections.add(f.relation_target)
            desc = f'  """{f.description}"""\n' if f.description else ""
            lines.append(f"{desc}  {f.name}: {_field_type_str(f)}")
        lines += ["}", ""]

        emitted_connections.add(t.name)
        lines += [
            f"type {t.name}Edge {{",
            "  cursor: String!",
            f"  node: {t.name}!",
            "}",
            "",
            f"type {t.name}Connection {{",
            f"  edges: [{t.name}Edge!]!",
            "  pageInfo: PageInfo!",
            "  totalCount: Int",
            "}",
            "",
        ]

    for t in schema.types:
        for f in t.fields:
            if f.is_connection and f.relation_target not in emitted_connections:
                target = f.relation_target
                emitted_connections.add(target)
                lines += [
                    f"type {target}Edge {{",
                    "  cursor: String!",
                    f"  node: {target}!",
                    "}}",
                    "",
                    f"type {target}Connection {{",
                    f"  edges: [{target}Edge!]!",
                    "  pageInfo: PageInfo!",
                    "  totalCount: Int",
                    "}}",
                    "",
                ]

    for inp in schema.inputs:
        lines.append(f"input {inp.name} {{")
        for f in inp.fields:
            lines.append(f"  {f.name}: {_input_field_str(f)}")
        lines += ["}", ""]

    if schema.queries:
        lines.append("type Query {")
        for q in schema.queries:
            args = ", ".join(f"{a.name}: {_input_field_str(a)}" for a in q.args)
            desc = f'  """{q.description}"""\n' if q.description else ""
            lines.append(f"{desc}  {q.name}({args}): {q.return_type}")
        lines += ["}", ""]

    if schema.mutations:
        lines.append("type Mutation {")
        for m in schema.mutations:
            args = ", ".join(f"{a.name}: {_input_field_str(a)}" for a in m.args)
            desc = f'  """{m.description}"""\n' if m.description else ""
            lines.append(f"{desc}  {m.name}({args}): {m.return_type}")
        lines += ["}", ""]

    return "\n".join(lines) + "\n"


_MARKER = "AUTO-GENERATED by kybes"
