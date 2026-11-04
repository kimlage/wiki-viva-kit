"""Index authority is checked from metadata before instruction bodies."""
import pytest
import yaml

from tests.test_folder_policy_v2 import project, git, commit, proposal_v2
from tests.test_folder_requalification_v2 import prepare
from tests.test_folder_mandatory_v2 import equivalent_repo
from wiki_core.context_policy import PolicyError
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_impact_v2 import assess_folder_source_v2, FolderImpactError
from wiki_core.folder_requalification_v2 import requalify_explicit_v1_requirement, RequalificationError
from wiki_core.repository_reader import RepositoryReader


def deny_index(repo):
    path=repo/'wiki-context-controls.yaml'; data=yaml.safe_load(path.read_text())
    data['controls']['a']['policy']['deny']={'read':['a/index.md']}
    path.write_text(yaml.safe_dump(data)); commit(repo)


def forbid_instruction_read(monkeypatch):
    original=RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if ref.endswith('/AGENTS.md') or ref=='AGENTS.md' or ref.endswith('/AGENTS.override.md'):
            raise AssertionError('instruction body opened before index authorization')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader,'read',spy)


def test_packet_absent_controls_does_not_open_instructions(project, monkeypatch):
    path=project/'wiki-context-controls.yaml'; data=yaml.safe_load(path.read_text())
    del data['controls']['a']; del data['controls']['a/aux/b']
    path.write_text(yaml.safe_dump(data)); commit(project)
    p=load_folder_policy_v2(project,'HEAD'); forbid_instruction_read(monkeypatch)
    with pytest.raises(PolicyError, match='index is not authorized'):
        build_folder_packet_v2(project,p,'a',20000,index_path='a/index.md',content_revision='HEAD',
                               task_id='x',goal='x',output='x',integrator='x')


def test_impact_denied_index_does_not_open_instructions(project, monkeypatch):
    _, _, _, packet, result=proposal_v2(project)
    git(project,'checkout','-q','-'); git(project,'merge','--ff-only','wiki/folder-task')
    git(project,'update-ref','refs/remotes/origin/main','HEAD'); deny_index(project)
    p=load_folder_policy_v2(project,'HEAD'); forbid_instruction_read(monkeypatch)
    with pytest.raises(FolderImpactError,match='authority unavailable'):
        assess_folder_source_v2(project,p,packet=packet,result=result,target='a/report.md',source='a/source.md',field='amount')


def test_requalification_denied_index_does_not_open_instructions(equivalent_repo, monkeypatch):
    _, proposal, packet, result, _=prepare(equivalent_repo)
    deny_index(equivalent_repo); p=load_folder_policy_v2(equivalent_repo,'HEAD'); forbid_instruction_read(monkeypatch)
    with pytest.raises(RequalificationError,match='authority unavailable'):
        requalify_explicit_v1_requirement(equivalent_repo,p,folder='a',index_path='a/index.md',
            consumer='a/result.md',requirement_index=0,packet=packet,result=result,proposal_head=proposal)
