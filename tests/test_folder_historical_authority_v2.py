"""Sentinel coverage for historical rule and evidence authorization."""
from copy import deepcopy

import pytest
import yaml

from tests.test_folder_policy_v2 import project, put, commit, git
from tests.test_folder_auxiliary_v2 import MARKER, _packet, _result
from wiki_core.context_policy import PolicyError
from wiki_core.context_selection import digest
from wiki_core.folder_impact_v2 import FolderImpactError, assess_folder_source_v2
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.repository_reader import RepositoryReader


def retag(packet, *, policy_revision=None, content_revision=None):
    packet = deepcopy(packet)
    if policy_revision is not None:
        packet['policy_revision'] = policy_revision
        for row in packet['inputs']:
            if row['kind'] != 'evidence': row['revision'] = policy_revision
    if content_revision is not None:
        packet['content_revision'] = content_revision
        for row in packet['inputs']:
            if row['kind'] == 'evidence': row['revision'] = content_revision
    packet['packet_digest'] = digest({k:v for k,v in packet.items() if k != 'packet_digest'})
    return packet


def test_old_omitted_mandatory_is_not_opened(project, monkeypatch):
    put(project,'a/AGENTS.md','# Rules\n\n## Wiki v2: mandatory references\n\n- [Rule](secret.md)\n')
    put(project,'a/secret.md','Synthetic denied historical body\n'); put(project,'a/source.md','source\n');commit(project)
    old=git(project,'rev-parse','HEAD')
    put(project,'a/AGENTS.md','# Rules\n');put(project,'a/report.md','report\n')
    config=project/'wiki-context-controls.yaml'; data=yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny']={'read':['a/secret.md']}
    config.write_text(yaml.safe_dump(data));commit(project);policy=load_folder_policy_v2(project,'HEAD')
    evidence=[{'path':'a/source.md','producer_folder':'a','reason':'synthetic','use':'interpret','classification':'synthetic'}]
    packet=build_folder_packet_v2(project,policy,'a',50000,index_path='a/index.md',content_revision='HEAD',
        task_id='x',goal='x',output='a/report.md',integrator='x',evidence=evidence)
    packet=retag(packet,policy_revision=old,content_revision=old);result=_result(packet,'a/report.md')
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if self.revision==old and path=='a/secret.md':pytest.fail('denied historical mandatory opened')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderImpactError,match='historical instruction, mandatory or index blob changed'):
        assess_folder_source_v2(project,policy,packet=packet,result=result,target='a/report.md',source='a/source.md')


@pytest.mark.parametrize('route',['policy','content','direct'])
def test_removed_auxiliary_marker_never_opened_historically(project,monkeypatch,route):
    put(project,'a/aux/AGENTS.md','# Outer\n\n'+MARKER)
    put(project,'a/aux/deep/AGENTS.md','# Historic inner\n\n'+MARKER)
    put(project,'a/aux/deep/source.md','Synthetic source\n');commit(project);old=git(project,'rev-parse','HEAD')
    (project/'a/aux/deep/AGENTS.md').unlink()
    put(project,'a/aux/deep/report.md','Synthetic report\n')
    config=project/'wiki-context-controls.yaml';data=yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny']={'read':['a/aux/deep/AGENTS.md']}
    config.write_text(yaml.safe_dump(data));commit(project);policy=load_folder_policy_v2(project,'HEAD')
    packet=_packet(project,policy,source='a/aux/deep/source.md',output='a/aux/deep/report.md',start='a/aux/deep')
    if route=='policy':packet=retag(packet,policy_revision=old,content_revision=old)
    elif route=='content':packet=retag(packet,content_revision=old)
    result=_result(packet,'a/aux/deep/report.md')
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if self.revision==old and path=='a/aux/deep/AGENTS.md':pytest.fail('denied old auxiliary marker opened')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    if route=='direct':
        with pytest.raises(PolicyError):
            build_folder_packet_v2(project,policy,'a',50000,index_path='a/index.md',content_revision=old,
                task_id='x',goal='x',output='a/aux/deep/report.md',integrator='x',start_folder='a/aux/deep',
                evidence=[{'path':'a/aux/deep/source.md','producer_folder':'a','reason':'synthetic',
                           'use':'interpret','classification':'synthetic'}])
    else:
        with pytest.raises((FolderImpactError,PolicyError)):
            assess_folder_source_v2(project,policy,packet=packet,result=result,
                                    target='a/aux/deep/report.md',source='a/aux/deep/source.md')


def test_later_historically_denied_evidence_blocks_before_first_source(project,monkeypatch):
    for name in ('first','second'):put(project,f'a/{name}.md',f'Synthetic {name}\n')
    config=project/'wiki-context-controls.yaml';data=yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny']={'read':['a/second.md']};config.write_text(yaml.safe_dump(data));commit(project)
    old=git(project,'rev-parse','HEAD');del data['controls']['a']['policy']['deny'];config.write_text(yaml.safe_dump(data))
    put(project,'a/report.md','Synthetic report\n');commit(project);policy=load_folder_policy_v2(project,'HEAD')
    evidence=[{'path':f'a/{name}.md','producer_folder':'a','reason':'synthetic','use':'interpret','classification':'synthetic'} for name in ('first','second')]
    packet=build_folder_packet_v2(project,policy,'a',50000,index_path='a/index.md',content_revision='HEAD',
                                  task_id='x',goal='x',output='a/report.md',integrator='x',evidence=evidence)
    forged=retag(packet,policy_revision=old,content_revision=old);result=_result(forged,'a/report.md')
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if self.revision==old and path in ('a/first.md','a/second.md'):pytest.fail('historical source opened before all authority checks')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderImpactError,match='historical evidence authority unavailable'):
        assess_folder_source_v2(project,policy,packet=forged,result=result,target='a/report.md',source='a/first.md')
    with pytest.raises(PolicyError,match='historical v2 evidence authority unavailable'):
        build_folder_packet_v2(project,policy,'a',50000,index_path='a/index.md',content_revision=old,
            task_id='x',goal='x',output='a/report.md',integrator='x',evidence=evidence)


def test_direct_builder_checks_all_current_evidence_before_old_source(project,monkeypatch):
    for name in ('first','second'):put(project,f'a/{name}.md',f'Synthetic {name}\n')
    commit(project);old=git(project,'rev-parse','HEAD')
    config=project/'wiki-context-controls.yaml';data=yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny']={'read':['a/second.md']}
    config.write_text(yaml.safe_dump(data));commit(project);policy=load_folder_policy_v2(project,'HEAD')
    evidence=[{'path':f'a/{name}.md','producer_folder':'a','reason':'synthetic','use':'interpret','classification':'synthetic'} for name in ('first','second')]
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if self.revision==old and path in ('a/first.md','a/second.md'):
            pytest.fail('historical source opened before current evidence checks')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(PolicyError,match='v2 evidence connection unavailable'):
        build_folder_packet_v2(project,policy,'a',50000,index_path='a/index.md',content_revision=old,
            task_id='x',goal='x',output='a/report.md',integrator='x',evidence=evidence)
