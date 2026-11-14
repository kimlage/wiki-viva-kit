from wiki_core.config import WikiConfig
from wiki_core.input_stage import LOCAL_FOLDER_INPUT_STATUS
from wiki_core.llm import context_pass
from wiki_core.paths import WikiPaths
from scripts.wiki_llm_context_pass import _emitted_requests


def test_local_request_source_selection_checks_before_loading(tmp_path, monkeypatch):
    paths = WikiPaths(tmp_path, WikiConfig())
    request = {'source_id': 'synthetic-b', 'input_stage_status': LOCAL_FOLDER_INPUT_STATUS,
               'chunks': [{'chunk_id': 'synthetic', 'source_id': 'synthetic-b',
                           'chunk_hash_sha256': 'a' * 64, 'context_sha256': 'b' * 64,
                           'cache_key': 'c' * 64}]}
    request['folder_request_id'] = context_pass.local_request_identity(request)
    context_pass.retain_local_request(paths, request)
    loaded = []
    original = context_pass.load_local_request

    def observe(*args, **kwargs):
        loaded.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(context_pass, 'load_local_request', observe)
    assert _emitted_requests(paths, source_id='synthetic-a', local_request=request) == []
    assert not loaded
    assert _emitted_requests(paths, source_id='synthetic-b', local_request=request) == [request]
    assert _emitted_requests(paths, local_request=request) == [request]
    assert len(loaded) == 2
