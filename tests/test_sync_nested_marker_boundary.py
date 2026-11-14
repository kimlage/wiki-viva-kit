from pathlib import Path

import pytest

from tests.test_wiki_sync_from_kit import _fixture, _git, _run, _sync_module


@pytest.mark.parametrize('operation', ['add', 'change'])
def test_nested_marker_created_after_temporary_refuses_target(tmp_path: Path, monkeypatch, operation: str) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    target = consumer / 'portable/tool.txt'
    if operation == 'change':
        assert _run(kit, consumer, manifest).returncode == 0
        lock_before = (consumer / 'kit.lock').read_bytes()
        (kit / 'portable/tool.txt').write_text('v2\n')
        _git(kit, 'add', 'portable/tool.txt')
        _git(kit, 'commit', '-qm', 'synthetic change')
    else:
        lock_before = None
    sync = _sync_module()
    plan = sync.build_plan(kit, consumer, manifest, [])
    assert 'portable/tool.txt' in plan['c1'][operation]
    real_chmod = sync.os.chmod
    def add_marker(path, mode):
        real_chmod(path, mode)
        if Path(path).parent == target.parent:
            (target.parent / '.git').write_text('synthetic marker\n')
    monkeypatch.setattr(sync.os, 'chmod', add_marker)
    with pytest.raises(sync.SyncError, match='nested repository'):
        sync._copy_c1(kit, consumer, plan)
    if operation == 'add':
        assert not target.exists()
        assert not (consumer / 'kit.lock').exists()
        assert (consumer / 'generate.py').exists()  # Earlier work is not rolled back.
    else:
        assert target.read_text() == 'v1\n'
        assert (consumer / 'kit.lock').read_bytes() == lock_before
    assert not list(consumer.rglob('.wiki-sync-*'))
