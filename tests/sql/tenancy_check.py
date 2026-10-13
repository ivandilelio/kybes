#!/usr/bin/env python3
"""Verifica su PostgreSQL reale del DDL multi-tenant generato (CI del kit).

  tenancy_check.py <progetto con tabelle column> <progetto con tabelle schema e database>

Usa KYBES_TEST_DATABASE_URL (utente con diritti di creare database e ruoli) e psycopg 3.
1. row-level security: con un ruolo senza BYPASSRLS ogni tenant vede e scrive solo le proprie righe;
2. schema per tenant: kybes_create_tenant_schema crea schema e tabelle, con le chiavi verso le tabelle condivise;
3. database per tenant: il DDL crea le tabelle in un database nuovo.
"""
import os
import sys
import uuid
from pathlib import Path

import psycopg

URL = os.environ["KYBES_TEST_DATABASE_URL"]
ADMIN = psycopg.connect(URL, autocommit=True)


def fresh(name: str) -> str:
    ADMIN.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    ADMIN.execute(f'CREATE DATABASE "{name}"')
    return URL.rsplit("/", 1)[0] + "/" + name


def check(ok: bool, msg: str) -> None:
    if not ok:
        raise AssertionError(msg)
    print("  ok  ", msg)


def rls(proj: Path) -> None:
    url = fresh("kybes_rls")
    with psycopg.connect(url, autocommit=True) as c:
        c.execute((proj / "db/generated/ddl/postgres/_all.sql").read_text())
        c.execute((proj / "db/generated/tenancy/_rls.sql").read_text())
        c.execute("DO $$ BEGIN CREATE ROLE kybes_app NOLOGIN NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
        c.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO kybes_app")
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    def as_tenant(tenant, sql, params=()):
        with psycopg.connect(url) as c:
            c.execute("SET ROLE kybes_app")
            if tenant:
                c.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
            cur = c.execute(sql, params)
            return cur.fetchall() if cur.description else None

    as_tenant(a, "INSERT INTO clienti (id, tenant_id, ragione_sociale) VALUES (%s, %s, 'Alfa')", (str(uuid.uuid4()), a))
    check(as_tenant(a, "SELECT count(*) FROM clienti")[0][0] == 1, "RLS: il tenant A vede la propria riga")
    check(as_tenant(b, "SELECT count(*) FROM clienti")[0][0] == 0, "RLS: il tenant B non vede le righe di A")
    check(as_tenant(None, "SELECT count(*) FROM clienti")[0][0] == 0, "RLS: senza app.tenant_id non si vede nulla")
    try:
        as_tenant(b, "INSERT INTO clienti (id, tenant_id, ragione_sociale) VALUES (%s, %s, 'Intrusa')", (str(uuid.uuid4()), a))
        check(False, "RLS: il tenant B non può scrivere righe di A")
    except psycopg.errors.InsufficientPrivilege:
        check(True, "RLS: il tenant B non può scrivere righe di A")


def schema_per_tenant(proj: Path) -> None:
    url = fresh("kybes_schema")
    with psycopg.connect(url, autocommit=True) as c:
        c.execute((proj / "db/generated/ddl/postgres/_all.sql").read_text())
        c.execute((proj / "db/generated/tenancy/_schema_per_tenant.sql").read_text())
        for s in ("tenant_x", "tenant_y"):
            c.execute("SELECT kybes_create_tenant_schema(%s)", (s,))
        rows = c.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema LIKE 'tenant_%' "
                         "ORDER BY 1, 2").fetchall()
        check(rows == [("tenant_x", "documenti"), ("tenant_x", "fascicoli"), ("tenant_y", "documenti"), ("tenant_y", "fascicoli")],
              f"schema per tenant: tabelle create in due schemi ({rows})")
        try:
            c.execute("SELECT kybes_create_tenant_schema('public; drop table x')")
            check(False, "schema per tenant: nome non valido rifiutato")
        except psycopg.errors.RaiseException:
            check(True, "schema per tenant: nome non valido rifiutato")
        tip = str(uuid.uuid4())
        c.execute("INSERT INTO tipologie (id, nome) VALUES (%s, 'Contratti')", (tip,))
        c.execute('SET search_path = "tenant_x", public')
        c.execute("INSERT INTO fascicoli (id, titolo, tipologia_id) VALUES (%s, 'F1', %s)", (str(uuid.uuid4()), tip))
        check(c.execute("SELECT count(*) FROM fascicoli").fetchone()[0] == 1, "schema per tenant: il fascicolo è nello schema di x")
        c.execute('SET search_path = "tenant_y", public')
        check(c.execute("SELECT count(*) FROM fascicoli").fetchone()[0] == 0, "schema per tenant: lo schema di y è separato")
        try:
            c.execute("INSERT INTO fascicoli (id, titolo, tipologia_id) VALUES (%s, 'F2', %s)", (str(uuid.uuid4()), str(uuid.uuid4())))
            check(False, "schema per tenant: chiave verso una tipologia condivisa inesistente rifiutata")
        except psycopg.errors.ForeignKeyViolation:
            check(True, "schema per tenant: chiave verso una tipologia condivisa inesistente rifiutata")


def database_per_tenant(proj: Path) -> None:
    url = fresh("kybes_tenant_x")
    with psycopg.connect(url, autocommit=True) as c:
        c.execute((proj / "db/generated/tenancy/_database_per_tenant.sql").read_text())
        rows = [r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY 1")]
        check(rows == ["registri", "voci"], f"database per tenant: tabelle create ({rows})")


if __name__ == "__main__":
    column_proj, physical_proj = Path(sys.argv[1]), Path(sys.argv[2])
    rls(column_proj)
    schema_per_tenant(physical_proj)
    database_per_tenant(physical_proj)
    print("TENANCY SQL OK")
