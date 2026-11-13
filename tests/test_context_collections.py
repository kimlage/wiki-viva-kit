"""Synthetic canonical pages: legacy layout and two nested local contexts."""
from __future__ import annotations

import datetime as dt
import hashlib
from collections import Counter

import pytest
import yaml

from scripts import wiki_source_registry as registry
from scripts.wiki_operation_compile import build_page, collect_actions
from wiki_core.action_transition import _render_document
from wiki_core.closure import build_ingestion_closure_report
from wiki_core.config import load_config
from wiki_core.coordination import dialogue_action, transition_dialogue_action
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.information_relations import authored_graph, projection_input_edges
from wiki_core.input_stage import compile_input_stage, render_input_stage_markdown
from wiki_core.paths import WikiPaths
from wiki_core.source_config import find_source_config
from wiki_core.web.sources import build_sources_payload

TODAY = dt.date(2026, 11, 12)


def page(path, page_id, page_type, **fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_document({
        'page_id': page_id, 'page_type': page_type, 'title': page_id,
        'context': 'system', 'updated_at': TODAY.isoformat(), **fields,
    }, f'# {page_id}\n\nSynthetic evidence.\n'))
    return path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(params=['legacy-and-local', 'local-only-custom'])
def collections(tmp_path, monkeypatch, request):
    custom = request.param == 'local-only-custom'
    settings = {'contexts': ['alpha', 'beta']}
    if custom:
        settings['paths'] = {'memory_root': 'knowledge/notes', 'actions_dirname': 'acoes',
                             'sources_dirname': 'fontes', 'operation_page': 'knowledge/notes/operations.md',
                             'operational_pass_page': 'knowledge/notes/system/operational-pass.md',
                             'source_registry_page': 'knowledge/notes/system/source-registry.md'}
        settings['root_entity'] = {'input_stage_page': 'knowledge/notes/system/input-stage.md'}
    (tmp_path / 'wiki.config.yaml').write_text(yaml.safe_dump(settings))
    config = load_config(tmp_path)
    paths = WikiPaths(tmp_path, config)
    monkeypatch.setattr(registry, 'ROOT', tmp_path)
    action_refs, source_refs = [], []
    contexts = [('teams/alpha', 'alpha'), ('teams/beta/research', 'beta')]
    if not custom:
        contexts.insert(0, ('', 'system'))
    for folder, context in contexts:
        base = paths.memory_root / folder
        page(base / 'index.md', f'hub-{context}', 'context_hub', context=context)
        action = page(base / config.paths['actions_dirname'] / 'task.md',
                      f'action-{context}', 'action', context=context,
                      owner_kind='human', owner_ref='synthetic-owner', action_state='open',
                      next_action='Review synthetic evidence', source_refs=['source-alpha'])
        source = page(base / config.paths['sources_dirname'] / 'evidence.md',
                      f'source-{context}', 'source', context=context, ingestion_state='ingested')
        page(source.parent / 'config' / 'recipe.md', f'config-{context}', 'source_config',
             context=context, source_refs=[paths.rel(source)], perspectives_required=['technical'])
        action_refs.append(paths.rel(action))
        source_refs.append(paths.rel(source))
    # Typed pages outside the configured collection names are not candidates.
    page(paths.memory_root / 'notes/other-action.md', 'other-action', 'action', action_state='open')
    page(paths.memory_root / 'notes/other-source.md', 'other-source', 'source', ingestion_state='ingested')
    policy = {'schema_version': 'wiki_coordination.v1', 'profiles': {
        'alpha': {'label': 'Alpha', 'scope': 'Synthetic alpha', 'action_ids': ['action-alpha']},
        'beta': {'label': 'Beta', 'scope': 'Synthetic beta', 'action_ids': ['action-beta']}}}
    (tmp_path / 'wiki.coordination.yaml').write_text(yaml.safe_dump(policy))
    return paths, action_refs, source_refs


def test_all_projections_use_the_same_canonical_pages_once(collections):
    paths, actions, sources = collections
    assert paths.action_files() == sorted(paths.root / ref for ref in actions)
    assert {a.page_id for a in collect_actions(paths)} == {
        parse_frontmatter(paths.root / ref)[0]['page_id'] for ref in actions}
    assert len(collect_actions(paths)) == len(actions)
    catalog = compile_input_stage(paths.root, paths.config, generated_at=TODAY)
    assert Counter(r['source_path'] for r in catalog['sources']) == Counter(sources)
    closure = build_ingestion_closure_report(paths.root, paths.config)
    assert Counter(r['path'] for r in closure['ingested_sources']) == Counter(sources)
    payload = build_sources_payload(paths.root, paths.config, today=TODAY)
    assert Counter(r['path'] for r in payload['sources']) == Counter(sources)
    assert Counter(r['rel'] for r in registry.collect_sources(paths)) == Counter(sources)
    for target, rendered in [
        (paths.operation_page, build_page(paths.root, paths.config, generated_at=dt.datetime(2026, 11, 12))),
        (paths.input_stage_page, render_input_stage_markdown(catalog, paths.config)),
        (paths.source_registry_page, registry.build_registry(paths, paths.config, TODAY.isoformat())),
    ]:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered)
        fm, _ = parse_frontmatter(rendered)
        graph = authored_graph(paths.root, paths.config)
        edges = projection_input_edges(paths.rel(target), fm, graph['nodes'])
        assert set(actions if target == paths.operation_page else sources) <= {e['target'] for e in edges}
        if target == paths.source_registry_page:
            assert Counter(fm['collection']['members']) == Counter(r['source_id'] for r in payload['sources'])
    # Two contexts reference one shared source identity, without a second page.
    shared = [r for r in catalog['sources'] if r['source_page_id'] == 'source-alpha']
    assert len(shared) == 1
    assert all(parse_frontmatter(paths.root / ref)[0]['source_refs'] == ['source-alpha'] for ref in actions)
    if paths.config.paths['memory_root'] != 'memories':
        assert not paths.actions_dir.exists() and not paths.sources_dir.exists()


