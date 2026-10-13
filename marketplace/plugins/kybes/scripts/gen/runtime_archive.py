"""Runtime della lettura dall'archivio (archive.read_through) nei quattro linguaggi.

Regole comuni:
- il lettore dell'archivio (ArchiveReader: fetch(percorso) -> byte o nulla) si lega alla sessione, come il tenant;
- getById cerca nella tabella hot e, se il record non c'è e un lettore è legato, l'oggetto per chiave scritto dal job:
  <tabella>/_keys/[tenant=<tenant>/]<chiave>.json, con tenant e chiave codificati da archiveSegment;
- il record archiviato è restituito come oggetto non collegato alla sessione, in sola lettura;
- FileArchiveReader legge da una cartella (sviluppo e test); per S3 e Blob si implementa fetch con l'SDK del cloud.
Formato: uuid in minuscolo, decimal e bigint come stringa, date AAAA-MM-GG, datetime ISO 8601 UTC, json come valore JSON.
"""
from __future__ import annotations

from naming import header


def python_file() -> str:
    return header("python", "kit") + "# ruff: noqa\n" + '''"""Lettura dall'archivio per le tabelle con archive.read_through (vedi docs/archivio.md).

    bind_archive(session, FileArchiveReader("/percorso/archivio"))   # o un lettore S3/Blob con fetch(path)
    Repository(session).get_by_id(id)   # hot, poi archivio: record non collegato alla sessione, in sola lettura
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from sqlalchemy.orm import Session

KEY = "kybes_archive"
_SAFE = re.compile(r"[A-Za-z0-9_-]")


class ArchiveReader(Protocol):
    def fetch(self, path: str) -> Optional[bytes]:
        """Contenuto dell'oggetto (percorso relativo alla radice dell'archivio) o None se non esiste."""


class FileArchiveReader:
    """Archivio in una cartella locale (sviluppo e test): la stessa struttura di S3 e Blob."""

    def __init__(self, root: Any) -> None:
        self.root = Path(root).resolve()

    def fetch(self, path: str) -> Optional[bytes]:
        p = (self.root / path).resolve()
        if self.root not in p.parents:
            raise ValueError(f"percorso fuori dall'archivio: {path}")
        return p.read_bytes() if p.is_file() else None


def archive_segment(value: Any) -> str:
    """Tenant e chiave nel percorso: lettere, cifre, _ e - restano, il resto diventa %XX (UTF-8), come nel job."""
    return "".join(ch if _SAFE.fullmatch(ch) else "".join(f"%{b:02X}" for b in ch.encode("utf-8")) for ch in str(value))


def archive_path(table: str, tenant: Any, key: Any) -> str:
    folder = f"tenant={archive_segment(tenant)}/" if tenant is not None else ""
    return f"{table}/_keys/{folder}{archive_segment(key)}.json"


def bind_archive(session: Session, reader: Optional[ArchiveReader]) -> None:
    """Lega il lettore dell'archivio alla sessione (None lo scollega)."""
    if reader is None:
        session.info.pop(KEY, None)
    else:
        session.info[KEY] = reader


def archive_of(session: Session) -> Optional[ArchiveReader]:
    return session.info.get(KEY)


def read_archived(session: Session, table: str, tenant: Any, key: Any) -> Optional[Dict[str, Any]]:
    reader = archive_of(session)
    if reader is None:
        return None
    data = reader.fetch(archive_path(table, tenant, key))
    return None if data is None else json.loads(data)


# decodifica dei valori del formato dell'archivio
def as_uuid(v: Any) -> Optional[uuid.UUID]:
    return None if v is None else uuid.UUID(v)


def as_int(v: Any) -> Optional[int]:
    return None if v is None else int(v)


def as_decimal(v: Any) -> Optional[Decimal]:
    return None if v is None else Decimal(v)


def as_date(v: Any) -> Optional[date]:
    return None if v is None else date.fromisoformat(v)


def as_datetime(v: Any) -> Optional[datetime]:
    return None if v is None else datetime.fromisoformat(v)
'''


