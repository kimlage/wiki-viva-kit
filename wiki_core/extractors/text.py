from __future__ import annotations

import csv
import datetime as dt
import decimal
import email
import io
import itertools
import json
import math
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


def _tabular_json_line(value):
    """Serialize one logical row without introducing physical line breaks."""
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    for separator in ('\u0085', '\u2028', '\u2029'):
        text = text.replace(separator, f'\\u{ord(separator):04x}')
    return text


def _extract_csv_stream(handle, suffix: str, *, bounded: bool = False, delimiter: str | None = None):
    rows: list[str] = []
    units: list[dict[str, object]] = []
    dialect = "excel-tab" if suffix.lower() == ".tsv" else "excel"
    size = 0
    # The protected byte-capture path must reject malformed quoting rather
    # than silently joining logical records. Legacy extraction keeps its
    # existing permissive dialect for historical compatibility.
    options = {'strict': True} if bounded else {}
    if delimiter is not None:
        options['delimiter'] = delimiter
    for index, row in enumerate(csv.reader(handle, dialect=dialect, **options), start=1):
        line = (_tabular_json_line({'record': index, 'cells': row}) if bounded
                else " | ".join(row))
        size += len(line.encode('utf-8')) + 1
        if bounded and (index > 100_000 or size > 2_000_000):
            raise ValueError('extracted content exceeds protected limit')
        rows.append(line)
        if bounded:
            units.append({'unit_id': f'record-{index}', 'kind': 'table_record', 'record': index, 'text': line})
        else:
            units.append({"unit_id": f"row-{index}", "kind": "table_row", "row": index, "text": line})
    return "\n".join(rows), units, []


def _extract_xlsx(path: Path) -> tuple[str, list[dict[str, object]], list[str]]:
    return _extract_xlsx_input(path)


def _spreadsheet_value(value, data_type=None):
    """Preserve scalar types and explicitly tag types not native to JSON."""
    if data_type == 'e':
        return {'type': 'error', 'value': str(value)}
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('spreadsheet non-finite value requires explicit review')
        return value
    if isinstance(value, dt.datetime):
        return {'type': 'datetime', 'value': value.isoformat()}
    if isinstance(value, dt.date):
        return {'type': 'date', 'value': value.isoformat()}
    if isinstance(value, dt.time):
        return {'type': 'time', 'value': value.isoformat()}
    if isinstance(value, dt.timedelta):
        return {'type': 'duration', 'value': str(value)}
    if isinstance(value, decimal.Decimal):
        if not value.is_finite():
            raise ValueError('spreadsheet non-finite value requires explicit review')
        return {'type': 'decimal', 'value': str(value)}
    raise ValueError('spreadsheet cell type requires explicit review')


def _check_xlsx_cell_layout(sheet):
    """Verify the actual worksheet before streaming can omit/reorder cells."""
    import xml.etree.ElementTree as ET
    from openpyxl.utils.cell import coordinate_to_tuple

    # Use the same resolved worksheet part as openpyxl, including renamed parts.
    with sheet._get_source() as source:
        root = ET.parse(source).getroot()
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    rows = root.find(ns + 'sheetData')
    previous_row = max_column = 0
    for row in (() if rows is None else rows):
        row_index = int(row.get('r', previous_row + 1))
        if row.tag != ns + 'row' or row_index <= previous_row:
            raise ValueError('spreadsheet cell layout requires explicit review')
        if row_index > 100_000:
            raise ValueError('spreadsheet dimensions exceed protected limit')
        column = 0
        for cell in row:
            cell_row, cell_column = (coordinate_to_tuple(cell.get('r'))
                                    if cell.get('r') else (row_index, column + 1))
            if cell.tag != ns + 'c' or cell_row != row_index or cell_column <= column:
                raise ValueError('spreadsheet cell layout requires explicit review')
            if cell_column > 1024:
                raise ValueError('spreadsheet dimensions exceed protected limit')
            column = cell_column
        max_column = max(max_column, column)
        if row_index * max_column > 2_000_000:
            raise ValueError('spreadsheet dimensions exceed protected limit')
        previous_row = row_index


