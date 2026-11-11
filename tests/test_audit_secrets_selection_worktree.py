"""Synthetic tests for the admitted worktree secrets subcheck, not global audit."""
import yaml
import pytest

from tests.test_audit_r1_inventory import git, repo, run
from tests.test_wiki_audit import _load_wiki_audit
from wiki_core import audit_secrets_selection as secrets
from wiki_core.context_policy import PolicyError
from wiki_core.coordination_context import CoordinationBinding


def _approve_fixture(repo, *, clear_deny):
    root, _, _, _ = repo
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    if clear_deny:
        config['context_access']['.']['policy']['deny'] = {}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'synthetic approved baseline')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', base)
    return root, base


def _args(root, base):
    return dict(root=root, binding=CoordinationBinding(('.',), 'refs/remotes/origin/main'),
                context_id='.', approved_revision=base, base=base, head=base,
                branch='wiki/synthetic', normative_paths=['wiki.config.yaml'])


def _inventory(args):
    return secrets.inventory(**args)


def test_denied_candidate_refuses_before_any_selected_body(repo, monkeypatch):
    snapshot = run(repo)
    monkeypatch.setattr(secrets, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='selection unavailable'):
        secrets.plan_worktree_secrets(snapshot)


def test_complete_worktree_candidates_match_legacy_check_and_detect_secret(repo, monkeypatch):
    root, base = _approve_fixture(repo, clear_deny=True)
    (root / 'candidate.py').write_text('TOKEN = "' + 'sk-' + 'proj-' + 'A' * 24 + '"\n')
    (root / 'cache/ignored.txt').write_text('ignored synthetic data')
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = secrets.plan_worktree_secrets(snapshot)
    audit = _load_wiki_audit()
    monkeypatch.setattr(audit, 'ROOT', root)
    audit._audit_git_inventory.cache_clear()
    audit.tracked_files.cache_clear()
    assert {x['path'] for x in plan['selection']['inputs']} == set(audit._scannable_text_files())
    assert 'cache/ignored.txt' not in {x['path'] for x in plan['selection']['inputs']}
    observed = []
    result = secrets.scan_worktree_secrets(**args, inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda p: observed.append(p) is None)
    assert observed and result['state'] == 'failed'
    assert any('candidate.py' in item and 'openai_api_key' in item for item in result['diagnostics'])
    assert result['global_audit'] == 'not_performed'
    assert result['gate_state'] == 'blocked_incomplete_coverage'
    legacy_errors = []
    audit.audit_secrets(legacy_errors, audit.WikiConfig())
    assert legacy_errors == result['diagnostics']


def test_refused_host_and_revoked_admission_precede_candidate_reads(repo, monkeypatch):
    root, base = _approve_fixture(repo, clear_deny=True)
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = secrets.plan_worktree_secrets(snapshot)
    monkeypatch.setattr(secrets, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='host admission unavailable'):
        secrets.scan_worktree_secrets(**args, inventory_sha256=snapshot['inventory_sha256'],
            plan_sha256=plan['plan_sha256'], admit=lambda _: False)
    decisions = iter([True, False])
    result = secrets.scan_worktree_secrets(**args, inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: next(decisions))
    assert result['state'] == 'partial' and result['source_body_attempts_may_have_read_bytes'] == 0


def test_staged_deletion_is_not_silently_counted_complete(repo, monkeypatch):
    root, base = _approve_fixture(repo, clear_deny=True)
    git(root, 'rm', '-q', 'restricted/denied.json')
    snapshot = _inventory(_args(root, base))
    monkeypatch.setattr(secrets, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='secrets selection unavailable'):
        secrets.plan_worktree_secrets(snapshot)