def test_local_config_and_dialogue_keep_identity_owner_context_and_cas(collections):
    paths, actions, sources = collections
    ref = next(ref for ref in actions if '/teams/alpha/' in ref)
    action = paths.root / ref
    before, _ = parse_frontmatter(action)
    previous_sha = sha(action)
    event = {'event_id': 'comment-local-1', 'kind': 'comment', 'text': 'Synthetic review', 'coordinator': 'alpha'}
    receipt = transition_dialogue_action(paths.root, ref, 'action-alpha', event, expected_sha256=previous_sha)
    after, _ = parse_frontmatter(action)
    assert receipt.page_ref == ref and receipt.before_sha256 == previous_sha and receipt.after_sha256 == sha(action)
    for key in ('page_id', 'context', 'owner_kind', 'owner_ref', 'action_state'):
        assert after[key] == before[key]
    assert len(after['action_state_history']) == 1
    stable = action.read_bytes()
    with pytest.raises(ValueError):
        transition_dialogue_action(paths.root, ref, 'action-alpha', {**event, 'event_id': 'comment-local-2'},
                                   expected_sha256=previous_sha)
    assert action.read_bytes() == stable
    for source_ref in sources:
        found = find_source_config(paths.root, paths.config, source_ref)
        assert found['path'] == paths.rel((paths.root / source_ref).parent / 'config/recipe.md')
        assert found['perspectives_required'] == ['technical']


def test_declared_registry_selection_does_not_expand_for_local_roots(collections):
    paths, _actions, sources = collections
    config_path = paths.root / 'wiki.config.yaml'
    settings = yaml.safe_load(config_path.read_text())
    direct = [ref for ref in sources if (paths.root / ref).parent == paths.sources_dir]
    local = next(ref for ref in sources if '/teams/alpha/' in ref)
    for selected, expected in [([], direct), ([local], [*direct, local])]:
        settings['source_registry'] = {'nested_sources': selected}
        config_path.write_text(yaml.safe_dump(settings))
        assert Counter(r['rel'] for r in registry.collect_sources(paths)) == Counter(expected)


@pytest.mark.parametrize('boundary', ['symlink-file', 'symlink-directory', 'git-file', 'git-directory'])
def test_discovery_and_explicit_dialogue_refuse_boundaries(collections, boundary):
    paths, actions, sources = collections
    base = paths.memory_root / 'excluded/context'
    action = page(base / paths.config.paths['actions_dirname'] / 'task.md', 'action-alpha', 'action', action_state='open')
    page(base / paths.config.paths['sources_dirname'] / 'source.md', 'source-excluded', 'source')
    ref = paths.rel(action)
    if boundary == 'symlink-file':
        action.unlink()
        action.symlink_to(paths.root / actions[0])
        source = base / paths.config.paths['sources_dirname'] / 'source.md'
        source.unlink()
        source.symlink_to(paths.root / sources[0])
    elif boundary == 'symlink-directory':
        saved = base.with_name('saved')
        base.rename(saved)
        (saved / '.git').mkdir()
        base.symlink_to(saved, target_is_directory=True)
    elif boundary == 'git-file':
        (base / '.git').write_text('gitdir: synthetic-separate-repository')
    else:
        (base / '.git').mkdir()
    assert Counter(paths.rel(p) for p in paths.action_files()) == Counter(actions)
    assert Counter(r['rel'] for r in registry.collect_sources(paths)) == Counter(sources)
    assert Counter(r['source_path'] for r in compile_input_stage(paths.root, paths.config)['sources']) == Counter(sources)
    assert Counter(r['path'] for r in build_sources_payload(paths.root, paths.config)['sources']) == Counter(sources)
    with pytest.raises(ValueError):
        dialogue_action(paths.root, ref, 'action-alpha', {'coordinator': 'alpha'})


