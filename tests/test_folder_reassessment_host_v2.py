"""Opt-in host-bound source reassessment using synthetic repositories only."""
from copy import deepcopy

import pytest
import yaml

from tests.test_folder_policy_v2 import project, put, commit, git
from tests.test_folder_reassessment_v2 import setup_flow
from wiki_core.folder_coordination_v2 import FolderCoordinationError, FolderHostBinding
from wiki_core.folder_reassessment_host_v2 import prepare_folder_reassessment
from wiki_core.repository_reader import RepositoryReader


def payload(repo,report,*,candidates=None):
    return {'folder':'a','approved_revision':git(repo,'rev-parse','HEAD'),'source':'a/source.md',
            'reports':[report] if report else [],'candidates':candidates or ['a/report.md']}


def test_host_bound_reassessment_matches_selected_report(project):
    report=setup_flow(project);request=payload(project,report,candidates=['a/report.md','a/second.md'])
    out=prepare_folder_reassessment(project,FolderHostBinding(project,('a',)),request)
    assert out['mode']=='host_bound' and out['enforcement_claim']=='none'
    assert out['reassessment']['coverage']=='selected_authorized_consumer_paths_and_explicit_reports_only'
    assert [row['state'] for row in out['reassessment']['consumers']] == [
        'verification_pending','declared_without_report','declared_without_report']
    assert 'Independent interpretation' not in str(out)


def test_unbound_folder_and_root_refused_before_policy_load(project,monkeypatch,tmp_path):
    import wiki_core.folder_coordination_v2 as host
    report=setup_flow(project);request=payload(project,report)
    binding=FolderHostBinding(project,('a',))
    def sentinel(*args,**kwargs):pytest.fail('policy opened before host binding')
    monkeypatch.setattr(host,'load_folder_policy_v2',sentinel)
    wrong=deepcopy(request);wrong['folder']='a/aux/b';wrong['candidates']=['a/aux/b/report.md'];wrong['reports']=[]
    with pytest.raises(FolderCoordinationError):prepare_folder_reassessment(project,binding,wrong)
    with pytest.raises(FolderCoordinationError):prepare_folder_reassessment(tmp_path/'wrong',binding,request)
    with pytest.raises(FolderCoordinationError):prepare_folder_reassessment(project,None,request)


def test_cross_owner_candidate_refused_before_consumer_read(project,monkeypatch):
    report=setup_flow(project);request=payload(project,None,candidates=['a/aux/b/index.md'])
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path!='wiki-context-controls.yaml':pytest.fail('body read before candidate authority')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderCoordinationError,match='candidate authority'):
        prepare_folder_reassessment(project,FolderHostBinding(project,('a',)),request)


def test_denied_source_refused_before_consumers_or_sources(project,monkeypatch):
    report=setup_flow(project)
    config=project/'wiki-context-controls.yaml';data=yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny']={'read':['a/source.md']};config.write_text(yaml.safe_dump(data));commit(project)
    request=payload(project,report)
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path in ('a/source.md','a/report.md','a/second.md'):pytest.fail('body read before source denial')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderCoordinationError,match='source authority'):
        prepare_folder_reassessment(project,FolderHostBinding(project,('a',)),request)


def test_later_report_denial_precedes_any_consumer_or_evidence(project,monkeypatch):
    report=setup_flow(project);put(project,'a/private.md','Synthetic denied\n')
    config=project/'wiki-context-controls.yaml';data=yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny']={'read':['a/private.md']};config.write_text(yaml.safe_dump(data));commit(project)
    second=deepcopy(report);second['target']='a/second.md';second['field']=None;second['packet']['output']='a/second.md'
    source=next(r for r in second['packet']['inputs'] if r['kind']=='evidence')
    source['field']=None
    extra=deepcopy(source);extra['path']='a/private.md';second['packet']['inputs'].append(extra)
    request=payload(project,report,candidates=['a/report.md','a/second.md']);request['reports'].append(second)
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path in ('a/report.md','a/second.md','a/source.md','a/private.md'):
            pytest.fail('body opened before all report authority checks')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderCoordinationError):
        prepare_folder_reassessment(project,FolderHostBinding(project,('a',)),request)


def test_cross_owner_source_needs_explicit_bilateral_evidence(project,monkeypatch):
    report=setup_flow(project);request=payload(project,None)
    request['source']='a/aux/b/index.md'
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path!='wiki-context-controls.yaml':pytest.fail('body opened before source authority')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderCoordinationError):
        prepare_folder_reassessment(project,FolderHostBinding(project,('a',)),request)


def test_bilateral_cross_owner_report_and_later_revocation(project,monkeypatch):
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_policy_v2 import load_folder_policy_v2
    source='a/aux/b/source.md';put(project,source,'Synthetic cross-owner source\n')
    config=project/'wiki-context-controls.yaml';data=yaml.safe_load(config.read_text())
    grant={'from_context':'a/aux/b','to_context':'a','selector':source,'use':'interpret',
           'classification':'synthetic','expires':'2099-01-01'}
    data['controls']['a']['imports']=[grant];data['controls']['a/aux/b']['exports']=[grant]
    config.write_text(yaml.safe_dump(data));commit(project);policy=load_folder_policy_v2(project,'HEAD')
    base=build_folder_packet_v2(project,policy,'a',50000,index_path='a/index.md',content_revision='HEAD',
        task_id='cross',goal='review',output='a/report.md',integrator='independent',
        evidence=[{'path':source,'producer_folder':'a/aux/b','reason':'synthetic',
                   'use':'interpret','classification':'synthetic'}])
    observed=[{'path':r['path'],'kind':r['kind'],'revision':r['revision'],'sha256':r['sha256'],
               'section':r.get('section'),'field':r.get('field')} for r in base['inputs']]
    result={'schema_version':'wiki.folder-task-result/v2','status':'completed','task_id':base['task_id'],
            'context_id':base['context_id'],'packet_digest':base['packet_digest'],'observed':observed,
            'changes':[{'path':'a/report.md','action':'created'}]}
    put(project,'a/report.md','---\ninformation_requirements:\n  - target: '+source+
        '\n    fields: ["*"]\n    temporal: current\n    max_age_days: 30\n---\nSynthetic report\n');commit(project)
    report={'target':'a/report.md','section':None,'field':None,'packet':base,'result':result}
    request={'folder':'a','approved_revision':git(project,'rev-parse','HEAD'),'source':source,
             'reports':[report],'candidates':['a/report.md']}
    binding=FolderHostBinding(project,('a',))
    out=prepare_folder_reassessment(project,binding,request)
    assert out['reassessment']['consumers'][0]['state']=='verification_pending'
    data['controls']['a/aux/b']['exports']=[];config.write_text(yaml.safe_dump(data));commit(project)
    request['approved_revision']=git(project,'rev-parse','HEAD')
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path in (source,'a/report.md'):pytest.fail('body opened after bilateral revocation')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderCoordinationError):prepare_folder_reassessment(project,binding,request)


def test_unsupported_source_and_missing_candidate_fail_before_body(project,monkeypatch):
    report=setup_flow(project)
    source=project/'a/source.md';source.unlink();source.symlink_to('report.md');commit(project)
    request=payload(project,None)
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path!='wiki-context-controls.yaml':pytest.fail('body read before metadata selection checks')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderCoordinationError,match='source metadata'):
        prepare_folder_reassessment(project,FolderHostBinding(project,('a',)),request)
    request['source']='a/absent-source.md';request['candidates']=['a/missing.md']
    with pytest.raises(FolderCoordinationError,match='candidate authority'):
        prepare_folder_reassessment(project,FolderHostBinding(project,('a',)),request)