PY_DECODE = {"uuid": "as_uuid", "bigint": "as_int", "decimal": "as_decimal", "date": "as_date", "datetime": "as_datetime"}


def typescript_file() -> str:
    return header("typescript", "kit") + "/* eslint-disable */\n" + '''// Lettura dall'archivio per le tabelle con archive.read_through (vedi docs/archivio.md).
//   bindArchive(em, new FileArchiveReader("/percorso/archivio"));   // o un lettore S3/Blob con fetch(path)
//   await new Repository(em).getById(id);   // hot, poi archivio: record non collegato all'EntityManager, in sola lettura
import { existsSync, readFileSync } from "node:fs";
import { resolve, sep } from "node:path";
import type { EntityManager } from "typeorm";

export interface ArchiveReader {
  /** Contenuto dell'oggetto (percorso relativo alla radice dell'archivio) o null se non esiste. */
  fetch(path: string): Promise<Uint8Array | null>;
}

/** Archivio in una cartella locale (sviluppo e test): la stessa struttura di S3 e Blob. */
export class FileArchiveReader implements ArchiveReader {
  private readonly root: string;

  constructor(root: string) {
    this.root = resolve(root);
  }

  async fetch(path: string): Promise<Uint8Array | null> {
    const full = resolve(this.root, path);
    if (!full.startsWith(this.root + sep)) throw new Error(`percorso fuori dall'archivio: ${path}`);
    return existsSync(full) ? readFileSync(full) : null;
  }
}

const bound = new WeakMap<EntityManager, ArchiveReader>();

/** Lega il lettore dell'archivio all'EntityManager (null lo scollega). */
export function bindArchive(em: EntityManager, reader: ArchiveReader | null): void {
  if (reader === null) bound.delete(em);
  else bound.set(em, reader);
}

export function archiveOf(em: EntityManager): ArchiveReader | null {
  return bound.get(em) ?? null;
}

/** Tenant e chiave nel percorso: lettere, cifre, _ e - restano, il resto diventa %XX (UTF-8), come nel job. */
export function archiveSegment(value: unknown): string {
  let out = "";
  for (const ch of String(value)) {
    if (/^[A-Za-z0-9_-]$/.test(ch)) out += ch;
    else for (const b of Buffer.from(ch, "utf8")) out += "%" + b.toString(16).toUpperCase().padStart(2, "0");
  }
  return out;
}

export function archivePath(table: string, tenant: string | null, key: unknown): string {
  const folder = tenant === null ? "" : `tenant=${archiveSegment(tenant)}/`;
  return `${table}/_keys/${folder}${archiveSegment(key)}.json`;
}

export async function readArchived(em: EntityManager, table: string, tenant: string | null, key: unknown): Promise<Record<string, unknown> | null> {
  const reader = archiveOf(em);
  if (reader === null) return null;
  const data = await reader.fetch(archivePath(table, tenant, key));
  return data === null ? null : (JSON.parse(Buffer.from(data).toString("utf8")) as Record<string, unknown>);
}

/** datetime del formato dell'archivio (ISO 8601 UTC); uuid, decimal, bigint e date restano stringhe come nel modello. */
export function asDateTime(v: unknown): Date | null {
  return v === null ? null : new Date(String(v));
}
'''


