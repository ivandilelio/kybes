"""Archivio a oggetti: file locali (sviluppo e test), Amazon S3, Azure Blob Storage.

I percorsi sono relativi alla radice dell'archivio (location), sempre con /.
  file:///percorso o /percorso                         cartella locale
  s3://bucket/prefisso                                 credenziali dalla catena standard di AWS (IRSA, variabili, profilo)
  az://container/prefisso                              account da AZURE_STORAGE_CONNECTION_STRING o AZURE_STORAGE_ACCOUNT_URL
  https://<account>.blob.core.windows.net/container/prefisso
{tenant} nella location (solo nel prefisso) dà a ogni Organization una radice separata.
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlparse

from .config import JobError


class Storage:
    """Interfaccia comune: put sovrascrive, get restituisce None se l'oggetto non esiste, delete è idempotente."""

    def put(self, path: str, data: bytes) -> None:
        raise NotImplementedError

    def get(self, path: str) -> Optional[bytes]:
        raise NotImplementedError

    def list(self, prefix: str) -> List[str]:
        raise NotImplementedError

    def delete(self, path: str) -> None:
        raise NotImplementedError


def _join(prefix: str, path: str) -> str:
    return f"{prefix}/{path}" if prefix else path


class FileStorage(Storage):
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def _p(self, path: str) -> Path:
        p = (self.root / path).resolve()
        if self.root.resolve() not in p.parents:
            raise JobError(f"percorso fuori dall'archivio: {path}")
        return p

    def put(self, path: str, data: bytes) -> None:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)  # scrittura atomica: un lettore vede il file intero o niente

    def get(self, path: str) -> Optional[bytes]:
        p = self._p(path)
        return p.read_bytes() if p.is_file() else None

    def list(self, prefix: str) -> List[str]:
        if not self.root.is_dir():
            return []
        out = [f.relative_to(self.root).as_posix() for f in self.root.rglob("*") if f.is_file() and not f.name.endswith(".tmp")]
        return sorted(x for x in out if x.startswith(prefix))

    def delete(self, path: str) -> None:
        p = self._p(path)
        if p.is_file():
            p.unlink()
            root, parent = self.root.resolve(), p.parent
            with contextlib.suppress(OSError):  # una cartella riempita nel frattempo resta
                while parent != root and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent


def _code(exc: BaseException) -> Any:
    """Codice di errore di boto3 (response.Error.Code) o di azure-core (status_code)."""
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        return resp.get("Error", {}).get("Code")
    return getattr(exc, "status_code", None)


class S3Storage(Storage):
    def __init__(self, client: Any, bucket: str, prefix: str = "") -> None:
        self.client, self.bucket, self.prefix = client, bucket, prefix.strip("/")

    def put(self, path: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=_join(self.prefix, path), Body=data)

    def get(self, path: str) -> Optional[bytes]:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=_join(self.prefix, path))["Body"].read()
        except Exception as exc:  # noqa: BLE001 - ClientError di boto3
            if _code(exc) in ("NoSuchKey", "404"):
                return None
            raise

    def list(self, prefix: str) -> List[str]:
        full = _join(self.prefix, prefix)
        cut = len(self.prefix) + 1 if self.prefix else 0
        out: List[str] = []
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=full):
            out += [o["Key"][cut:] for o in page.get("Contents", [])]
        return sorted(out)

    def delete(self, path: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_join(self.prefix, path))


class BlobStorage(Storage):
    def __init__(self, container: Any, prefix: str = "") -> None:
        self.container, self.prefix = container, prefix.strip("/")

    def put(self, path: str, data: bytes) -> None:
        self.container.upload_blob(_join(self.prefix, path), data, overwrite=True)

    def get(self, path: str) -> Optional[bytes]:
        try:
            return self.container.download_blob(_join(self.prefix, path)).readall()
        except Exception as exc:  # noqa: BLE001 - ResourceNotFoundError di azure-core
            if _code(exc) == 404:
                return None
            raise

    def list(self, prefix: str) -> List[str]:
        cut = len(self.prefix) + 1 if self.prefix else 0
        return sorted(b.name[cut:] for b in self.container.list_blobs(name_starts_with=_join(self.prefix, prefix)))

    def delete(self, path: str) -> None:
        try:
            self.container.delete_blob(_join(self.prefix, path))
        except Exception as exc:  # noqa: BLE001
            if _code(exc) != 404:
                raise


def _blob_service(account_url: Optional[str]) -> Any:
    from azure.storage.blob import BlobServiceClient
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if conn:
        return BlobServiceClient.from_connection_string(conn)
    account_url = account_url or os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
    if not account_url:
        raise JobError("az://: imposta AZURE_STORAGE_CONNECTION_STRING o AZURE_STORAGE_ACCOUNT_URL")
    from azure.identity import DefaultAzureCredential
    return BlobServiceClient(account_url, credential=DefaultAzureCredential())


def open_storage(location: str, tenant_segment: Optional[str] = None) -> Storage:
    """Apre l'archivio della location; {tenant} è sostituito dal segmento del tenant."""
    if "{tenant}" in location:
        if tenant_segment is None:
            raise JobError("la location contiene {tenant} ma la tabella non è multi-tenant")
        location = location.replace("{tenant}", tenant_segment)
    u = urlparse(location)
    path = u.path.strip("/")
    if u.scheme == "s3":
        import boto3
        return S3Storage(boto3.client("s3"), u.netloc, path)
    if u.scheme == "az":
        return BlobStorage(_blob_service(None).get_container_client(u.netloc), path)
    if u.scheme == "https" and u.netloc.endswith(".blob.core.windows.net"):
        container, _, prefix = path.partition("/")
        return BlobStorage(_blob_service(f"https://{u.netloc}").get_container_client(container), prefix)
    if u.scheme in ("", "file"):
        return FileStorage(u.path if u.scheme else location)
    raise JobError(f"location non supportata: {location} (ammesse: s3://, az://, https://<account>.blob.core.windows.net/, file://)")
