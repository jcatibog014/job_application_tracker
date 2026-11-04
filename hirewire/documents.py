"""Documents: résumé and cover letter versions, as PDF or Word files.

A file is checked by its first bytes, not by its name: a PDF starts with
"%PDF-" and a .docx file is a zip ("PK"). Anything else is refused, so the
download link can only ever hand back a PDF or a Word file.
"""
import re

from . import forms
from .models import DOCUMENT_KINDS

MAX_SIZE = 2 * 1024 * 1024
TYPES = {
    "pdf": ("application/pdf", b"%PDF-"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK\x03\x04"),
}


def safe_filename(name, extension):
    """Only letters, digits, dot, dash and underscore; never a folder."""
    base = (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    base = re.sub(r"\.(pdf|docx)$", "", base, flags=re.IGNORECASE)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-")[:80] or "document"
    return f"{stem}.{extension}"


def read_file(upload):
    """An uploaded file -> (fields, None), or (None, problem)."""
    if upload is None or not upload.filename:
        return None, "Choose a PDF or Word (.docx) file."
    data = upload.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        return None, "That file is too big. Files can be up to 2 MB."
    for extension, (mime, start) in TYPES.items():
        if data.startswith(start) and (extension == "pdf" or upload.filename.lower().endswith(".docx")):
            return {"data": data, "size": len(data), "mime": mime,
                    "filename": safe_filename(upload.filename, extension)}, None
    return None, "Only PDF and Word (.docx) files can be added."


def read_form(form):
    """The name, kind and version label -> (values, errors)."""
    values, errors = {}, {}
    values["name"], problem = forms.text(form, "name", 120, required=True, label="A name")
    if problem:
        errors["name"] = problem
    values["version_label"], problem = forms.text(form, "version_label", 60)
    if problem:
        errors["version_label"] = problem
    values["kind"], problem = forms.choice(form, "kind", DOCUMENT_KINDS, default="resume")
    if problem:
        errors["kind"] = problem
    return values, errors


def size_words(size):
    return f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{max(1, round(size / 1024))} KB"
