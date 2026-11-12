from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.test_quadrant_projection_report import _wiki

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
    assert '[Intent](intent.md)' in rendered
    assert '_Empty: `quadrant_absence` mission._' in rendered
    assert module.main(['--anchor', 'company', '--check']) == 0
    assert module.main(['--anchor', 'company']) == 0
    assert path.read_text() == rendered
    path.write_text(rendered.replace('[Intent](intent.md)', 'stale'))
    assert module.main(['--anchor', 'company', '--check']) == 1
