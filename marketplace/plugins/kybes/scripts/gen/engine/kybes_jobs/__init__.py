"""Motore dei job di kybes: archiviazione hot → cold (Parquet su S3 o Blob) e conservazione (TTL).

Un job lavora su una tabella, descritta da jobs/generated/<t>-archive/config.json (o <t>-retention):
  python -m kybes_jobs run jobs/generated/ordini-archive/config.json [--loop]

Lo spostamento è sicuro in ogni passo: i file Parquet sono scritti in un'area di staging e verificati
(righe, chiavi e SHA-256); le righe sono cancellate dalla tabella hot nella stessa transazione che registra
il passaggio in kybes_archive_runs; solo dopo il commit i file passano nella posizione definitiva.
Se un passo fallisce prima del commit le righe restano nella tabella hot e lo staging viene scartato;
se fallisce dopo, il job successivo completa lo spostamento (recupero).
"""
from .config import JobConfig, JobError, load_config, subtract
from .engine import Job, Report
from .storage import FileStorage, Storage, open_storage

__all__ = ["FileStorage", "Job", "JobConfig", "JobError", "Report", "Storage", "load_config", "open_storage", "subtract"]
