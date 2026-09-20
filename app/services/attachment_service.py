"""Attachments: turn an uploaded file into text the pipeline can use.

- .txt/.md/.json/.csv are read directly.
- Images (png/jpg/jpeg/webp/bmp/tiff) go through the free local
  Tesseract OCR if it is installed (TESSERACT_CMD or on PATH).
- Anything else gets an honest 400: we say what we cannot read instead
  of pretending.

extract() returns (text, note) where note is the honest one-liner the UI
shows (e.g. "Read 42 words from receipt.png via OCR").
"""
import subprocess
from pathlib import Path
from typing import Tuple

from app import config


class UnsupportedFileError(Exception):
    """Raised for file types we honestly cannot read."""


TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".log"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _tesseract_available(cmd: str) -> bool:
    try:
        subprocess.run([cmd, "--version"], capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def extract(filename: str, data: bytes) -> Tuple[str, str]:
    ext = Path(filename or "").suffix.lower()

    if ext in TEXT_EXTS:
        text = data.decode("utf-8", errors="replace").strip()
        lines = len(text.splitlines()) if text else 0
        return text, f"Read {lines} line{'s' if lines != 1 else ''} from {filename}."

    if ext in IMAGE_EXTS:
        cmd = config.TESSERACT_CMD or "tesseract"
        if not _tesseract_available(cmd):
            raise UnsupportedFileError(
                "This is an image, but the free Tesseract OCR is not "
                "installed (or TESSERACT_CMD in .env does not point at it). "
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
