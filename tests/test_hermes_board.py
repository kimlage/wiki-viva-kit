from pathlib import Path
import pytest
from scripts.wiki_hermes_board import install, validate_board_url

@pytest.mark.parametrize('url', ['https://example.org/board', 'http://127.0.0.1.evil/board', 'http://127.0.0.1:0/board', 'http://user:secret@localhost/board', 'http://localhost/board?token=x', 'http://localhost/board#x', 'file:///board', 'http://localhost:invalid/board'])
def test_board_rejects_remote_or_credential_urls(url):
    with pytest.raises(ValueError): validate_board_url(url)


def test_installer_is_idempotent_and_preserves_different_plugin(tmp_path):
    template=Path(__file__).resolve().parents[1] / 'docs/references/templates/deploy/hermes/plugin.js'
    url='http://127.0.0.1:8765/board'
    target=install(template,tmp_path,url)
    assert url in target.read_text()
    assert install(template,tmp_path,url)==target
    target.write_text('existing modification')
    with pytest.raises(FileExistsError): install(template,tmp_path,url)
    assert target.read_text()=='existing modification'