@pytest.mark.parametrize('invalid', ['route', 'identity', 'outside-collection', 'escape'])
def test_explicit_path_never_grants_route_or_writes(collections, invalid):
    paths, actions, _sources = collections
    ref = next(ref for ref in actions if '/teams/beta/' in ref)
    action_id, coordinator = 'action-beta', 'beta'
    if invalid == 'route':
        coordinator = 'alpha'
    elif invalid == 'identity':
        action_id = 'action-alpha'
    elif invalid == 'outside-collection':
        ref = paths.rel(page(paths.memory_root / 'teams/beta/rogue.md', action_id, 'action'))
    else:
        ref = paths.rel(paths.memory_root) + '/../' + ref
    before = {r: (paths.root / r).read_bytes() for r in actions}
    with pytest.raises(ValueError):
        transition_dialogue_action(paths.root, ref, action_id,
            {'event_id': 'comment-denied-1', 'kind': 'comment', 'text': 'Denied', 'coordinator': coordinator},
            expected_sha256=sha(paths.root / actions[0]))
    assert all((paths.root / r).read_bytes() == raw for r, raw in before.items())


def test_projection_directory_predicate_validates_and_cannot_match_sibling_names():
    spec = {'page_types': ['source'], 'fields': ['page_id'], 'path_prefix': 'knowledge', 'path_directory': 'fontes'}
    nodes = {path: {'page_type': 'source'} for path in [
        'knowledge/fontes/one.md', 'knowledge/team/nested/fontes/two.md',
        'knowledge/team/other-fontes/three.md', 'elsewhere/fontes/four.md', 'knowledge/fontes.md']}
    edges = projection_input_edges('projection.md', {'projection_inputs': [spec]}, nodes)
    assert {e['target'] for e in edges} == {'knowledge/fontes/one.md', 'knowledge/team/nested/fontes/two.md'}
    for invalid in [None, '', '..', '../fontes', 'a/b', '/fontes', 'a\\b', ['fontes'], 'bad\nname']:
        with pytest.raises(ValueError):
            projection_input_edges('projection.md', {'projection_inputs': [{**spec, 'path_directory': invalid}]}, nodes)


def test_new_local_candidates_are_projection_inputs_before_they_are_displayed(collections):
    from wiki_core.information_impact import evaluate_information_impact
    paths, _actions, _sources = collections
    catalog = compile_input_stage(paths.root, paths.config, generated_at=TODAY)
    for target, content in [
        (paths.operation_page, build_page(paths.root, paths.config, generated_at=dt.datetime(2026, 11, 12))),
        (paths.input_stage_page, render_input_stage_markdown(catalog, paths.config)),
        (paths.source_registry_page, registry.build_registry(paths, paths.config, TODAY.isoformat())),
    ]:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    before = authored_graph(paths.root, paths.config)
    base = paths.memory_root / 'teams/new/deep'
    action = page(base / paths.config.paths['actions_dirname'] / 'new.md', 'action-new', 'action', action_state='open')
    source = page(base / paths.config.paths['sources_dirname'] / 'new.md', 'source-new', 'source', ingestion_state='ingested')
    report = evaluate_information_impact(authored_graph(paths.root, paths.config), before,
        {paths.rel(action), paths.rel(source)}, today=TODAY)
    assert {paths.rel(paths.operation_page), paths.rel(paths.input_stage_page), paths.rel(paths.source_registry_page)} <= {
        row['path'] for row in report['included']}


def test_guarded_local_discovery_does_not_read_unselected_bodies(collections, monkeypatch):
    from wiki_core.audit_r1_inventory import SelectedReads
    from wiki_core.input_stage import _source_pages
    paths, _actions, sources = collections
    # Trusted admitted metadata can mention more pages than the selected bodies.
    contents = {ref: (paths.root / ref).read_bytes() for ref in sources}
    physical = {'files': {ref: {} for ref in sources}, 'directories': {}}
    guarded = SelectedReads(paths.root, physical, contents)
    with monkeypatch.context() as guard:
        guard.setattr(type(paths.root), 'read_text', lambda *a, **k: pytest.fail('filesystem body read'))
        assert Counter(p['path'] for p in _source_pages(paths.root, paths, reads=guarded)) == Counter(sources)
        guarded.contents = {sources[0]: contents[sources[0]]}
        with pytest.raises(RuntimeError, match='outside admitted selection'):
            _source_pages(paths.root, paths, reads=guarded)


def test_overlapping_named_directories_are_not_traversed_twice(collections):
    paths, actions, sources = collections
    nested_action = page((paths.root / actions[0]).parent / 'child' / paths.config.paths['actions_dirname'] / 'nested.md',
                         'nested-action', 'action', action_state='open')
    nested_source = page((paths.root / sources[0]).parent / 'child' / paths.config.paths['sources_dirname'] / 'nested.md',
                         'nested-source', 'source')
    assert Counter(paths.rel(p) for p in paths.action_files()) == Counter([*actions, paths.rel(nested_action)])
    assert Counter(r['rel'] for r in registry.collect_sources(paths)) == Counter([*sources, paths.rel(nested_source)])
