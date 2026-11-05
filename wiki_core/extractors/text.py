from __future__ import annotations

import csv
import email
import io
import os
import selectors
import subprocess
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExtractedDocument:
    source: str
    source_type: str
    text: str
    units: list[dict[str, object]]
    warnings: list[str]


def _looks_binary(data: bytes) -> bool:
    """Heuristic: NUL bytes or a high fraction of non-text bytes indicate binary."""
    if b"\x00" in data:
        return True
    if not data:
        return False
    sample = data[:4096]
    text_bytes = bytes(range(0x20, 0x7F)) + b"\n\r\t\f\b"
    nontext = sum(1 for b in sample if b not in text_bytes)
    return (nontext / len(sample)) > 0.30


def _read_text(path: Path) -> tuple[str, list[str]]:
    """Read text, but refuse to return the raw bytes of a binary file."""
    raw = path.read_bytes()
    if _looks_binary(raw):
        return "", [f"unsupported_binary_source:{path.suffix or 'no-ext'}"]
    return raw.decode("utf-8", errors="replace"), []


def _extract_pdf(path: Path) -> tuple[str, list[dict[str, object]], list[str]]:
    warnings: list[str] = []
    try:
        output = subprocess.check_output(
            ["pdftotext", "-layout", str(path), "-"], text=True, stderr=subprocess.PIPE
        )
    except FileNotFoundError:
        # Missing system dependency: do NOT return raw bytes (would pollute the index).
        return "", [], ["pdftotext_unavailable:install_poppler"]
    except subprocess.CalledProcessError as exc:
        return "", [], [f"pdftotext_failed:{exc}"]
    units = [{"unit_id": "pdf-full-text", "kind": "pdf_text", "text": output}]
    if not output.strip():
        warnings.append("empty_text_extraction")
    return output, units, warnings


