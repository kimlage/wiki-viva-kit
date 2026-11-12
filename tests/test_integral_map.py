from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from tests.test_freshness_impact import commit, git, paths, report
from tests.test_quadrant_projection_report import _wiki
from wiki_core.markdown_link_roles import declare_link_role

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('wiki_integral_map', ROOT / 'scripts/wiki_integral_map.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_map_generation_is_idempotent_and_check_detects_stale(tmp_path, monkeypatch):
    markers = ''.join(f'<!-- integral-map:{q}:start -->\nold\n<!-- integral-map:{q}:end -->\n'
                      for q in ('q1', 'q2', 'q3', 'q4'))
    _wiki(tmp_path, {
        'memories/index.md': '---\npage_id: company\npage_type: context_hub\ntitle: Company\n'
            'blocks: [wiki.block.quadrants.v1]\n---\n# Company\n' + markers,
        'memories/intent.md': '---\npage_id: intent\npage_type: claim\ntitle: Intent\n'
            'moc_parent: memories/index.md\nsubject_ref: company\nsubject_role: perception\n---\n# Intent\n',
    })
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    path = tmp_path / 'memories/index.md'
    assert module.main(['--anchor', 'company', '--check']) == 1
    assert module.main(['--anchor', 'company']) == 0
    rendered = path.read_text()
    assert declare_link_role('[Intent](intent.md)', 'navigation') in rendered
    assert '_Empty: `quadrant_absence` mission._' in rendered
    assert module.main(['--anchor', 'company', '--check']) == 0
    assert module.main(['--anchor', 'company']) == 0
    assert path.read_text() == rendered
    path.write_text(rendered.replace('[Intent](intent.md)', 'stale'))
    assert module.main(['--anchor', 'company', '--check']) == 1


def test_map_links_do_not_propagate_freshness_between_members(tmp_path, monkeypatch):
    markers = ''.join(f'<!-- integral-map:{q}:start -->\n<!-- integral-map:{q}:end -->\n'
                      for q in ('q1', 'q2', 'q3', 'q4'))
    common = 'updated_at: 2026-01-01\nstale_after_days: 30\n'
    _wiki(tmp_path, {
        'memories/index.md': '---\npage_id: company\npage_type: context_hub\ntitle: Company\n'
            + common + 'blocks: [wiki.block.quadrants.v1]\n---\n# Company\n' + markers,
        **{f'memories/{name}.md': f'---\npage_id: {name}\npage_type: claim\ntitle: {name.title()}\n'
           + common + 'moc_parent: memories/index.md\nsubject_ref: company\n'
           'subject_role: perception\n---\n# Claim\n' for name in ('first', 'second')},
    })
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    assert module.main(['--anchor', 'company']) == 0
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
    git(tmp_path, 'config', 'user.name', 'Synthetic Fixture')
    base = commit(tmp_path)
    with (tmp_path / 'memories/first.md').open('a') as stream:
        stream.write('\nChanged factual body.\n')
    result = report(tmp_path, base)
    assert paths(result['included']) == {'memories/first.md'}
    assert not ({'memories/index.md', 'memories/second.md'} & paths(result['blockers']))
    assert sum(edge.get('authored_role') == 'navigation'
               for edge in result['nonpropagating_relations']
               if edge['path'] == 'memories/index.md') >= 2


def test_map_normalizes_windows_separators_before_quoting(tmp_path, monkeypatch):
    markers = ''.join(f'<!-- integral-map:{q}:start -->\n<!-- integral-map:{q}:end -->\n'
                      for q in ('q1', 'q2', 'q3', 'q4'))
    _wiki(tmp_path, {
        'memories/index.md': '---\npage_id: company\npage_type: context_hub\ntitle: Company\n'
            'blocks: [wiki.block.quadrants.v1]\n---\n# Company\n' + markers,
        'memories/claims/first claim.md': '---\npage_id: first\npage_type: claim\ntitle: First\n'
            'moc_parent: memories/index.md\nsubject_ref: company\nsubject_role: perception\n---\n# First\n',
    })
    monkeypatch.setattr(module, 'os', SimpleNamespace(
        path=SimpleNamespace(relpath=lambda *_: r'claims\first claim.md'), sep='\\'))
    _, rendered = module.render_map(tmp_path, 'company')
    assert declare_link_role('[First](claims/first%20claim.md)', 'navigation') in rendered
    assert '%5C' not in rendered
