"""Synthetic cross-turn secret detection and scan-first ingestion."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from wiki_core.detectors import scan_text
from wiki_core.repo_read import contains_access_secrets


QUESTION = 'Speaker A: What is the room password?'
TEST_MARKER = 'blue-harbor-test-42'
INGEST = Path(__file__).resolve().parents[1] / 'scripts' / 'wiki_ingest.py'


@pytest.mark.parametrize(('question', 'answer', 'line'), [
    (QUESTION, 'Speaker B: ' + TEST_MARKER + '.', 2),
    ("[00:00:01] Speaker A: What's your password?", '\n[00:00:02] Speaker B: It is "' + TEST_MARKER + '".', 3),
    ('Pessoa A: Qual é a senha da sala?', 'Pessoa B: É ' + TEST_MARKER + '.', 2),
    ('Persona A: ¿Cuál es la contraseña de la sala?', 'Persona B: Es ' + TEST_MARKER + '.', 2),
])
def test_password_question_detects_next_speaker_value(question, answer, line):
    transcript = question + '\n' + answer
    findings = [finding for finding in scan_text(transcript) if finding.category == 'secret']
    assert [(finding.kind, finding.line) for finding in findings] == [('transcript_password', line)]
    assert TEST_MARKER not in findings[0].excerpt
    assert contains_access_secrets(transcript)


@pytest.mark.parametrize(('question', 'answer'), [
    (QUESTION, "Speaker B: I don't know."),
    (QUESTION, 'Speaker B: Unknown!'),
    (QUESTION, 'Speaker B: Ask the moderator.'),
    (QUESTION, 'Speaker B: Version 2.'),
    (QUESTION, 'Speaker B: 2FA.'),
    (QUESTION, 'Speaker A: ' + TEST_MARKER),
    (QUESTION, 'Speaker B: No.\nSpeaker C: ' + TEST_MARKER),
    (QUESTION, 'An unrelated paragraph.\nSpeaker B: ' + TEST_MARKER),
    ('Speaker A: Should we change the room password?', 'Speaker B: ' + TEST_MARKER),
    ('Speaker A: Which room is open?', 'Speaker B: ' + TEST_MARKER),
])
def test_ordinary_or_unrelated_turns_are_allowed(question, answer):
    transcript = question + '\n' + answer
    assert not any(finding.category == 'secret' for finding in scan_text(transcript))
    assert not contains_access_secrets(transcript)


@pytest.mark.parametrize(('extension', 'blocked'), [('txt', True), ('docx', True), ('txt', False)])
def test_ingestion_writes_no_artifacts_for_cross_turn_password(tmp_path, extension, blocked):
    (tmp_path / 'wiki.config.yaml').write_text('repo_id: synthetic-transcript\n')
    context = tmp_path / 'memories/example'
    context.mkdir(parents=True)
    (context / 'AGENTS.md').write_text('# Synthetic guidance\n')
    (context / 'index.md').write_text('# Synthetic context\n')
    source = tmp_path / f'dialogue.{extension}'
    reply = 'Speaker B: ' + (TEST_MARKER + '.' if blocked else "I don't know.")
    if extension == 'docx':
        from docx import Document

        document = Document()
        document.add_paragraph(QUESTION)
        document.add_paragraph(reply)
        document.save(source)
    else:
        source.write_text(QUESTION + '\n' + reply + '\n')

    result = subprocess.run(
        [sys.executable, str(INGEST), '--root', str(tmp_path), '--source', source.name, '--context', 'example',
         '--folder', 'memories/example', '--no-score'],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == (2 if blocked else 0), result.stderr
    report = json.loads(result.stdout)
    assert report['blocked'] is blocked
    assert report['written'] is not blocked
    assert TEST_MARKER not in result.stdout + result.stderr
    if blocked:
        assert any(item['kind'] == 'transcript_password' for item in report['secret_findings'])
        assert not any(path.is_file() for path in (tmp_path / 'data/derived').rglob('*'))
    else:
        assert report['secret_findings'] == []
        assert (tmp_path / report['request_path']).is_file()
