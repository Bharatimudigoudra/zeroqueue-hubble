"""Attachments: turn an uploaded file into text the pipeline can use.

- .txt/.md/.json/.csv are read directly.
- Images (png/jpg/jpeg/webp/bmp/tiff) go through the free local
  Tesseract OCR. We try, in order: TESSERACT_CMD from .env, a plain
  "tesseract" on PATH, then the default Windows install folder
  (C:\\Program Files\\Tesseract-OCR\\tesseract.exe). Only if none of
  those works do we say OCR is unavailable.
- Anything else gets an honest 400: we say what we cannot read instead
  of pretending.

extract() returns (text, note) where note is the honest one-liner the UI
shows (e.g. "Read 42 words from receipt.png via OCR").
"""
import os
import subprocess
import uuid
from pathlib import Path
from typing import List, Tuple

from app import config


class UnsupportedFileError(Exception):
    """Raised for file types we honestly cannot read."""


TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".log"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# The default install location of the UB-Mannheim Windows build. Many
# Windows users install Tesseract there and never put it on PATH, so a
# bare "tesseract" fails even though OCR is installed.
_WINDOWS_DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_WINDOWS_DEFAULT_TESSERACT_X86 = r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"


def _clean(value: str) -> str:
    """Trim whitespace and any surrounding quotes from a configured path.

    Windows users often paste TESSERACT_CMD="C:\\Program Files\\..." with
    quotes (because of the space); subprocess wants the bare path.
    """
    return (value or "").strip().strip('"').strip("'").strip()


def _tesseract_available(cmd: str) -> bool:
    try:
        proc = subprocess.run([cmd, "--version"], capture_output=True, timeout=10)
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _tesseract_candidates() -> List[str]:
    """All the commands worth trying, best first, duplicates removed."""
    candidates: List[str] = []
    configured = _clean(config.TESSERACT_CMD)
    if configured:
        candidates.append(configured)
    candidates.append("tesseract")  # works when Tesseract is on PATH
    if os.name == "nt":
        candidates.append(_WINDOWS_DEFAULT_TESSERACT)
        candidates.append(_WINDOWS_DEFAULT_TESSERACT_X86)
    # De-duplicate while keeping order.
    seen, unique = set(), []
    for cmd in candidates:
        if cmd and cmd not in seen:
            seen.add(cmd)
            unique.append(cmd)
    return unique


def _resolve_tesseract() -> str:
    """Return the first Tesseract command that actually runs, or ""."""
    for cmd in _tesseract_candidates():
        if _tesseract_available(cmd):
            return cmd
    return ""


def extract(filename: str, data: bytes) -> Tuple[str, str]:
    ext = Path(filename or "").suffix.lower()

    if ext in TEXT_EXTS:
        text = data.decode("utf-8", errors="replace").strip()
        lines = len(text.splitlines()) if text else 0
        return text, f"Read {lines} line{'s' if lines != 1 else ''} from {filename}."

    if ext in IMAGE_EXTS:
        cmd = _resolve_tesseract()
        if not cmd:
            raise UnsupportedFileError(
                "This is an image, but the free Tesseract OCR is not "
                "installed (or TESSERACT_CMD in .env does not point at it). "
                "We also tried 'tesseract' on PATH and the default install "
                "folder (C:\\Program Files\\Tesseract-OCR). "
                "See the README for the one-time install step.")
        tmp = config.UPLOAD_DIR / f"upload-{Path(filename).name}"
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        try:
            # Call the binary directly ("tesseract <img> stdout") - no
            # wrapper package, works the same on Windows and Linux.
            proc = subprocess.run([cmd, str(tmp), "stdout"], capture_output=True,
                                  text=True, timeout=60)
            text = proc.stdout.strip()
        finally:
            tmp.unlink(missing_ok=True)
        words = len(text.split()) if text else 0
        note = (f"Read {words} words from {filename} via OCR." if text
                else f"Looked at {filename} with OCR but found no readable text.")
        return text, note

    raise UnsupportedFileError(
        f'I cannot read "{ext or "this"}" files yet. Text '
        "(.txt/.md/.json/.csv) and images (.png/.jpg) work.")


def save_upload(filename: str, data: bytes) -> dict:
    """Keep the uploaded file so the chat and the agent console can display
    it later. Returns {"url", "name", "kind"}; url is served from /uploads."""
    safe_name = (Path(filename or "").name or "attachment")
    ext = Path(safe_name).suffix.lower()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex[:12]}-{safe_name}"
    (config.UPLOAD_DIR / stored).write_bytes(data)
    kind = "image" if ext in IMAGE_EXTS else "file"
    return {"url": f"/uploads/{stored}", "name": safe_name, "kind": kind}
