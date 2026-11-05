import hashlib
import io
import json
import shutil
import zipfile

import pytest

from tests.test_protected_ingestion import prepared_repo
from tests.test_folder_policy_core import repo
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.extractors.text import extract_captured, extract_source
from wiki_core.ingest.protected import prepare, record, consolidate


def pdf_bytes():
    stream = b'BT /F1 12 Tf 20 250 Td (Synthetic PDF content) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    data = bytearray(b'%PDF-1.4\n')
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(str(index).encode() + b' 0 obj\n' + obj + b'\nendobj\n')
    start = len(data)
    data.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(start).encode() + b'\n%%EOF\n')
    return bytes(data)


def source_bytes(suffix):
    if suffix in ('.csv', '.tsv'):
        return ('name' + ('\t' if suffix == '.tsv' else ',') + 'value\n漢字,example\n').encode()
    if suffix == '.xlsx':
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active.append(['Synthetic', '漢字'])
        target = io.BytesIO()
        workbook.save(target)
        workbook.close()
        return target.getvalue()
    if suffix == '.docx':
        from docx import Document
        document = Document()
        document.add_paragraph('Synthetic 漢字 paragraph')
        target = io.BytesIO()
        document.save(target)
        return target.getvalue()
    if suffix == '.eml':
        return b'From: synthetic@example.invalid\nSubject: Example\nContent-Type: text/plain; charset=utf-8\n\nSynthetic email body\n'
    return pdf_bytes()


@pytest.mark.parametrize('suffix,kind', [('.csv', 'table'), ('.tsv', 'table'),
    ('.xlsx', 'spreadsheet'), ('.docx', 'document'), ('.eml', 'email'), ('.pdf', 'pdf')])
def test_captured_reader_matches_existing_reader(tmp_path, suffix, kind, monkeypatch):
    if suffix == '.pdf' and not shutil.which('pdftotext'):
        pytest.skip('optional pdftotext unavailable')
    path = tmp_path / ('source' + suffix)
    data = source_bytes(suffix)
    path.write_bytes(data)
    expected = extract_source(str(path), kind)
    path.unlink()
    actual = extract_captured(str(path), kind, data)
    assert (actual.text, actual.units, actual.warnings) == (expected.text, expected.units, expected.warnings)
    assert actual.text.strip()


@pytest.mark.parametrize('suffix,kind', [('.csv', 'table'), ('.xlsx', 'spreadsheet'),
    ('.docx', 'document'), ('.eml', 'email'), ('.pdf', 'pdf')])
def test_protected_stage_with_captured_formats(prepared_repo, suffix, kind):
    if suffix == '.pdf' and not shutil.which('pdftotext'):
        pytest.skip('optional pdftotext unavailable')
    root, sha = prepared_repo
    path = root / ('source' + suffix)
    path.write_bytes(source_bytes(suffix))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    options = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                   source_ref=path.name)
    output = prepare(root, binding, source_context='system', **options)
    request = output['request']
    assert request['chunks']
    sample = json.loads((__import__('pathlib').Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    row = request['chunks'][0]
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': request['perspectives_required'], 'perspectives': {}}
    ids = dict(source_id=output['source_id'], request_id=output['request_id'])
    assert record(root, binding, results=[result], **options, **ids)['recorded'] == 1
    event = ('memories/system/ingestion/events/2026-11-04-' +
             hashlib.sha256(output['source_id'].encode()).hexdigest() + '-' + output['request_id'] + '.md')
    import datetime
    result = consolidate(root, binding, source_page='memories/sources/synthetic.md', event_target=event,
                         date=datetime.date(2026, 11, 4), **options, **ids)
    assert f'source_type: {kind}' in (root / result['event']).read_text()


def test_strict_encoding_and_archive_limit():
    for filename, kind, data in [('x.csv', 'table', b'bad\xff'),
            ('x.eml', 'email', b'Content-Type: text/plain; charset=utf-8\n\ninvalid\xff')]:
        with pytest.raises(ValueError, match='encoding'):
            extract_captured(filename, kind, data)
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('large.xml', b'0' * 32_000_001)
    with pytest.raises(ValueError, match='archive'):
        extract_captured('x.xlsx', 'spreadsheet', target.getvalue())
    with pytest.raises(ValueError, match='authorized adapter'):
        extract_captured('x.mbox', 'email', b'unsupported')


def test_captured_docx_preserves_simple_table_in_body_order():
    from docx import Document

    document = Document()
    document.add_paragraph('Before table')
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = 'Item'
    table.cell(0, 1).text = 'Amount'
    document.add_paragraph('After table')
    output = io.BytesIO()
    document.save(output)

    extracted = extract_captured('source.docx', 'document', output.getvalue())
    assert extracted.text == 'Before table\nItem | Amount\nAfter table'
    assert [unit['kind'] for unit in extracted.units] == [
        'doc_paragraph', 'doc_table_row', 'doc_paragraph']


def test_captured_docx_does_not_silently_flatten_merged_or_nested_tables():
    from docx import Document

    document = Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1)).text = 'Merged'
    output = io.BytesIO()
    document.save(output)
    with pytest.raises(ValueError, match='merged or nested'):
        extract_captured('source.docx', 'document', output.getvalue())

    document = Document()
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).add_table(rows=1, cols=1).cell(0, 0).text = 'Nested'
    output = io.BytesIO()
    document.save(output)
    with pytest.raises(ValueError, match='merged or nested'):
        extract_captured('source.docx', 'document', output.getvalue())


