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
from tests.test_protected_ingestion import prepare, record, consolidate


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
    if kind == 'table':
        assert json.loads(actual.text.splitlines()[0]) == {'record': 1, 'cells': ['name', 'value']}
        assert actual.warnings == expected.warnings == []
    elif kind == 'spreadsheet':
        assert json.loads(actual.text) == {'sheet': 'Sheet', 'row': 1, 'cells': [
            {'value': 'Synthetic', 'number_format': 'General'},
            {'value': '漢字', 'number_format': 'General'}]}
        assert actual.warnings == expected.warnings == []
    else:
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
    if kind in {'table', 'spreadsheet'}:
        captured_rows = [json.loads(line) for chunk in request['chunks'] for line in chunk['text'].split('\n')]
        locator = 'record' if kind == 'table' else 'row'
        assert all(row.get(locator) and isinstance(row.get('cells'), list) for row in captured_rows)
        if kind == 'spreadsheet':
            assert all(row.get('sheet') for row in captured_rows)
    sample = json.loads((__import__('pathlib').Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    row = request['chunks'][0]
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': request['perspectives_required'], 'perspectives': {name: {'status': 'extracted'} for name in request['perspectives_required']}}
    ids = dict(source_id=output['source_id'], request_id=output['request_id'])
    assert record(root, binding, results=[result], **options, **ids)['recorded'] == 1
    event = ('memories/system/ingestion/events/2026-11-04-' +
             hashlib.sha256(output['source_id'].encode()).hexdigest() + '-' + output['request_id'] + '.md')
    import datetime
    result = consolidate(root, binding, source_page='memories/sources/synthetic.md', event_target=event,
                         date=datetime.date(2026, 11, 4), **options, **ids)
    assert f'source_type: {kind}' in (root / result['event']).read_text()
    from wiki_core.frontmatter import parse_frontmatter
    from wiki_core.ingest.protected import _format_omissions
    expected = _format_omissions(path.name)
    assert all(item in request['block_context_package']['coverage']['missing'] for item in expected)
    metadata, _ = parse_frontmatter(root / result['event'])
    assert metadata['protected_provenance']['extraction_limitations'] == expected
    derived = root / 'data/derived/wiki/.wiki-viva-protected'
    manifest = json.loads((derived / 'source-manifests' / (output['source_id'] + '.json')).read_text())
    chunks = json.loads((derived / 'chunks' / (output['source_id'] + '.json')).read_text())
    extracted = json.loads((derived / 'source-text' / (output['source_id'] + '.json')).read_text())
    assert manifest['extraction_limitations'] == chunks['extraction_limitations'] == expected
    assert manifest['extraction_complete'] is chunks['extraction_complete'] is (not bool(expected))
    assert extracted['warnings'] == expected
    if suffix == '.docx':
        for block in (manifest['extraction_limitations'], chunks['extraction_limitations'],
                      request['block_context_package']['coverage']['missing'],
                      metadata['protected_provenance']['extraction_limitations']):
            assert any('hyperlink destinations' in item and 'comments' in item for item in block)
    if suffix == '.pdf':
        assert any('OCR was not performed' in item for item in manifest['extraction_limitations'])
        for block in (manifest['extraction_limitations'], chunks['extraction_limitations'],
                      request['block_context_package']['coverage']['missing'],
                      metadata['protected_provenance']['extraction_limitations']):
            assert any('do not retain page numbers' in item for item in block)
    if suffix == '.csv':
        for block in (manifest['extraction_limitations'], chunks['extraction_limitations'],
                      request['block_context_package']['coverage']['missing'],
                      metadata['protected_provenance']['extraction_limitations']):
            assert any('semicolon-delimited' in item and 'not inferred or verified' in item for item in block)


def test_captured_csv_exposes_unverified_dialect_without_guessing():
    from wiki_core.ingest.protected import _format_omissions

    extracted = extract_captured('source.csv', 'table', b'name;value\nitem;3\n')
    rows = [json.loads(line) for line in extracted.text.splitlines()]
    assert rows == [{'record': 1, 'cells': ['name;value']},
                    {'record': 2, 'cells': ['item;3']}]
    limitations = _format_omissions('source.csv')
    assert any('comma-delimited' in item and 'semicolon-delimited' in item
               and 'not inferred or verified' in item for item in limitations)
    assert any('tab-delimited' in item and 'not inferred or verified' in item
               for item in _format_omissions('source.tsv'))


@pytest.mark.parametrize('selection,delimiter', [('comma', ','), ('semicolon', ';'), ('tab', '\t')])
def test_captured_csv_uses_only_explicit_delimiter(selection, delimiter):
    data = f'name{delimiter}value\nitem{delimiter}3\n'.encode()
    extracted = extract_captured('source.csv', 'table', data, csv_delimiter=selection)
    assert [json.loads(line)['cells'] for line in extracted.text.splitlines()] == [
        ['name', 'value'], ['item', '3']]


@pytest.mark.parametrize('selection', ['pipe', '', 1, ['semicolon']])
def test_captured_csv_rejects_unsupported_delimiter(selection):
    with pytest.raises(ValueError, match='CSV delimiter selection unavailable'):
        extract_captured('source.csv', 'table', b'name;value\n', csv_delimiter=selection)
    with pytest.raises(ValueError, match='CSV delimiter selection unavailable'):
        extract_captured('source.tsv', 'table', b'name\tvalue\n', csv_delimiter='semicolon')


def test_protected_semicolon_selection_is_bound_and_revalidated(prepared_repo):
    from tests.test_protected_ingestion import AQAL_REFS, protected_source_stage
    from wiki_core.frontmatter import parse_frontmatter
    from wiki_core.ingest.protected import inspect
    import datetime

    root, sha = prepared_repo
    source = root / 'semicolon.csv'
    source.write_text('name;value\nitem;3\n', encoding='utf-8')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    options = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                   source_ref=source.name, csv_delimiter='semicolon')
    prepared = protected_source_stage(root, binding, 'prepare', {**options, 'source_context': 'system'})['result']
    request = prepared['request']
    rows = [json.loads(line) for chunk in request['chunks'] for line in chunk['text'].split('\n')]
    assert [row['cells'] for row in rows] == [['name', 'value'], ['item', '3']]
    assert request['source_authorization']['csv_delimiter'] == 'semicolon'
    assert any('explicitly selected semicolon' in item for item in request['block_context_package']['coverage']['missing'])
    sample = json.loads((__import__('pathlib').Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    chunk = request['chunks'][0]
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: chunk[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': request['perspectives_required'], 'perspectives': {name: {'status': 'extracted'} for name in request['perspectives_required']}}
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    for wrong in (None, 'comma', 'tab'):
        bad = dict(options)
        if wrong is None:
            del bad['csv_delimiter']
        else:
            bad['csv_delimiter'] = wrong
        with pytest.raises(ValueError):
            record(root, binding, **bad, **ids, results=[result])
    assert record(root, binding, **options, **ids, results=[result])['recorded'] == 1
    viewed = inspect(root, binding, **options, **ids, view='results', chunk_ids=[chunk['chunk_id']],
                     context_selection={'omit_root_entity': True}, perspective_refs=AQAL_REFS)
    assert viewed['view'] == 'results'
    with pytest.raises(ValueError):
        inspect(root, binding, **{**options, 'csv_delimiter': 'comma'}, **ids, view='results',
                chunk_ids=[chunk['chunk_id']], context_selection={'omit_root_entity': True}, perspective_refs=AQAL_REFS)
    event = ('memories/system/ingestion/events/2026-11-04-' +
             hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    with pytest.raises(ValueError):
        consolidate(root, binding, **{**options, 'csv_delimiter': 'comma'}, **ids,
                    source_page='memories/sources/synthetic.md', event_target=event, date=datetime.date(2026, 11, 4))
    assert not (root / event).exists()
    output = consolidate(root, binding, **options, **ids, source_page='memories/sources/synthetic.md',
                         event_target=event, date=datetime.date(2026, 11, 4))
    metadata, _ = parse_frontmatter(root / output['event'])
    assert metadata['protected_provenance']['csv_delimiter'] == 'semicolon'
    assert any('explicitly selected semicolon' in item
               for item in metadata['protected_provenance']['extraction_limitations'])
    derived = root / 'data/derived/wiki/.wiki-viva-protected'
    paths = [derived / directory / (prepared['source_id'] + '.json')
             for directory in ('source-manifests', 'source-text', 'chunks')]
    original = {path: path.read_bytes() for path in paths}
    assert json.loads(original[paths[0]])['csv_delimiter'] == 'semicolon'
    with pytest.raises(ValueError, match='existing source capture differs'):
        prepare(root, binding, **{**options, 'csv_delimiter': 'comma'}, source_context='system')
    assert all(path.read_bytes() == content for path, content in original.items())


@pytest.mark.parametrize('suffix', ['.csv', '.tsv', '.pdf'])
def test_previous_capture_with_less_coverage_is_preserved_and_requalified(prepared_repo, monkeypatch, suffix):
    from wiki_core.ingest import protected

    if suffix == '.pdf' and not shutil.which('pdftotext'):
        pytest.skip('optional pdftotext unavailable')
    root, sha = prepared_repo
    source = root / ('previous' + suffix)
    source.write_bytes(source_bytes(suffix))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    options = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                   source_ref=source.name)
    old_pdf_limit = 'PDF images and scanned text were not inspected; OCR was not performed.'
    with monkeypatch.context() as previous:
        previous.setattr(protected, '_format_omissions',
            lambda source_ref, csv_delimiter=None: [old_pdf_limit] if source_ref.lower().endswith('.pdf') else [])
        prepared = prepare(root, binding, **options, source_context='system')
    request = prepared['request']
    chunk = request['chunks'][0]
    sample = json.loads((__import__('pathlib').Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: chunk[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': request['perspectives_required'], 'perspectives': {name: {'status': 'extracted'} for name in request['perspectives_required']}}
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    derived = root / 'data/derived/wiki/.wiki-viva-protected'
    original = {path.relative_to(derived): path.read_bytes() for path in derived.rglob('*.json')}
    with pytest.raises(ValueError, match='request authority changed'):
        record(root, binding, **options, **ids, results=[result])
    with pytest.raises(ValueError, match='existing source capture differs'):
        prepare(root, binding, **options, source_context='system')
    assert {path.relative_to(derived): path.read_bytes() for path in derived.rglob('*.json')} == original


@pytest.mark.parametrize('suffix,delimiter', [('.csv', ','), ('.tsv', '\t')])
@pytest.mark.parametrize('malformed', ['unterminated', 'after_quote'])
def test_protected_tabular_capture_rejects_malformed_quoting_before_writes(prepared_repo, suffix, delimiter, malformed):
    root, sha = prepared_repo
    source = root / ('source' + suffix)
    body = (f'first{delimiter}"open\nsecond{delimiter}value\n' if malformed == 'unterminated'
            else f'first{delimiter}"closed"unexpected\n')
    source.write_text(body, encoding='utf-8')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(ValueError, match='source extraction unavailable'):
        prepare(root, binding, context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                source_ref=source.name, source_context='system')
    assert not (root / 'data/derived/wiki/.wiki-viva-protected').exists()


@pytest.mark.parametrize('suffix,delimiter', [('.csv', ','), ('.tsv', '\t')])
def test_legacy_tabular_reader_preserves_permissive_quote_handling(tmp_path, suffix, delimiter):
    source = tmp_path / ('legacy' + suffix)
    source.write_text(f'first{delimiter}"open\nsecond{delimiter}value\n', encoding='utf-8')
    extracted = extract_source(str(source), 'table')
    assert extracted.text and not extracted.warnings


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
    before, row, after = extracted.text.split('\n')
    assert before == 'Before table' and after == 'After table'
    assert json.loads(row) == {'kind': 'doc_table_row', 'table': 1, 'row': 1, 'cells': ['Item', 'Amount']}
    assert [unit['kind'] for unit in extracted.units] == [
        'doc_paragraph', 'doc_table_row', 'doc_paragraph']


def test_captured_docx_table_rows_keep_cell_boundaries_and_locator_in_chunks():
    from docx import Document
    from wiki_core.chunking import chunk_text

    document = Document()
    document.add_paragraph('long ' * 250)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = 'pipe | text'
    table.cell(0, 1).text = 'line 1\nline 2'
    table.cell(1, 0).text = 'second'
    table.cell(1, 1).text = 'row'
    document.add_paragraph('After table')
    output = io.BytesIO()
    document.save(output)
    extracted = extract_captured('source.docx', 'document', output.getvalue())
    chunks = chunk_text('source', extracted.text, target_tokens=100, source_units=extracted.units)
    rows = [json.loads(line) for chunk in chunks for line in chunk.text.split('\n')
            if line.startswith('{"kind":"doc_table_row"')]
    assert rows == [{'kind': 'doc_table_row', 'table': 1, 'row': 1, 'cells': ['pipe | text', 'line 1\nline 2']},
                    {'kind': 'doc_table_row', 'table': 1, 'row': 2, 'cells': ['second', 'row']}]
    assert any('After table' in chunk.text for chunk in chunks)
    assert len(chunks) >= 3  # Long paragraphs still subdivide normally.


def test_captured_docx_table_row_does_not_split_when_oversize():
    from docx import Document
    from wiki_core.chunking import chunk_text

    document = Document()
    document.add_table(rows=1, cols=1).cell(0, 0).text = 'x' * 32_001
    output = io.BytesIO()
    document.save(output)
    extracted = extract_captured('source.docx', 'document', output.getvalue())
    with pytest.raises(ValueError, match='tabular row exceeds estimated limit'):
        chunk_text('source', extracted.text, source_units=extracted.units)


def test_document_chunking_rejects_units_that_do_not_match_extracted_text():
    from wiki_core.chunking import chunk_text

    units = [{'kind': 'doc_paragraph', 'text': 'Different content'}]
    with pytest.raises(ValueError, match='document chunk units differ'):
        chunk_text('source', 'Source content', source_units=units)


def test_protected_request_keeps_docx_table_row(prepared_repo):
    from docx import Document

    root, sha = prepared_repo
    document = Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = 'pipe | inside'
    table.cell(0, 1).text = 'first line\nsecond line'
    source = root / 'table.docx'
    document.save(source)
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    result = prepare(root, binding, context_id='.', approved_revision=sha,
        entry_folder='.', entry_index='index.md', source_ref=source.name, source_context='system')
    rows = [json.loads(line) for chunk in result['request']['chunks'] for line in chunk['text'].split('\n')
            if line.startswith('{"kind":"doc_table_row"')]
    assert rows == [{'kind': 'doc_table_row', 'table': 1, 'row': 1,
                     'cells': ['pipe | inside', 'first line\nsecond line']}]


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


@pytest.mark.parametrize('wrapper', ['ins', 'del', 'moveFrom', 'moveTo', 'sdt', 'customXml', 'smartTag', 'fldSimple'])
@pytest.mark.parametrize('inside_table', [False, True])
def test_captured_docx_rejects_unreadable_inline_wrappers(wrapper, inside_table):
    from docx import Document
    from docx.oxml import OxmlElement

    document = Document()
    paragraph = (document.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0]
                 if inside_table else document.add_paragraph())
    run = OxmlElement('w:r')
    text = OxmlElement('w:t')
    text.text = 'Do not drop this text'
    run.append(text)
    container = OxmlElement('w:' + wrapper)
    container.append(run)
    paragraph._p.append(container)
    output = io.BytesIO()
    document.save(output)
    with pytest.raises(ValueError, match='revision or unsupported inline'):
        extract_captured('source.docx', 'document', output.getvalue())


@pytest.mark.parametrize('wrapper', ['oMath', 'oMathPara'])
def test_captured_docx_rejects_equations_missing_from_paragraph_text(wrapper):
    from docx import Document
    from docx.oxml import OxmlElement

    document = Document()
    paragraph = document.add_paragraph('Before equation ')
    equation = OxmlElement('m:' + wrapper)
    run = OxmlElement('m:r')
    text = OxmlElement('m:t')
    text.text = 'x+y'
    run.append(text)
    equation.append(run)
    paragraph._p.append(equation)
    output = io.BytesIO()
    document.save(output)
    with pytest.raises(ValueError, match='revision or unsupported inline'):
        extract_captured('source.docx', 'document', output.getvalue())


@pytest.mark.parametrize('reference,inside_table', [
    ('footnoteReference', False), ('endnoteReference', False), ('footnoteReference', True),
])
def test_captured_docx_requires_review_for_note_references(reference, inside_table):
    from docx import Document
    from docx.oxml import OxmlElement

    document = Document()
    paragraph = (document.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0]
                 if inside_table else document.add_paragraph('Text'))
    run = OxmlElement('w:r')
    run.append(OxmlElement('w:' + reference))
    paragraph._p.append(run)
    output = io.BytesIO()
    document.save(output)
    with pytest.raises(ValueError, match='revision or unsupported inline'):
        extract_captured('source.docx', 'document', output.getvalue())


def test_captured_docx_preserves_hyperlink_runs_and_rejects_unknown_text_wrappers():
    from docx import Document
    from docx.oxml import OxmlElement

    document = Document()
    paragraph = document.add_paragraph('Before ')
    hyperlink = OxmlElement('w:hyperlink')
    run = OxmlElement('w:r')
    text = OxmlElement('w:t')
    text.text = 'linked text'
    run.append(text)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)
    output = io.BytesIO()
    document.save(output)
    assert extract_captured('source.docx', 'document', output.getvalue()).text == 'Before linked text'

    wrapper = OxmlElement('w:unknownTextContainer')
    run = OxmlElement('w:r')
    text = OxmlElement('w:t')
    text.text = 'Hidden by reader'
    run.append(text)
    wrapper.append(run)
    paragraph._p.append(wrapper)
    output = io.BytesIO()
    document.save(output)
    with pytest.raises(ValueError, match='revision or unsupported inline'):
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
    assert json.loads(extracted.text) == {'sheet': 'Sheet', 'row': 1, 'cells': [
        {'value': 3, 'number_format': 'General'},
        {'formula': '=A1*2', 'cached_value': None if cached_value is None else 6,
         'number_format': 'General'}]}
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


def xlsx_with_declared_dimension(data, dimension):
    import xml.etree.ElementTree as ET
    target = io.BytesIO()
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as dest:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename.startswith('xl/worksheets/') and item.filename.endswith('.xml'):
                root = ET.fromstring(payload)
                declared = root.find(ns + 'dimension')
                if dimension is None:
                    root.remove(declared)
                else:
                    declared.set('ref', dimension)
                payload = ET.tostring(root)
            dest.writestr(item, payload)
    return target.getvalue()


@pytest.mark.parametrize('dimension', ['A1', 'A1:B1', 'A1:A3', None])
def test_captured_xlsx_reads_cells_outside_declared_dimensions(dimension):
    from openpyxl import Workbook
    workbook = Workbook()
    for sheet in (workbook.active, workbook.create_sheet('Second')):
        sheet.append(['Safe first row'])
        sheet.append(['field', 'literal value'])
        sheet.append(['other', '="formula value"'])
    target = io.BytesIO()
    workbook.save(target)
    workbook.close()
    data = xlsx_with_declared_dimension(target.getvalue(), dimension)
    extracted = extract_captured('source.xlsx', 'spreadsheet', data)
    assert not extracted.warnings
    rows = [json.loads(unit['text']) for unit in extracted.units]
    assert len(rows) == 6
    for sheet_name in ('Sheet', 'Second'):
        selected = [row for row in rows if row['sheet'] == sheet_name]
        assert [row['row'] for row in selected] == [1, 2, 3]
        assert selected[1]['cells'][1]['value'] == 'literal value'
        assert selected[2]['cells'][1]['formula'] == '="formula value"'


@pytest.mark.parametrize('row,column', [(100_001, 1), (1, 1025), (100_000, 50)])
def test_captured_xlsx_actual_limits_survive_understated_dimensions(row, column):
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.active['A1'] = 'Safe first row'
    workbook.active.cell(row=row, column=column, value='Outside limit')
    target = io.BytesIO()
    workbook.save(target)
    workbook.close()
    data = xlsx_with_declared_dimension(target.getvalue(), 'A1')
    with pytest.raises(ValueError, match='spreadsheet dimensions'):
        extract_captured('source.xlsx', 'spreadsheet', data)


def test_captured_xlsx_preserves_scalar_types_and_tags_dates():
    import datetime
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append([1, '1', True, 'True', datetime.datetime(2026, 11, 5, 8, 30),
                            '#DIV/0!', '#DIV/0!', 0.5])
    workbook.active.cell(row=1, column=7).data_type = 's'
    workbook.active.cell(row=1, column=8).number_format = '0%'
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    extracted = extract_captured('source.xlsx', 'spreadsheet', output.getvalue())
    cells = json.loads(extracted.text)['cells']
    assert [cell['value'] for cell in cells] == [1, '1', True, 'True',
        {'type': 'datetime', 'value': '2026-11-05T08:30:00'},
        {'type': 'error', 'value': '#DIV/0!'}, '#DIV/0!', 0.5]
    assert cells[-1]['number_format'] == '0%'


@pytest.mark.parametrize('suffix,delimiter', [('.csv', ','), ('.tsv', '\t')])
def test_captured_table_rows_keep_cell_boundaries_and_locator_in_chunks(suffix, delimiter):
    import csv
    from wiki_core.chunking import chunk_text

    target = io.StringIO(newline='')
    writer = csv.writer(target, delimiter=delimiter, lineterminator='\n')
    writer.writerow(['pipe | text', 'line 1\nline 2', 'unicode\u2028separator'])
    writer.writerow(['next', 'row'])
    extracted = extract_captured('source' + suffix, 'table', target.getvalue().encode())
    chunks = chunk_text('source', extracted.text, target_tokens=100, preserve_lines=True)
    rows = [json.loads(line) for chunk in chunks for line in chunk.text.split('\n')]
    assert rows == [{'record': 1, 'cells': ['pipe | text', 'line 1\nline 2', 'unicode\u2028separator']},
                    {'record': 2, 'cells': ['next', 'row']}]
    assert all(chunk.token_estimate >= (len(chunk.text.encode('utf-8')) + 3) // 4 for chunk in chunks)


def test_captured_spreadsheet_rows_keep_sheet_and_row_in_chunks():
    from openpyxl import Workbook
    from wiki_core.chunking import chunk_text

    workbook = Workbook()
    workbook.active.title = 'First'
    workbook.active.append(['same | value', 'line 1\nline 2'])
    workbook.create_sheet('Second').append(['same | value', 'line 1\nline 2'])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    extracted = extract_captured('source.xlsx', 'spreadsheet', output.getvalue())
    chunks = chunk_text('source', extracted.text, target_tokens=100, preserve_lines=True)
    rows = [json.loads(line) for chunk in chunks for line in chunk.text.split('\n')]
    cells = [{'value': 'same | value', 'number_format': 'General'},
             {'value': 'line 1\nline 2', 'number_format': 'General'}]
    assert rows == [{'sheet': 'First', 'row': 1, 'cells': cells},
                    {'sheet': 'Second', 'row': 1, 'cells': cells}]


@pytest.mark.parametrize('text', ['word ' * 121, 'x' * 32_001])
def test_tabular_chunker_rejects_oversize_row_instead_of_splitting(text):
    from wiki_core.chunking import chunk_text

    line = json.dumps({'row': 1, 'cells': [text]}, ensure_ascii=False)
    with pytest.raises(ValueError, match='tabular row exceeds estimated limit'):
        chunk_text('source', line, target_tokens=1, preserve_lines=True)


def test_oversize_tabular_source_is_rejected_before_artifact_creation(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected

    root, sha = prepared_repo
    source = root / 'large.csv'
    source.write_text('x' * 32_001, encoding='utf-8')
    monkeypatch.setattr(protected, 'scan_text', lambda *_args: pytest.fail('oversize row scanned'))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(ValueError, match='tabular row exceeds estimated limit'):
        prepare(root, binding, context_id='.', approved_revision=sha, entry_folder='.',
                entry_index='index.md', source_ref=source.name, source_context='system')
    assert not (root / 'data/derived/wiki/.wiki-viva-protected').exists()


def test_one_token_target_still_uses_documented_minimum_word_estimate():
    from wiki_core.chunking import chunk_text
    text = 'x' * 100
    assert chunk_text('source', text, target_tokens=1, preserve_lines=True)[0].text == text
    with pytest.raises(ValueError, match='estimated limit'):
        chunk_text('source', 'x' * 601, target_tokens=1, preserve_lines=True)


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
