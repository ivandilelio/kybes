"""Runtime del contesto del tenant (Organization) per le tabelle multi-tenant, nei quattro linguaggi.

Regole comuni:
- il tenant si lega alla sessione (Session, EntityManager, DbContext) una volta, o con la Unit of Work;
- i repository delle tabelle con tenancy diversa da none lo leggono da lì e rifiutano di lavorare senza;
- tenant_key/schema_for/search_path_for/database_url_for instradano schema e database per tenant;
- su PostgreSQL la Unit of Work imposta app.tenant_id per la transazione (policy di row-level security).
"""
from __future__ import annotations

from naming import header

NAME_RULE = "minuscole, cifre e _, al massimo 48 caratteri"


# ------------------------------------------------------------------------------------------- Python

def python_file(id_type: str) -> str:
    if id_type == "uuid":
        coerce = (
            "    try:\n"
            "        return uuid.UUID(str(tenant))\n"
            "    except ValueError:\n"
            '        raise TenantError("tenant non valido: atteso un UUID") from None\n')
    else:
        coerce = (
            "    value = str(tenant)\n"
            "    if not value or len(value) > 64:\n"
            '        raise TenantError("tenant non valido: da 1 a 64 caratteri")\n'
            "    return value\n")
    key_py = ('    return str(coerce_tenant(tenant)).replace("-", "_")  # un UUID è sempre un nome valido\n' if id_type == "uuid" else
              '    key = str(coerce_tenant(tenant)).lower().replace("-", "_")\n'
              '    if not _NAME.match(key):\n'
              '        raise TenantError("tenant non utilizzabile come nome di schema o database")\n'
              '    return key\n')
    return header("python", "kit") + "# ruff: noqa\n" + '''"""Contesto del tenant (Organization) per le tabelle multi-tenant.

Il tenant si lega alla sessione una volta, con bind_tenant(session, tenant) o run_in_transaction(..., tenant=...):
i repository delle tabelle con tenancy diversa da none lo leggono dalla sessione e rifiutano di lavorare senza.
  column    ogni metodo filtra per TenantId; l'inserimento lo imposta; un padre di un altro tenant è rifiutato
  schema    la sessione va aperta su una connessione con search_path_for(tenant)
  database  la sessione va aperta sul database database_url_for(modello_url, tenant)
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

KEY = "kybes_tenant"
_NAME = re.compile(r"^[a-z0-9_]{1,48}$")


class TenantError(PermissionError):
    """Dati multi-tenant senza un tenant legato alla sessione, o con un tenant diverso."""


def coerce_tenant(tenant: Any) -> Any:
    """Il tenant nel tipo della colonna TenantId (''' + id_type + ''')."""
    if tenant is None:
        raise TenantError("tenant mancante")
''' + coerce + '''

def bind_tenant(session: Session, tenant: Any) -> None:
    """Lega il tenant alla sessione (None lo scollega)."""
    if tenant is None:
        session.info.pop(KEY, None)
    else:
        session.info[KEY] = coerce_tenant(tenant)


def tenant_of(session: Session) -> Any:
    tenant = session.info.get(KEY)
    if tenant is None:
        raise TenantError("sessione senza tenant: chiama bind_tenant(session, tenant) o usa run_in_transaction(..., tenant=...)")
    return tenant


def tenant_key(tenant: Any) -> str:
    """Il tenant come parte di un nome di schema o di database (''' + NAME_RULE + ''')."""
''' + key_py + '''

def schema_for(tenant: Any) -> str:
    return "tenant_" + tenant_key(tenant)


def search_path_for(tenant: Any) -> str:
    """search_path della connessione per le tabelle con tenancy: schema,
    es. create_engine(url, connect_args={"options": "-csearch_path=" + search_path_for(t)})."""
    return '"' + schema_for(tenant) + '", public'


def database_url_for(template: str, tenant: Any) -> str:
    """URL del database del tenant per le tabelle con tenancy: database; il modello contiene {tenant}."""
    if "{tenant}" not in template:
        raise TenantError("il modello dell'URL deve contenere {tenant}")
    return template.replace("{tenant}", tenant_key(tenant))


def apply_tenant_setting(session: Session) -> None:
    """PostgreSQL: app.tenant_id per la transazione corrente (usato dalle policy di row-level security)."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("select set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_of(session))})
'''