@pytest.mark.parametrize('cached_value', [None, '6'])
def test_captured_xlsx_keeps_formula_and_cached_value_state(cached_value):
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append([3, '=A1*2'])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    data = output.getvalue()
    if cached_value is not None:
        rewritten = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(rewritten, 'w') as result:
            for item in original.infolist():
                payload = original.read(item.filename)
                if item.filename == 'xl/worksheets/sheet1.xml':
                    assert b'<f>A1*2</f><v></v>' in payload
                    payload = payload.replace(b'<f>A1*2</f><v></v>',
                        b'<f>A1*2</f><v>' + cached_value.encode() + b'</v>')
                result.writestr(item, payload)
        data = rewritten.getvalue()

    extracted = extract_captured('source.xlsx', 'spreadsheet', data)
    expected = 'unavailable' if cached_value is None else cached_value
    assert extracted.text == f'3 | [formula =A1*2; cached value: {expected}]'
    assert extracted.units[0]['text'] == extracted.text


def test_captured_xlsx_limits_total_sheet_cells():
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.cell(row=100_000, column=50, value='Sparse')
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    with pytest.raises(ValueError, match='spreadsheet dimensions'):
        extract_captured('source.xlsx', 'spreadsheet', output.getvalue())


def test_captured_email_preserves_plain_and_html_alternatives():
    from email.message import EmailMessage

    message = EmailMessage()
    message['Subject'] = 'Alternatives'
    message.set_content('Plain version')
    message.add_alternative('<p>HTML version</p>', subtype='html')
    extracted = extract_captured('source.eml', 'email', message.as_bytes())
    assert 'Plain version' in extracted.text
    assert 'Content-Type: text/html\n<p>HTML version</p>' in extracted.text

    html_only = EmailMessage()
    html_only['Subject'] = 'HTML only'
    html_only.make_alternative()
    html_only.add_alternative('<p>Only HTML</p>', subtype='html')
    extracted = extract_captured('source.eml', 'email', html_only.as_bytes())
    assert 'Content-Type: text/html\n<p>Only HTML</p>' in extracted.text


def test_captured_email_rejects_attachment_and_missing_body():
    from email.message import EmailMessage

    message = EmailMessage()
    message['Subject'] = 'Attachment'
    message.set_content('Useful plain text')
    message.add_attachment(b'separate data', maintype='application', subtype='octet-stream', filename='data.bin')
    with pytest.raises(ValueError, match='attachment requires separate explicit review'):
        extract_captured('source.eml', 'email', message.as_bytes())
    with pytest.raises(ValueError, match='body unavailable'):
        extract_captured('source.eml', 'email', b'Subject: Empty\n\n')


def test_capture_revoked_during_extraction_does_not_reopen(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    from wiki_core.ingest import protected
    path = tmp_path / 'source.csv'
    path.write_bytes(source_bytes('.csv'))
    state = {'revoked': False, 'reads': 0}
    class Policy:
        def fresh(self):
            if state['revoked']:
                raise ValueError('authority revoked')
    original_open = Path.open
    def tracked_open(self, *args, **kwargs):
        if self == path:
            state['reads'] += 1
        return original_open(self, *args, **kwargs)
    original_extract = protected.extract_captured
    def revoke(*args):
        result = original_extract(*args)
        state['revoked'] = True
        return result
    monkeypatch.setattr(Path, 'open', tracked_open)
    monkeypatch.setattr(protected, '_source', lambda *args: path)
    monkeypatch.setattr(protected, 'extract_captured', revoke)
    with pytest.raises(ValueError, match='authority revoked'):
        protected._capture(tmp_path, Policy(), '.', 'source.csv', 'system', SimpleNamespace(llm={}))
    assert state['reads'] == 1


@pytest.mark.parametrize('mode', ['timeout', 'output-limit'])
def test_pdf_process_is_reaped_on_failure(monkeypatch, mode):
    import subprocess
    import sys
    from wiki_core.extractors import text as extractor
    original_popen = subprocess.Popen
    children = []
    script = ('import time; time.sleep(60)' if mode == 'timeout' else
              'import sys; sys.stdout.buffer.write(b"x" * 2000001); sys.stdout.flush()')
    def spawn(_command, **kwargs):
        child = original_popen([sys.executable, '-c', script], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(extractor.subprocess, 'Popen', spawn)
    if mode == 'timeout':
        ticks = iter(range(0, 1000, 5))
        monkeypatch.setattr(extractor.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(ValueError, match='timed out|exceeds protected limit'):
        extractor.extract_captured('synthetic.pdf', 'pdf', b'%PDF-1.4')
    assert len(children) == 1 and children[0].poll() is not None