def java_file(pkg: str) -> str:
    return header("java", "kit") + f"package {pkg}.generated;\n\n" + '''import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.persistence.EntityManager;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.Collections;
import java.util.Map;
import java.util.UUID;
import java.util.WeakHashMap;

/**
 * Lettura dall'archivio per le tabelle con archive.read_through (vedi docs/archivio.md).
 * <pre>
 * Archive.bind(em, new Archive.FileReader(Path.of("/percorso/archivio")));   // o un Reader S3/Blob
 * new Repository(em).getById(id);   // hot, poi archivio: entità non gestita dall'EntityManager, in sola lettura
 * </pre>
 */
public final class Archive {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Map<EntityManager, Reader> BOUND = Collections.synchronizedMap(new WeakHashMap<>());

    private Archive() { }

    /** Legge un oggetto dell'archivio (percorso relativo alla radice); null se non esiste. */
    @FunctionalInterface
    public interface Reader {
        byte[] fetch(String path) throws IOException;
    }

    /** Archivio in una cartella locale (sviluppo e test): la stessa struttura di S3 e Blob. */
    public static final class FileReader implements Reader {
        private final Path root;

        public FileReader(Path root) {
            this.root = root.toAbsolutePath().normalize();
        }

        @Override
        public byte[] fetch(String path) throws IOException {
            Path p = root.resolve(path).normalize();
            if (!p.startsWith(root) || p.equals(root)) throw new IllegalArgumentException("percorso fuori dall'archivio: " + path);
            return Files.isRegularFile(p) ? Files.readAllBytes(p) : null;
        }
    }

    /** Lega il lettore dell'archivio all'EntityManager (null lo scollega). */
    public static void bind(EntityManager em, Reader reader) {
        if (reader == null) BOUND.remove(em);
        else BOUND.put(em, reader);
    }

    public static Reader of(EntityManager em) {
        return BOUND.get(em);
    }

    /** Tenant e chiave nel percorso: lettere, cifre, _ e - restano, il resto diventa %XX (UTF-8), come nel job. */
    public static String segment(Object value) {
        StringBuilder out = new StringBuilder();
        String s = String.valueOf(value);
        for (int i = 0; i < s.length(); ) {
            int cp = s.codePointAt(i);
            boolean safe = cp < 128 && (Character.isLetterOrDigit(cp) || cp == '_' || cp == '-');
            if (safe) out.appendCodePoint(cp);
            else for (byte b : new String(Character.toChars(cp)).getBytes(StandardCharsets.UTF_8)) out.append(String.format("%%%02X", b & 0xff));
            i += Character.charCount(cp);
        }
        return out.toString();
    }

    public static String path(String table, Object tenant, Object key) {
        String folder = tenant == null ? "" : "tenant=" + segment(tenant) + "/";
        return table + "/_keys/" + folder + segment(key) + ".json";
    }

    /** L'oggetto per chiave come JSON, o null se nessun lettore è legato o l'oggetto non esiste. */
    public static JsonNode read(EntityManager em, String table, Object tenant, Object key) {
        Reader reader = of(em);
        if (reader == null) return null;
        try {
            byte[] data = reader.fetch(path(table, tenant, key));
            return data == null ? null : MAPPER.readTree(data);
        } catch (IOException e) {
            throw new UncheckedIOException("archivio illeggibile: " + path(table, tenant, key), e);
        }
    }

    // decodifica dei valori del formato dell'archivio: assente o null JSON = null
    private static boolean missing(JsonNode v) {
        return v == null || v.isNull();
    }

    public static UUID uuid(JsonNode v) {
        return missing(v) ? null : UUID.fromString(v.asText());
    }

    public static String text(JsonNode v) {
        return missing(v) ? null : v.asText();
    }

    public static Integer integer(JsonNode v) {
        return missing(v) ? null : v.asInt();
    }

    public static Long bigint(JsonNode v) {
        return missing(v) ? null : Long.parseLong(v.asText());
    }

    public static BigDecimal decimal(JsonNode v) {
        return missing(v) ? null : new BigDecimal(v.asText());
    }

    public static Boolean bool(JsonNode v) {
        return missing(v) ? null : v.asBoolean();
    }

    public static LocalDate date(JsonNode v) {
        return missing(v) ? null : LocalDate.parse(v.asText());
    }

    public static OffsetDateTime datetime(JsonNode v) {
        return missing(v) ? null : OffsetDateTime.parse(v.asText());
    }

    /** json: il valore JSON come testo, come la colonna del modello. */
    public static String json(JsonNode v) {
        return missing(v) ? null : v.toString();
    }
}
'''


JAVA_DECODE = {"uuid": "uuid", "string": "text", "text": "text", "int": "integer", "bigint": "bigint", "decimal": "decimal",
               "bool": "bool", "date": "date", "datetime": "datetime", "json": "json"}