def _extract_csv(path: Path) -> tuple[str, list[dict[str, object]], list[str]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        return _extract_csv_stream(handle, path.suffix)


def _extract_csv_stream(handle, suffix: str, *, bounded: bool = False):
    rows: list[str] = []
    units: list[dict[str, object]] = []
    dialect = "excel-tab" if suffix.lower() == ".tsv" else "excel"
    size = 0
    for index, row in enumerate(csv.reader(handle, dialect=dialect), start=1):
        line = " | ".join(row)
        size += len(line.encode('utf-8')) + 1
        if bounded and (index > 100_000 or size > 2_000_000):
            raise ValueError('extracted content exceeds protected limit')
        rows.append(line)
        units.append({"unit_id": f"row-{index}", "kind": "table_row", "row": index, "text": line})
    return "\n".join(rows), units, []


def _extract_xlsx(path: Path) -> tuple[str, list[dict[str, object]], list[str]]:
    return _extract_xlsx_input(path)


def _extract_xlsx_input(source, *, bounded: bool = False):
    try:
        from openpyxl import load_workbook
    except ImportError:
        return "", [], ["openpyxl_missing:pip_install_openpyxl"]
    try:
        wb = load_workbook(source, read_only=True, data_only=True)
    except Exception as exc:  # corrupted file / unexpected format
        return "", [], [f"xlsx_read_failed:{exc}"]
    lines: list[str] = []
    units: list[dict[str, object]] = []
    size = 0
    try:
        for sheet in wb.worksheets:
            if bounded and ((sheet.max_row or 0) > 100_000 or (sheet.max_column or 0) > 1024):
                raise ValueError('spreadsheet dimensions exceed protected limit')
            for r_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if bounded and (r_index > 100_000 or len(row) > 1024):
                    raise ValueError('spreadsheet dimensions exceed protected limit')
                cells = ["" if c is None else str(c) for c in row]
                if not any(cells):
                    continue
                line = " | ".join(cells)
                size += len(line.encode('utf-8')) + 1
                if bounded and (len(units) >= 100_000 or size > 2_000_000):
                    raise ValueError('extracted content exceeds protected limit')
                lines.append(line)
                units.append(
                    {"unit_id": f"{sheet.title}-row-{r_index}", "kind": "sheet_row", "sheet": sheet.title, "row": r_index, "text": line}
                )
    finally:
        wb.close()
    return "\n".join(lines), units, []


def _extract_docx(path: Path) -> tuple[str, list[dict[str, object]], list[str]]:
    return _extract_docx_input(str(path))


def _extract_docx_input(source, *, bounded: bool = False):
    try:
        from docx import Document
    except ImportError:
        return "", [], ["python_docx_missing:pip_install_python-docx"]
    try:
        doc = Document(source)
    except Exception as exc:
        return "", [], [f"docx_read_failed:{exc}"]
    paragraphs = []
    size = 0
    for p in doc.paragraphs:
        if not p.text.strip(): continue
        size += len(p.text.encode('utf-8')) + 1
        if bounded and (len(paragraphs) >= 100_000 or size > 2_000_000):
            raise ValueError('extracted content exceeds protected limit')
        paragraphs.append(p.text)
    units = [
        {"unit_id": f"para-{i}", "kind": "doc_paragraph", "ordinal": i, "text": text}
        for i, text in enumerate(paragraphs, start=1)
    ]
    return "\n".join(paragraphs), units, []


def _extract_email(path: Path) -> tuple[str, list[dict[str, object]], list[str]]:
    return _extract_email_data(path.read_bytes())


def _extract_email_data(raw: bytes, *, strict: bool = False):
    try:
        msg = email.message_from_bytes(raw)
    except Exception as exc:
        return "", [], [f"email_parse_failed:{exc}"]
    header_lines = [
        f"{key}: {msg.get(key)}" for key in ("From", "To", "Cc", "Date", "Subject") if msg.get(key)
    ]
    body_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True)
                if payload:
                    body_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="strict" if strict else "replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body_parts.append(payload.decode(msg.get_content_charset() or "utf-8", errors="strict" if strict else "replace"))
    if strict and any(part.defects for part in msg.walk()):
        raise ValueError('email encoding or structure unavailable')
    text = "\n".join(header_lines + ["", *body_parts])
    units = [{"unit_id": "email-headers", "kind": "email_headers", "text": "\n".join(header_lines)}]
    if body_parts:
        units.append({"unit_id": "email-body", "kind": "email_body", "text": "\n".join(body_parts)})
    return text, units, []


_SUFFIX_TYPE = {
    ".pdf": "pdf",
    ".csv": "table",
    ".tsv": "table",
    ".xlsx": "spreadsheet",
    ".xlsm": "spreadsheet",
    ".docx": "document",
    ".eml": "email",
    ".mbox": "email",
}