def test_staged_deletion_with_ignored_body_is_not_silently_omitted(repo, monkeypatch):
    root, _, _, _ = repo
    with (root / '.gitignore').open('a') as stream:
        stream.write('restricted/denied.json\n')
    root, base = _approve_fixture(repo, clear_deny=True)
    git(root, 'rm', '--cached', '-q', 'restricted/denied.json')
    snapshot = _inventory(_args(root, base))
    assert 'restricted/denied.json' in snapshot['ignored']
    monkeypatch.setattr(secrets, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='secrets selection unavailable'):
        secrets.plan_worktree_secrets(snapshot)


def test_known_denied_index_alias_refuses_before_body_reads(repo, monkeypatch):
    root, _, _, _ = repo
    git(root, 'mv', 'restricted/denied.json', 'restricted/denied.bin')
    root, base = _approve_fixture(repo, clear_deny=False)
    (root / 'alias.txt').write_bytes((root / 'restricted/denied.bin').read_bytes())
    git(root, 'add', 'alias.txt')
    snapshot = _inventory(_args(root, base))
    assert any(row['path'] == 'alias.txt' and row['oid'] in snapshot['denied_oid_aliases']
               for row in snapshot['index'])
    monkeypatch.setattr(secrets, '_worktree_bytes', lambda *_: pytest.fail('body opened'))
    with pytest.raises(PolicyError, match='secrets selection unavailable'):
        secrets.plan_worktree_secrets(snapshot)


def test_failed_read_reports_attempt_even_when_no_body_was_validated(repo, monkeypatch):
    root, base = _approve_fixture(repo, clear_deny=True)
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = secrets.plan_worktree_secrets(snapshot)
    original = secrets._worktree_bytes
    def read_then_fail(root, row):
        original(root, row)
        raise OSError('synthetic post-read failure')
    monkeypatch.setattr(secrets, '_worktree_bytes', read_then_fail)
    result = secrets.scan_worktree_secrets(**args, inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert result['state'] == 'partial'
    assert result['source_bodies_validated'] == 0
    assert result['source_body_attempts_may_have_read_bytes'] == 1


def test_disabled_secrets_check_does_not_report_completion(repo):
    root, _, _, _ = repo
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['audit'] = {'forbid_access_secrets': False}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    root, base = _approve_fixture(repo, clear_deny=True)
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = secrets.plan_worktree_secrets(snapshot)
    result = secrets.scan_worktree_secrets(**args, inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert result['state'] == 'partial' and result['scan_progress'] == 'partial_or_unknown'
    assert result['global_audit'] == 'not_performed'


def test_admission_withdrawn_after_scan_hides_diagnostics(repo):
    root, base = _approve_fixture(repo, clear_deny=True)
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = secrets.plan_worktree_secrets(snapshot)
    decisions = iter([True] * (len(plan['selection']['inputs']) + 2) + [False])
    result = secrets.scan_worktree_secrets(**args, inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: next(decisions))
    assert result['state'] == 'partial' and 'diagnostics' not in result
    assert result['scan_progress'] == 'partial_or_unknown'


def test_binary_eligible_input_reports_partial_not_scan_success(repo):
    root, base = _approve_fixture(repo, clear_deny=True)
    (root / 'synthetic.json').write_bytes(b'\x00synthetic')
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = secrets.plan_worktree_secrets(snapshot)
    result = secrets.scan_worktree_secrets(**args, inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert result['state'] == 'partial' and result['global_audit'] == 'not_performed'


@pytest.mark.parametrize('data', [b'\xff\xfe synthetic', b'valid\x01control'])
def test_nontext_without_nul_is_partial(repo, data):
    root, base = _approve_fixture(repo, clear_deny=True)
    (root / 'synthetic.json').write_bytes(data)
    args = _args(root, base)
    snapshot = _inventory(args)
    plan = secrets.plan_worktree_secrets(snapshot)
    result = secrets.scan_worktree_secrets(**args, inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert result['state'] == 'partial'
    assert result['coverage']['worktree'] == 'partial_or_unknown'
    assert result['global_audit'] == 'not_performed'