# ------------------------------------------------------------------------------------------- TypeScript

def typescript_file(id_type: str) -> str:
    key_ts = ('  return coerceTenant(tenant).replace(/-/g, "_"); // un UUID è sempre un nome valido\n' if id_type == "uuid" else
              '  const key = coerceTenant(tenant).toLowerCase().replace(/-/g, "_");\n'
              '  if (!/^[a-z0-9_]{1,48}$/.test(key)) throw new TenantError("tenant non utilizzabile come nome di schema o database");\n'
              '  return key;\n')
    check = ('  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) '
             'throw new TenantError("tenant non valido: atteso un UUID");\n  return value.toLowerCase();\n'
             if id_type == "uuid" else
             '  if (value.length === 0 || value.length > 64) throw new TenantError("tenant non valido: da 1 a 64 caratteri");\n  return value;\n')
    return header("typescript", "kit") + "/* eslint-disable */\n" + '''// Contesto del tenant (Organization) per le tabelle multi-tenant.
// Il tenant si lega all'EntityManager una volta, con bindTenant(em, tenant) o runInTransaction(ds, work, { tenant }):
// i repository delle tabelle con tenancy diversa da none lo leggono da lì e rifiutano di lavorare senza.
import type { EntityManager } from "typeorm";

export class TenantError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TenantError";
  }
}

const bound = new WeakMap<EntityManager, string>();

/** Il tenant nel formato della colonna TenantId (''' + id_type + '''). */
export function coerceTenant(tenant: unknown): string {
  if (tenant === null || tenant === undefined) throw new TenantError("tenant mancante");
  const value = String(tenant);
''' + check + '''}

/** Lega il tenant all'EntityManager (null lo scollega). */
export function bindTenant(em: EntityManager, tenant: unknown): void {
  if (tenant === null || tenant === undefined) bound.delete(em);
  else bound.set(em, coerceTenant(tenant));
}

export function tenantOf(em: EntityManager): string {
  const tenant = bound.get(em);
  if (tenant === undefined) {
    throw new TenantError("EntityManager senza tenant: chiama bindTenant(em, tenant) o usa runInTransaction(ds, work, { tenant })");
  }
  return tenant;
}

/** Il tenant come parte di un nome di schema o di database (''' + NAME_RULE + '''). */
export function tenantKey(tenant: unknown): string {
''' + key_ts + '''}

export function schemaFor(tenant: unknown): string {
  return "tenant_" + tenantKey(tenant);
}

/** search_path per le tabelle con tenancy: schema, es. new DataSource({ ..., extra: { options: `-c search_path=${searchPathFor(t)}` } }). */
export function searchPathFor(tenant: unknown): string {
  return `"${schemaFor(tenant)}", public`;
}

/** URL del database del tenant per le tabelle con tenancy: database; il modello contiene {tenant}. */
export function databaseUrlFor(template: string, tenant: unknown): string {
  if (!template.includes("{tenant}")) throw new TenantError("il modello dell'URL deve contenere {tenant}");
  return template.split("{tenant}").join(tenantKey(tenant));
}

/** PostgreSQL: app.tenant_id per la transazione corrente (policy di row-level security). */
export async function applyTenantSetting(em: EntityManager): Promise<void> {
  if (em.connection.options.type === "postgres") {
    await em.query("select set_config('app.tenant_id', $1, true)", [tenantOf(em)]);
  }
}
'''


# ------------------------------------------------------------------------------------------- Java