def _extract_xlsx_captured(data: bytes):
    """Retain formulas alongside cached values without recalculating them."""
    from openpyxl import load_workbook

    formulas = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    try:
        cached = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        formulas.close()
        raise
    lines, units = [], []
    size = 0
    try:
        if formulas.sheetnames != cached.sheetnames:
            raise ValueError('spreadsheet sheets unavailable')
        for sheet, values in zip(formulas.worksheets, cached.worksheets):
            _check_xlsx_cell_layout(sheet)
            max_row, max_column = sheet.max_row or 0, sheet.max_column or 0
            if (max_row > 100_000 or max_column > 1024 or max_row * max_column > 2_000_000):
                raise ValueError('spreadsheet dimensions exceed protected limit')
            # Worksheet dimension metadata can understate actual cells. Stream
            # both views independently of it; the loop enforces actual limits.
            sheet.reset_dimensions()
            values.reset_dimensions()
            pairs = itertools.zip_longest(sheet.iter_rows(), values.iter_rows())
            visited_cells = 0
            actual_max_column = 0
            for row_index, (formula_row, value_row) in enumerate(pairs, start=1):
                if (formula_row is None or value_row is None or len(formula_row) != len(value_row)
                        or row_index > 100_000 or len(formula_row) > 1024):
                    raise ValueError('spreadsheet dimensions exceed protected limit')
                visited_cells += len(formula_row)
                actual_max_column = max(actual_max_column, len(formula_row))
                if visited_cells > 2_000_000 or row_index * actual_max_column > 2_000_000:
                    raise ValueError('spreadsheet dimensions exceed protected limit')
                cells = []
                for formula_cell, value_cell in zip(formula_row, value_row):
                    value = value_cell.value
                    if formula_cell.data_type == 'f':
                        expression = formula_cell.value
                        if not isinstance(expression, str):
                            raise ValueError('spreadsheet formula requires explicit review')
                        cells.append({'formula': expression,
                                      'cached_value': _spreadsheet_value(value, value_cell.data_type),
                                      'number_format': formula_cell.number_format})
                    else:
                        cells.append(None if value is None else {
                            'value': _spreadsheet_value(value, value_cell.data_type),
                            'number_format': formula_cell.number_format})
                if all(value is None or value.get('value') == '' for value in cells):
                    continue
                line = _tabular_json_line({'sheet': sheet.title, 'row': row_index, 'cells': cells})
                size += len(line.encode('utf-8')) + 1
                if len(units) >= 100_000 or size > 2_000_000:
                    raise ValueError('extracted content exceeds protected limit')
                lines.append(line)
                units.append({'unit_id': f'{sheet.title}-row-{row_index}', 'kind': 'sheet_row',
                    'sheet': sheet.title, 'row': row_index, 'text': line})
    finally:
        formulas.close()
        cached.close()
    return '\n'.join(lines), units, []


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


