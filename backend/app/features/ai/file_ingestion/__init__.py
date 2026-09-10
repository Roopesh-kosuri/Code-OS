"""File ingestion package for Code-OS AI."""
from .service import (
    ingest_file,
    save_uploaded_file,
    get_uploaded_file,
    list_uploaded_files,
    delete_uploaded_file,
    format_attached_files_xml,
)

__all__ = [
    "ingest_file",
    "save_uploaded_file",
    "get_uploaded_file",
    "list_uploaded_files",
    "delete_uploaded_file",
    "format_attached_files_xml",
]