def java_file(pkg: str, id_type: str) -> str:
    jt = "UUID" if id_type == "uuid" else "String"
    coerce = ('''        try {
            return tenant instanceof UUID u ? u : UUID.fromString(String.valueOf(tenant));
        } catch (IllegalArgumentException e) {
            throw new TenantException("tenant non valido: atteso un UUID");
        }''' if id_type == "uuid" else '''        String value = String.valueOf(tenant);
        if (value.isEmpty() || value.length() > 64) throw new TenantException("tenant non valido: da 1 a 64 caratteri");
        return value;''')
    return header("java", "kit").rstrip("\n") + f'''
package {pkg}.generated;

import jakarta.persistence.EntityManager;
import java.util.Locale;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * Contesto del tenant (Organization) per le tabelle multi-tenant.
 * Il tenant si lega all'EntityManager una volta, con Tenancy.bind(em, tenant) o UnitOfWork.run(..., tenant):
 * i repository delle tabelle con tenancy diversa da none lo leggono da lì e rifiutano di lavorare senza.
 */
public final class Tenancy {{

    /** Proprietà dell'EntityManager che contiene il tenant. */
    public static final String KEY = "kybes.tenant";
    private static final Pattern NAME = Pattern.compile("^[a-z0-9_]{{1,48}}$");

    private Tenancy() {{
    }}

    /** Il tenant nel tipo della colonna TenantId ({id_type}). */
    public static {jt} coerce(Object tenant) {{
        if (tenant == null) throw new TenantException("tenant mancante");
{coerce}
    }}

    /** Lega il tenant all'EntityManager (null lo scollega). */
    public static void bind(EntityManager em, Object tenant) {{
        // Hibernate ignora i valori null nelle proprietà: "" vale come tenant non legato
        em.setProperty(KEY, tenant == null ? "" : coerce(tenant));
    }}

    public static {jt} of(EntityManager em) {{
        Object tenant = em.getProperties().get(KEY);
        if (tenant == null || "".equals(tenant)) {{
            throw new TenantException("EntityManager senza tenant: chiama Tenancy.bind(em, tenant) o usa UnitOfWork.run(..., tenant)");
        }}
        return ({jt}) tenant;
    }}

    /** Il tenant come parte di un nome di schema o di database ({NAME_RULE}). */
    public static String key(Object tenant) {{
        String key = String.valueOf(coerce(tenant)).toLowerCase(Locale.ROOT).replace('-', '_');
        if (!NAME.matcher(key).matches()) throw new TenantException("tenant non utilizzabile come nome di schema o database");
        return key;
    }}

    public static String schemaFor(Object tenant) {{
        return "tenant_" + key(tenant);
    }}

    /** search_path per le tabelle con tenancy: schema (es. URL JDBC con currentSchema=tenant_x,public). */
    public static String searchPathFor(Object tenant) {{
        return "\\"" + schemaFor(tenant) + "\\", public";
    }}

    /** URL del database del tenant per le tabelle con tenancy: database; il modello contiene {{tenant}}. */
    public static String databaseUrlFor(String template, Object tenant) {{
        if (!template.contains("{{tenant}}")) throw new TenantException("il modello dell'URL deve contenere {{tenant}}");
        return template.replace("{{tenant}}", key(tenant));
    }}

    /** PostgreSQL: app.tenant_id per la transazione corrente (policy di row-level security). */
    public static void applySetting(EntityManager em) {{
        em.createNativeQuery("SELECT set_config('app.tenant_id', ?1, true)").setParameter(1, String.valueOf(of(em))).getSingleResult();
    }}

    /** Dati multi-tenant senza un tenant legato, o con un tenant diverso. */
    public static final class TenantException extends RuntimeException {{
        private static final long serialVersionUID = 1L;

        public TenantException(String message) {{
            super(message);
        }}
    }}
}}
'''


# ------------------------------------------------------------------------------------------- C#

