"""Modulo errori condiviso (Python). Punto unico per rollback, accodamento e risposte sicure."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("app")

STATUS = {"VALIDATION": 400, "AUTH": 401, "FORBIDDEN": 403, "NOT_FOUND": 404,
          "CONFLICT": 409, "TRANSIENT": 503, "INTERNAL": 500}
PUBLIC_MESSAGE = {"VALIDATION": "Richiesta non valida", "AUTH": "Autenticazione richiesta",
                  "FORBIDDEN": "Operazione non consentita", "NOT_FOUND": "Risorsa non trovata",
                  "CONFLICT": "Conflitto con lo stato attuale", "TRANSIENT": "Servizio temporaneamente non disponibile",
                  "INTERNAL": "Errore interno"}


class AppError(Exception):
    def __init__(self, kind: str, code: str, detail: str = "", fields: Optional[Dict[str, str]] = None):
        super().__init__(detail or code)
        self.kind, self.code, self.detail, self.fields = kind, code, detail, fields or {}


def correlation_id(headers: Optional[Dict[str, str]]) -> str:
    h = {k.lower(): v for k, v in (headers or {}).items()}
    return h.get("x-correlation-id") or str(uuid.uuid4())


def to_response(err: Exception, cid: str, enqueue: Optional[Callable[[], None]] = None) -> Dict[str, Any]:
    """Converte qualsiasi eccezione in una risposta che non espone dettagli interni."""
    app = err if isinstance(err, AppError) else AppError("INTERNAL", "UNEXPECTED")
    log.error("request failed", extra={"correlationId": cid, "kind": app.kind, "code": app.code}, exc_info=err)
    if app.kind == "TRANSIENT" and enqueue:
        enqueue()  # la richiesta viene riprocessata più tardi
    body = {"error": {"code": app.code, "message": PUBLIC_MESSAGE[app.kind], "correlationId": cid}}
    if app.kind == "VALIDATION" and app.fields:
        body["error"]["fields"] = app.fields  # solo nomi di campo e regole violate, mai valori interni
    return {"statusCode": STATUS[app.kind], "headers": {"x-correlation-id": cid}, "body": json.dumps(body)}
