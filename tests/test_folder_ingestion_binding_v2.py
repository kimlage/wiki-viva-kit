"""Ingestion requests pin the source authorization into the task packet."""
import copy
import hashlib
import json

from tests.test_folder_policy_v2 import project
from tests.test_folder_ingestion_v2 import setup, _synthetic_result
from wiki_core.config import load_config
from wiki_core.folder_ingestion_v2 import ingestion_binding_for_authorization
from wiki_core.ingest import run
from wiki_core.llm.context_pass import result_matches_request


def test_ingestion_marker_is_digested_and_result_bound(project):
    sha, selection = setup(project)
    result = run(str(project / 'a/source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection)
    assert not result.blocked
    request = json.loads((project / result.request_path).read_text())
    packet = request['block_context_package']; auth = request['source_authorization']
    assert packet['ingestion_binding'] == ingestion_binding_for_authorization(auth)
    payload = {key: value for key, value in packet.items() if key != 'packet_digest'}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':')).encode()).hexdigest()
    assert digest == packet['packet_digest']
    reported = _synthetic_result(request)
    assert result_matches_request(reported, request, request['chunks'][0], recording=True)
    omitted = copy.deepcopy(request); del omitted['block_context_package']['ingestion_binding']
    assert not result_matches_request(reported, omitted, omitted['chunks'][0], recording=True)
    changed = copy.deepcopy(request); changed['source_authorization']['source_sha256'] = '0' * 64
    assert not result_matches_request(reported, changed, changed['chunks'][0], recording=True)