def _check_office_archive(data: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if (len(entries) > 4096 or len(names) != len(set(names))
                or sum(entry.file_size for entry in entries) > 64_000_000
                or any(entry.file_size > 32_000_000 or entry.flag_bits & 1 for entry in entries)):
            raise ValueError('office archive exceeds protected limits')


def _extract_pdf_bytes(data: bytes):
    """Pass captured bytes through poppler without reopening or staging the source."""
    process = subprocess.Popen(['pdftotext', '-layout', '-', '-'], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    selector = selectors.DefaultSelector()
    chunks = []
    total = 0
    position = 0
    deadline = time.monotonic() + 30
    try:
        for stream, event in ((process.stdin, selectors.EVENT_WRITE), (process.stdout, selectors.EVENT_READ)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, event)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('PDF extraction timed out')
            for key, _ in selector.select(min(remaining, 0.25)):
                stream = key.fileobj
                if key.events == selectors.EVENT_WRITE:
                    try:
                        count = os.write(stream.fileno(), data[position:position + 65536])
                        position += count
                    except BrokenPipeError:
                        position = len(data)
                    if position == len(data):
                        selector.unregister(stream)
                        stream.close()
                else:
                    chunk = os.read(stream.fileno(), 65536)
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                    else:
                        total += len(chunk)
                        if total > 2_000_000:
                            raise ValueError('extracted content exceeds protected limit')
                        chunks.append(chunk)
        if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
            raise ValueError('PDF extraction failed')
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()
        for stream in (process.stdin, process.stdout):
            if not stream.closed:
                stream.close()
    output = b''.join(chunks).decode('utf-8', errors='strict')
    return output, [{'unit_id': 'pdf-full-text', 'kind': 'pdf_text', 'text': output}], ([] if output.strip() else ['empty_text_extraction'])


def extract_captured(source: str, source_type: str, data: bytes) -> ExtractedDocument:
    """Extract authorized captured bytes; never reopen or stage the source path."""
    if not isinstance(data, bytes) or len(data) > 16_000_000:
        raise ValueError('source unavailable')
    suffix = Path(source).suffix.lower()
    try:
        if source_type == 'markdown' and suffix in {'.md', '.markdown', '.txt'}:
            if b'\x00' in data:
                raise ValueError('source unavailable')
            text = data.decode('utf-8', errors='strict')
            units, warnings = [{'unit_id': 'full-text', 'kind': 'text', 'text': text}], []
        elif source_type == 'table' and suffix in {'.csv', '.tsv'}:
            if b'\x00' in data:
                raise ValueError('source unavailable')
            stream = io.StringIO(data.decode('utf-8', errors='strict'), newline='')
            text, units, warnings = _extract_csv_stream(stream, suffix, bounded=True)
        elif source_type == 'spreadsheet' and suffix == '.xlsx':
            _check_office_archive(data)
            text, units, warnings = _extract_xlsx_input(io.BytesIO(data), bounded=True)
        elif source_type == 'document' and suffix == '.docx':
            _check_office_archive(data)
            text, units, warnings = _extract_docx_input(io.BytesIO(data), bounded=True)
        elif source_type == 'email' and suffix == '.eml':
            text, units, warnings = _extract_email_data(data, strict=True)
        elif source_type == 'pdf' and suffix == '.pdf':
            text, units, warnings = _extract_pdf_bytes(data)
        else:
            raise ValueError('source format requires an authorized adapter')
        if warnings or (source_type != 'markdown' and len(text.encode('utf-8')) > 2_000_000):
            raise ValueError('source extraction unavailable')
        return ExtractedDocument(source, source_type, text, units, [])
    except UnicodeError as exc:
        raise ValueError('source encoding requires an authorized adapter') from exc
    except (OSError, LookupError, zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
        raise ValueError('source extraction unavailable') from exc
    except ValueError:
        raise
    except Exception as exc:
        # Parsers can report malformed input using library-specific exceptions.
        raise ValueError('source extraction unavailable') from exc


def extract_source(source: str, source_type: str) -> ExtractedDocument:
    path = Path(source).expanduser()
    if not path.exists():
        return ExtractedDocument(source, source_type, "", [], ["source_not_found"])

    # Reconcile a generic source_type (document/email/file) with the real
    # extension, so we do not fall into raw-text reads of binaries (xlsx/docx).
    suffix_type = _SUFFIX_TYPE.get(path.suffix.lower())
    if source_type in {"file", "document", "email", "spreadsheet", "table"} and suffix_type:
        source_type = suffix_type

    if source_type == "pdf":
        text, units, warnings = _extract_pdf(path)
    elif source_type == "spreadsheet":
        text, units, warnings = _extract_xlsx(path)
    elif source_type == "document":
        text, units, warnings = _extract_docx(path)
    elif source_type == "email":
        text, units, warnings = _extract_email(path)
    elif source_type == "table":
        text, units, warnings = _extract_csv(path)
    elif source_type in {"markdown", "file", "text"}:
        text, warnings = _read_text(path)
        units = [{"unit_id": "full-text", "kind": "text", "text": text}]
    else:
        text, warnings = _read_text(path)
        units = [{"unit_id": "full-text", "kind": "text", "text": text}]

    return ExtractedDocument(source, source_type, text, units, warnings)