def csharp_file(ns: str, id_type: str) -> str:
    ct = "Guid" if id_type == "uuid" else "string"
    coerce = ('''        if (tenant is Guid g) return g;
        if (Guid.TryParse(tenant.ToString(), out var parsed)) return parsed;
        throw new TenantException("tenant non valido: atteso un UUID");''' if id_type == "uuid" else '''        var value = tenant.ToString() ?? "";
        if (value.Length == 0 || value.Length > 64) throw new TenantException("tenant non valido: da 1 a 64 caratteri");
        return value;''')
    return header("csharp", "kit") + f'''// <auto-generated />
#nullable enable
using System;
using System.Globalization;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;

namespace {ns};

/// <summary>Dati multi-tenant senza un tenant legato al contesto, o con un tenant diverso.</summary>
public sealed class TenantException : Exception
{{
    public TenantException(string message) : base(message) {{ }}
}}

/// <summary>
/// Contesto del tenant (Organization) per le tabelle multi-tenant.
/// Il tenant si lega all'AppDbContext una volta, con db.BindTenant(tenant) o UnitOfWork.RunAsync(..., tenant: ...):
/// i repository delle tabelle con tenancy diversa da none lo leggono da lì e rifiutano di lavorare senza.
/// </summary>
public static class Tenancy
{{
    private static readonly Regex Name = new("^[a-z0-9_]{{1,48}}$", RegexOptions.CultureInvariant);

    /// <summary>Il tenant nel tipo della colonna TenantId ({id_type}).</summary>
    public static {ct} Coerce(object? tenant)
    {{
        if (tenant is null) throw new TenantException("tenant mancante");
{coerce}
    }}

    /// <summary>Il tenant come parte di un nome di schema o di database ({NAME_RULE}).</summary>
    public static string Key(object? tenant)
    {{
        var key = Convert.ToString(Coerce(tenant), CultureInfo.InvariantCulture)!.ToLowerInvariant().Replace('-', '_');
        if (!Name.IsMatch(key)) throw new TenantException("tenant non utilizzabile come nome di schema o database");
        return key;
    }}

    public static string SchemaFor(object? tenant) => "tenant_" + Key(tenant);

    /// <summary>search_path per le tabelle con tenancy: schema (connection string Npgsql: Search Path=...).</summary>
    public static string SearchPathFor(object? tenant) => "\\"" + SchemaFor(tenant) + "\\", public";

    /// <summary>Connection string del database del tenant per le tabelle con tenancy: database; il modello contiene {{tenant}}.</summary>
    public static string DatabaseUrlFor(string template, object? tenant)
    {{
        if (!template.Contains("{{tenant}}", StringComparison.Ordinal)) throw new TenantException("il modello deve contenere {{tenant}}");
        return template.Replace("{{tenant}}", Key(tenant), StringComparison.Ordinal);
    }}

    /// <summary>PostgreSQL: app.tenant_id per la transazione corrente (policy di row-level security).</summary>
    public static Task ApplySettingAsync(AppDbContext db, CancellationToken ct = default) =>
        db.Database.ExecuteSqlRawAsync("SELECT set_config('app.tenant_id', {{0}}, true)", new object[] {{ db.RequireTenant().ToString()! }}, ct);
}}

public partial class AppDbContext
{{
    /// <summary>Il tenant legato a questo contesto, se c'è.</summary>
    public {ct}? KybesTenant {{ get; private set; }}

    /// <summary>Lega il tenant al contesto (null lo scollega).</summary>
    public void BindTenant(object? tenant) => KybesTenant = tenant is null ? null : Tenancy.Coerce(tenant);

    /// <summary>Il tenant legato; senza, l'operazione è rifiutata.</summary>
    public {ct} RequireTenant() =>
        KybesTenant ?? throw new TenantException("contesto senza tenant: chiama db.BindTenant(tenant) o usa UnitOfWork.RunAsync(..., tenant: ...)");
}}
'''
