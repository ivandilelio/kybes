// Modulo errori condiviso (TypeScript). Punto unico per rollback, accodamento e risposte sicure.
import { randomUUID } from "node:crypto";

export type ErrorKind = "VALIDATION" | "AUTH" | "FORBIDDEN" | "NOT_FOUND" | "CONFLICT" | "TRANSIENT" | "INTERNAL";

const STATUS: Record<ErrorKind, number> = {
  VALIDATION: 400, AUTH: 401, FORBIDDEN: 403, NOT_FOUND: 404, CONFLICT: 409, TRANSIENT: 503, INTERNAL: 500,
};
const PUBLIC_MESSAGE: Record<ErrorKind, string> = {
  VALIDATION: "Richiesta non valida", AUTH: "Autenticazione richiesta", FORBIDDEN: "Operazione non consentita",
  NOT_FOUND: "Risorsa non trovata", CONFLICT: "Conflitto con lo stato attuale",
  TRANSIENT: "Servizio temporaneamente non disponibile", INTERNAL: "Errore interno",
};

export class AppError extends Error {
  constructor(public kind: ErrorKind, public code: string, public detail = "", public fields: Record<string, string> = {}) {
    super(detail || code);
  }
}

export function correlationId(headers: Record<string, string | undefined> = {}): string {
  const h = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
  return h["x-correlation-id"] ?? randomUUID();
}

export interface SafeErrorResponse { status: number; headers: Record<string, string>; body: unknown }

export function toResponse(err: unknown, cid: string, enqueue?: () => Promise<void> | void): SafeErrorResponse {
  const app = err instanceof AppError ? err : new AppError("INTERNAL", "UNEXPECTED");
  // il dettaglio completo va solo nei log, legato al correlationId
  console.error(JSON.stringify({ level: "error", correlationId: cid, kind: app.kind, code: app.code, cause: String(err) }));
  if (app.kind === "TRANSIENT" && enqueue) void enqueue();
  const error: Record<string, unknown> = { code: app.code, message: PUBLIC_MESSAGE[app.kind], correlationId: cid };
  if (app.kind === "VALIDATION" && Object.keys(app.fields).length) error.fields = app.fields;
  return { status: STATUS[app.kind], headers: { "x-correlation-id": cid }, body: { error } };
}