def csharp_file(ns: str) -> str:
    return header("csharp", "kit") + f'''// <auto-generated />
#nullable enable
using System;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace {ns};

/// <summary>Legge un oggetto dell'archivio (percorso relativo alla radice); null se non esiste.</summary>
public interface IArchiveReader
{{
    Task<byte[]?> FetchAsync(string path, CancellationToken ct = default);
}}

/// <summary>Archivio in una cartella locale (sviluppo e test): la stessa struttura di S3 e Blob.</summary>
public sealed class FileArchiveReader : IArchiveReader
{{
    private readonly string root;

    public FileArchiveReader(string root) => this.root = Path.GetFullPath(root);

    public async Task<byte[]?> FetchAsync(string path, CancellationToken ct = default)
    {{
        var full = Path.GetFullPath(Path.Combine(root, path));
        if (!full.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            throw new ArgumentException("percorso fuori dall'archivio: " + path, nameof(path));
        return File.Exists(full) ? await File.ReadAllBytesAsync(full, ct) : null;
    }}
}}

/// <summary>
/// Lettura dall'archivio per le tabelle con archive.read_through (vedi docs/archivio.md).
/// db.BindArchive(new FileArchiveReader("/percorso/archivio")) (o un lettore S3/Blob), poi GetByIdAsync cerca nella
/// tabella hot e poi nell'archivio: il record archiviato non è tracciato dal contesto ed è in sola lettura.
/// </summary>
public static class Archive
{{
    private static readonly JsonSerializerOptions Options = new() {{ NumberHandling = JsonNumberHandling.AllowReadingFromString }};

    /// <summary>Tenant e chiave nel percorso: lettere, cifre, _ e - restano, il resto diventa %XX (UTF-8), come nel job.</summary>
    public static string Segment(object value)
    {{
        var sb = new StringBuilder();
        Span<byte> buf = stackalloc byte[4];
        foreach (var rune in Convert.ToString(value, CultureInfo.InvariantCulture)!.EnumerateRunes())
        {{
            if (rune.IsAscii && (char.IsAsciiLetterOrDigit((char)rune.Value) || rune.Value == '_' || rune.Value == '-'))
            {{
                sb.Append((char)rune.Value);
                continue;
            }}
            var n = rune.EncodeToUtf8(buf);
            for (var i = 0; i < n; i++) sb.Append('%').Append(buf[i].ToString("X2", CultureInfo.InvariantCulture));
        }}
        return sb.ToString();
    }}

    public static string PathOf(string table, object? tenant, object key) =>
        table + "/_keys/" + (tenant is null ? "" : "tenant=" + Segment(tenant) + "/") + Segment(key) + ".json";

    /// <summary>L'oggetto per chiave, o null se nessun lettore è legato o l'oggetto non esiste.</summary>
    public static async Task<JsonElement?> ReadAsync(AppDbContext db, string table, object? tenant, object key, CancellationToken ct = default)
    {{
        if (db.KybesArchive is not {{ }} reader) return null;
        var data = await reader.FetchAsync(PathOf(table, tenant, key), ct);
        if (data is null) return null;
        using var doc = JsonDocument.Parse(data);
        return doc.RootElement.Clone();
    }}

    /// <summary>Valore di una colonna nel tipo della proprietà (decimal e bigint arrivano come stringa).</summary>
    public static T Get<T>(JsonElement doc, string name) => doc.GetProperty(name).Deserialize<T>(Options)!;

    /// <summary>json: il valore JSON come testo, come la proprietà del modello.</summary>
    public static string? Json(JsonElement doc, string name)
    {{
        var v = doc.GetProperty(name);
        return v.ValueKind == JsonValueKind.Null ? null : v.GetRawText();
    }}
}}

public partial class AppDbContext
{{
    /// <summary>Il lettore dell'archivio legato a questo contesto, se c'è.</summary>
    public IArchiveReader? KybesArchive {{ get; private set; }}

    /// <summary>Lega il lettore dell'archivio al contesto (null lo scollega).</summary>
    public void BindArchive(IArchiveReader? reader) => KybesArchive = reader;
}}
'''