def _extract_docx_captured(data: bytes):
    """Extract body paragraphs and simple table rows in document order."""
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    texts, units = [], []
    size = 0
    paragraph_index = table_index = 0
    unsupported_inline = {qn('w:ins'), qn('w:del'), qn('w:moveFrom'), qn('w:moveTo'),
        qn('w:sdt'), qn('w:customXml'), qn('w:smartTag'), qn('w:fldSimple'),
        qn('w:sym'), qn('w:instrText'), qn('w:delText'), qn('w:footnoteReference'),
        qn('w:endnoteReference')}
    math_namespace = qn('m:oMath').split('}')[0] + '}'

    def append(text, unit):
        nonlocal size
        size += len(text.encode('utf-8')) + 1
        if len(units) >= 100_000 or size > 2_000_000:
            raise ValueError('extracted content exceeds protected limit')
        texts.append(text)
        units.append({**unit, 'text': text})

    for element in doc.element.body.iterchildren():
        if any(isinstance(descendant.tag, str) and (descendant.tag in unsupported_inline
                or descendant.tag.startswith(math_namespace)) for descendant in element.iter()):
            raise ValueError('document revision or unsupported inline content requires explicit review')
        # Paragraph.text includes direct runs and hyperlink runs. Refuse text
        # under any other wrapper rather than silently dropping it.
        for paragraph in element.iter(qn('w:p')):
            for text_node in paragraph.iter(qn('w:t')):
                run = text_node.getparent()
                parent = run.getparent() if run is not None else None
                if (run is None or run.tag != qn('w:r') or parent is None or
                        (parent is not paragraph and not (parent.tag == qn('w:hyperlink')
                         and parent.getparent() is paragraph))):
                    raise ValueError('document revision or unsupported inline content requires explicit review')
        if element.tag == qn('w:p'):
            text = Paragraph(element, doc).text
            if text.strip():
                paragraph_index += 1
                append(text, {'unit_id': f'para-{paragraph_index}', 'kind': 'doc_paragraph',
                    'ordinal': paragraph_index})
        elif element.tag == qn('w:tbl'):
            table_index += 1
            seen_cells = set()
            for row_index, row in enumerate(Table(element, doc).rows, start=1):
                cells = []
                for cell in row.cells:
                    if cell._tc in seen_cells or cell.tables:
                        raise ValueError('merged or nested document table requires explicit review')
                    seen_cells.add(cell._tc)
                    cells.append(cell.text)
                text = _tabular_json_line({'kind': 'doc_table_row', 'table': table_index,
                                           'row': row_index, 'cells': cells})
                if any(cell.strip() for cell in cells):
                    append(text, {'unit_id': f'table-{table_index}-row-{row_index}',
                        'kind': 'doc_table_row', 'table': table_index, 'row': row_index})
        elif element.tag != qn('w:sectPr'):
            raise ValueError('unsupported document body content requires explicit review')
    return '\n'.join(texts), units, []


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
    if strict and not msg.is_multipart() and (msg.get_filename() or
            msg.get_content_disposition() == 'attachment' or
            msg.get_content_type() not in ('text/plain', 'text/html')):
        raise ValueError('email attachment requires separate explicit review')
    body_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if strict and not part.is_multipart() and (part.get_filename() or
                    part.get_content_disposition() == 'attachment' or
                    part.get_content_type() not in ('text/plain', 'text/html')):
                raise ValueError('email attachment requires separate explicit review')
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True)
                if payload:
                    body_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="strict" if strict else "replace"))
            elif strict and part.get_content_type() == 'text/html' and not part.get_filename():
                payload = part.get_payload(decode=True)
                if payload:
                    body_parts.append('Content-Type: text/html\n' +
                        payload.decode(part.get_content_charset() or 'utf-8', errors='strict'))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body_parts.append(payload.decode(msg.get_content_charset() or "utf-8", errors="strict" if strict else "replace"))
    if strict and any(part.defects for part in msg.walk()):
        raise ValueError('email encoding or structure unavailable')
    if strict and not any(part.strip() for part in body_parts):
        raise ValueError('email body unavailable; explicit review required')
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


def extract_captured(source: str, source_type: str, data: bytes, *, csv_delimiter: str | None = None) -> ExtractedDocument:
    """Extract authorized captured bytes; never reopen or stage the source path."""
    if not isinstance(data, bytes) or len(data) > 16_000_000:
        raise ValueError('source unavailable')
    suffix = Path(source).suffix.lower()
    delimiters = {'comma': ',', 'semicolon': ';', 'tab': '\t'}
    if csv_delimiter is not None and (source_type != 'table' or suffix != '.csv'
            or not isinstance(csv_delimiter, str) or csv_delimiter not in delimiters):
        raise ValueError('CSV delimiter selection unavailable')
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
            text, units, warnings = _extract_csv_stream(stream, suffix, bounded=True,
                delimiter=None if csv_delimiter is None else delimiters[csv_delimiter])
        elif source_type == 'spreadsheet' and suffix == '.xlsx':
            _check_office_archive(data)
            text, units, warnings = _extract_xlsx_captured(data)
        elif source_type == 'document' and suffix == '.docx':
            _check_office_archive(data)
            text, units, warnings = _extract_docx_captured(data)
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
