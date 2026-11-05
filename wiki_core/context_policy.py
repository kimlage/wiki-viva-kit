"""Revision-bound, narrow context policy; Git and YAML do not enforce a sandbox.

Each context is declared once in a context.yaml at its root. Scope values are
literal repository-relative paths (or self[/...]); no glob semantics. The
configured trusted ref must be maintained by an independent approval process.
"""
from __future__ import annotations
import datetime as dt
import re
import subprocess
from pathlib import Path, PurePosixPath
import yaml
from wiki_core.git_env import local_git_environment, local_git_executable, local_git_tree
from wiki_core.git_safety import GitSafetyError

class PolicyError(ValueError): pass

class UniqueLoader(yaml.SafeLoader): pass

def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result: raise PolicyError('duplicate or invalid YAML key')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)

def safe_path(value, *, allow_root=False):
    if allow_root and value == '.': return value
    if not isinstance(value, str) or not value or '\\' in value or value.startswith('/') or any(ord(c) < 32 or ord(c) == 127 for c in value): raise PolicyError('invalid relative path')
    if any(x in ('', '.', '..') for x in value.split('/')) or any(c in value for c in '*?[]'): raise PolicyError('invalid relative path')
    return str(PurePosixPath(value))

def within(path, scope): return scope == '.' or path == scope or path.startswith(scope + '/')

def is_context_instruction(path):
    """A potential native instruction boundary, whether added, removed or edited.

    Recognition is deliberately conservative; it does not turn folder
    instructions into v1 authority or prove native instruction loading.
    """
    return isinstance(path, str) and path.rsplit('/', 1)[-1] in ('AGENTS.md', 'AGENTS.override.md')

def _git(root, *args):
    if 'ls-tree' in args and '-r' in args:
        try:
            return local_git_tree(Path(root), *args)
        except GitSafetyError as exc:
            raise PolicyError('Git tree enumeration unavailable or exceeded limit') from exc
    p = subprocess.run([local_git_executable(), '--no-lazy-fetch','-C',str(root),*args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=local_git_environment())
    if p.returncode: raise PolicyError('Git revision or path unavailable')
    return p.stdout

def revision(root, ref):
    if not isinstance(ref,str) or not ref or ref.startswith('-'): raise PolicyError('invalid revision')
    sha = _git(root,'rev-parse','--verify',ref+'^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40,64}',sha): raise PolicyError('invalid commit')
    return sha

def git_file(root, rev, path):
    path=safe_path(path)
    for i in range(1,len(path.split('/'))+1):
        prefix='/'.join(path.split('/')[:i]); entry=_git(root,'ls-tree',rev,'--',prefix).decode().strip()
        if not entry or entry.startswith(('120000 ','160000 ')): raise PolicyError('missing or unsafe Git path')
    try:
        size = int(_git(root, 'cat-file', '-s', f'{rev}:{path}'))
    except ValueError as exc:
        raise PolicyError('Git object size unavailable') from exc
    if size < 0 or size > 2_000_000:
        raise PolicyError('Git object exceeds size limit')
    return _git(root,'show',f'{rev}:{path}')

def _list(v, name):
    if not isinstance(v,list) or any(not isinstance(x,str) or not x for x in v) or len(v)!=len(set(v)): raise PolicyError('invalid '+name)
    return v

def _scope(v, root):
    if v=='self': return root
    if v.startswith('self/'): return safe_path((root+'/' if root!='.' else '')+v[5:])
    return safe_path(v,allow_root=True)

def _keys(obj, allowed, required, label):
    if not isinstance(obj,dict) or set(obj)-set(allowed) or set(required)-set(obj): raise PolicyError('invalid '+label+' fields')

class ContextPolicy:
    def __init__(self, document, policy_revision, *, folder_ids=False):
        _keys(document,{'schema_version','contexts'},{'schema_version','contexts'},'document')
        if document['schema_version']!='wiki.context/v1' or not isinstance(document['contexts'],list): raise PolicyError('invalid context document')
        self.policy_revision=policy_revision; self.contexts={}; self.effective={}; self._binding=None
        for c in document['contexts']:
            _keys(c,{'id','parent','root','purpose','owner','instructions','skills','templates','policy','imports','exports','workflow','defaults'}, {'id','parent','root','purpose','owner','instructions','skills','templates','policy','imports','exports'},'context')
            if folder_ids:
                safe_path(c['id'], allow_root=True)
                if c['id'] != c['root']: raise PolicyError('folder context identity differs from path')
            elif not isinstance(c['id'],str) or not re.fullmatch(r'[a-z0-9][a-z0-9/_-]*',c['id']):
                raise PolicyError('invalid or duplicate context id')
            if c['id'] in self.contexts: raise PolicyError('invalid or duplicate context id')
            if not all(isinstance(c[k],str) and c[k].strip() for k in ('purpose','owner')): raise PolicyError('purpose and owner required')
            safe_path(c['root'],allow_root=True)
            for k in ('instructions','skills','templates'):
                for p in _list(c[k],k): safe_path(p)
            _keys(c['policy'],{'read','write','capabilities','deny','publication'},set(),'policy')
            for k,v in c['policy'].items():
                if k=='deny':
                    _keys(v,{'read','write','capabilities','publication'},set(),'deny')
                    for name,values in v.items(): _list(values,'deny '+name)
                else: _list(v,k)
            for k in ('workflow','defaults'):
                if k in c and not isinstance(c[k],dict): raise PolicyError('invalid '+k)
            for k in ('imports','exports'):
                if not isinstance(c[k],list): raise PolicyError('invalid connections')
                for r in c[k]:
                    _keys(r,{'from_context','to_context','selector','section','field','use','classification','expires'}, {'from_context','to_context','selector','use','classification','expires'},'connection')
                    if any(not isinstance(v,str) or not v.strip() for v in r.values()) or ('section' in r and 'field' in r): raise PolicyError('invalid connection')
                    safe_path(r['selector'])
                    try: dt.date.fromisoformat(r['expires'])
                    except ValueError as exc: raise PolicyError('invalid connection expiry') from exc
            self.contexts[c['id']]=c
        roots=[c for c in self.contexts.values() if c['parent'] is None]
        if len(roots)!=1: raise PolicyError('exactly one root required')
        paths=[c['root'] for c in self.contexts.values()]
        if len(paths)!=len(set(paths)): raise PolicyError('duplicate context roots')
        for cid in self.contexts: self._resolve(cid,set())
        for c in self.contexts.values():
            for key in ('instructions','skills','templates'):
                for ref in c[key]:
                    if self.owner_of(ref) != c['id']: raise PolicyError('mandatory reference belongs to another context')
            if c['parent'] is not None:
                parent=self.contexts[c['parent']]
                if c['root']==parent['root'] or not within(c['root'],parent['root']): raise PolicyError('invalid physical parent')
                containing=[x for x in self.contexts.values() if x['id']!=c['id'] and within(c['root'],x['root'])]
                nearest=max(containing,key=lambda x: len(x['root']) if x['root']!='.' else 0)
                if nearest['id']!=c['parent']: raise PolicyError('parent is not nearest context root')
            for name in ('imports','exports'):
                for rule in c[name]:
                    if rule['from_context'] not in self.contexts or rule['to_context'] not in self.contexts: raise PolicyError('unknown connection context')
                    if rule['to_context' if name=='imports' else 'from_context']!=c['id']: raise PolicyError('invalid connection owner')

    def _resolve(self,cid,visiting):
        if cid in self.effective: return self.effective[cid]
        if cid in visiting or cid not in self.contexts: raise PolicyError('missing or cyclic parent')
        c=self.contexts[cid]; parent=c['parent']; visiting=visiting|{cid}
        if parent is not None and (not isinstance(parent,str) or parent not in self.contexts): raise PolicyError('missing parent')
        base=self._resolve(parent,visiting) if parent is not None else None
        if base is None and set(c['policy']) != {'read','write','capabilities','deny','publication'}: raise PolicyError('root must declare all boundaries')
        result={}
        for key in ('read','write','capabilities','publication'):
            raw=c['policy'].get(key)
            if raw is None: result[key]=list(base[key]); continue
            vals=[_scope(v,c['root']) for v in raw] if key in ('read','write') else list(raw)
            if base:
                for v in vals:
                    if not any(within(v,p) if key in ('read','write') else v==p for p in base[key]): raise PolicyError('child widens '+key)
            result[key]=vals
        result['deny']={}
        for key in ('read','write','capabilities','publication'):
            raw=c['policy'].get('deny',{}).get(key,[])
            result['deny'][key]=(list(base['deny'][key]) if base else [])+([_scope(v,c['root']) for v in raw] if key in ('read','write') else list(raw))
        self.effective[cid]=result; return result

    def lineage(self,cid):
        if cid not in self.contexts: raise PolicyError('unknown context')
        out=[]
        while cid is not None:
            c=self.contexts[cid]; out.append(c); cid=c['parent']
        return list(reversed(out))

    def owner_of(self,path):
        path=safe_path(path)
        matches=[c for c in self.contexts.values() if within(path,c['root'])]
        if not matches: raise PolicyError('path has no context owner')
        return max(matches,key=lambda c:len(c['root']) if c['root']!='.' else 0)['id']

    def permits(self,cid,action,path):
        if getattr(self, 'format_version', None) == 'folder' and cid not in self._qualified_contexts:
            return False
        return self._permits_unqualified(cid, action, path)

    def _permits_unqualified(self,cid,action,path):
        path=safe_path(path)
        if action not in ('read','write'): raise PolicyError('invalid action')
        p=self.effective[cid]
        return any(within(path,x) for x in p[action]) and not any(within(path,x) for x in p['deny'][action])

    def permits_effect(self, cid, category, effect):
        if category not in ('capabilities','publication') or not isinstance(effect, str) or not effect:
            raise PolicyError('invalid effect')
        if getattr(self, 'format_version', None) == 'folder' and cid not in self._qualified_contexts:
            return False
        p = self.effective[cid]
        return effect in p[category] and effect not in p['deny'][category]

    def connection(self,producer,consumer,selector,use,classification,today=None,section=None,field=None):
        return self._connection(producer,consumer,selector,use,classification,today,section,field,qualified=True)

    def _connection(self,producer,consumer,selector,use,classification,today=None,section=None,field=None,*,qualified):
        safe_path(selector)
        if section is not None and field is not None: raise PolicyError('section and field mutually exclusive')
        if producer not in self.contexts or consumer not in self.contexts: raise PolicyError('unknown context')
        if self.owner_of(selector)!=producer: return 'denied'
        check = self.permits if qualified else self._permits_unqualified
        if not check(producer,'read',selector) or not check(consumer,'read',selector): return 'denied'
        if producer==consumer: return 'approved'
        today=today or dt.date.today()
        def matches(r): return r['from_context']==producer and r['to_context']==consumer and r['selector']==selector and r['use']==use and r['classification']==classification and r.get('section')==section and r.get('field')==field and dt.date.fromisoformat(r['expires'])>=today
        return 'approved' if any(a==b for a in self.contexts[producer]['exports'] if matches(a) for b in self.contexts[consumer]['imports'] if matches(b)) else 'pending'

    def fresh(self):
        if not self._binding: raise PolicyError('unbound policy is not authority')
        root, trusted_ref, root_manifest = self._binding
        fresh=load_policy(root,self.policy_revision,root_manifest,trusted_ref=trusted_ref)
        return fresh

def load_policy(root, approved_revision, manifest_path='context.yaml', *, trusted_ref='refs/remotes/origin/main'):
    root=Path(root).resolve(); manifest_path=safe_path(manifest_path)
    sha=revision(root,approved_revision)
    if sha!=revision(root,trusted_ref): raise PolicyError('policy revision is not current trusted approval ref')
    policy = (_folder_policy_at(root, sha) if manifest_path == 'wiki.config.yaml'
              else _policy_at(root, sha, manifest_path))
    policy._binding=(str(root),trusted_ref,manifest_path)
    return policy


def _folder_policy_at(root, sha):
    """Build context ownership from approved Git paths and explicit access data.

    The existing wiki configuration may contain sparse ``context_access``
    entries keyed by physical folder. These entries contain access rules only;
    they do not define folders, ancestry or instruction files. Missing entries
    grant nothing. This is a policy model, not a sandbox or a native-session
    discovery claim.
    """
    try:
        config = yaml.load(git_file(root, sha, 'wiki.config.yaml'), Loader=UniqueLoader)
    except (yaml.YAMLError, UnicodeError) as exc:
        raise PolicyError('invalid wiki configuration') from exc
    if not isinstance(config, dict): raise PolicyError('invalid wiki configuration')
    access = config.get('context_access', {})
    if not isinstance(access, dict): raise PolicyError('invalid context access')

    raw = _git(root, 'ls-tree', '-r', '-z', sha)
    names = set()
    for entry in raw.split(b'\0'):
        if not entry: continue
        try:
            metadata, name = entry.split(b'\t', 1)
            mode, kind, _oid = metadata.split(b' ', 2)
            path = name.decode('utf-8')
        except (ValueError, UnicodeError) as exc:
            raise PolicyError('invalid Git tree entry') from exc
        if PurePosixPath(path).name not in ('AGENTS.md', 'AGENTS.override.md', 'index.md'):
            continue
        safe_path(path)
        if mode not in (b'100644', b'100755') or kind != b'blob':
            raise PolicyError('unsafe context tree entry')
        names.add(path)

    def selected_instruction(folder):
        prefix = '' if folder == '.' else folder + '/'
        return next((prefix + n for n in ('AGENTS.override.md', 'AGENTS.md')
                     if prefix + n in names), None)

    if selected_instruction('.') is None: raise PolicyError('root instructions unavailable')
    folders = {'.'}
    for path in names:
        if PurePosixPath(path).name != 'index.md': continue
        folder = str(PurePosixPath(path).parent)
        if folder != '.' and selected_instruction(folder): folders.add(folder)
    for folder in access:
        safe_path(folder, allow_root=True)
        if folder not in folders: raise PolicyError('access entry has no context folder')

    contexts = []
    for folder in sorted(folders, key=lambda value: (value.count('/'), value)):
        spec = access.get(folder, {})
        _keys(spec, {'owner', 'policy', 'imports', 'exports'}, set(), 'context access')
        owner = spec.get('owner', 'unassigned')
        policy = spec.get('policy', {})
        _keys(policy, {'read', 'write', 'capabilities', 'deny', 'publication'}, set(), 'policy')
        # Missing values are empty, not inherited grants. Denies continue to
        # accumulate through ContextPolicy._resolve.
        policy = {key: policy.get(key, {} if key == 'deny' else [])
                  for key in ('read', 'write', 'capabilities', 'deny', 'publication')}
        if owner == 'unassigned' and any(policy[key] for key in ('read', 'write', 'capabilities', 'publication')):
            raise PolicyError('explicit owner required for access')
        ancestors = [candidate for candidate in folders if candidate != folder and within(folder, candidate)]
        parent = max(ancestors, key=lambda value: len(value) if value != '.' else 0) if ancestors else None
        contexts.append({'id': folder, 'parent': parent, 'root': folder,
            'purpose': 'See the context instructions.', 'owner': owner,
            'instructions': [selected_instruction(folder)], 'skills': [], 'templates': [],
            'policy': policy, 'imports': spec.get('imports', []), 'exports': spec.get('exports', [])})
    result = ContextPolicy({'schema_version': 'wiki.context/v1', 'contexts': contexts}, sha, folder_ids=True)
    # Existing packet/integration paths must not silently reinterpret v1.
    # A caller must use the folder-aware versioned interfaces when available.
    result.format_version = 'folder'
    result._folder_names = frozenset(names)
    # Metadata alone is not a qualified context. Callers must authorize and
    # inspect the selected instruction/index bodies before receiving grants.
    result._qualified_contexts = set()
    return result


def _policy_at(root, sha, manifest_path):
    """Parse policy bytes only; the returned object deliberately has no authority binding."""
    if PurePosixPath(manifest_path).name!='context.yaml': raise PolicyError('root manifest must be context.yaml')
    base=str(PurePosixPath(manifest_path).parent)
    entries=_git(root,'ls-tree','-r','-z','--name-only',sha).split(b'\0')
    paths=[]
    for raw in entries:
        if not raw or not (raw==b'context.yaml' or raw.endswith(b'/context.yaml')): continue
        try: p=raw.decode('utf-8')
        except UnicodeDecodeError as exc: raise PolicyError('invalid Git path') from exc
        if (p=='context.yaml' or p.endswith('/context.yaml')) and within(p,base): paths.append(p)
    if manifest_path not in paths: raise PolicyError('root manifest missing')
    contexts=[]
    for p in sorted(paths):
        try: c=yaml.load(git_file(root,sha,p),Loader=UniqueLoader)
        except (yaml.YAMLError, UnicodeError) as exc: raise PolicyError('invalid manifest YAML') from exc
        if not isinstance(c,dict): raise PolicyError('invalid context manifest')
        if c.get('schema_version')!='wiki.context/v1': raise PolicyError('invalid schema version')
        c=dict(c); del c['schema_version']
        if c.get('root')!=str(PurePosixPath(p).parent): raise PolicyError('manifest root does not match directory')
        contexts.append(c)
    policy=ContextPolicy({'schema_version':'wiki.context/v1','contexts':contexts},sha)
    if policy.contexts[next(c['id'] for c in contexts if c['parent'] is None)]['root']!=base: raise PolicyError('root manifest is not hierarchy root')
    return policy


def historical_policy(current, fixed_revision, *, authority_format='v1', historical_manifest=None):
    """Reconstruct a recorded policy format, never permission to read.

    Historical v1 receipts have no format field and remain v1. New folder
    receipts must select ``folder`` explicitly; file coexistence is not proof
    of which format produced a receipt.
    """
    if getattr(current, 'format_version', None) not in (None, 'folder'):
        raise PolicyError('v2 historical replay is not supported; v1 receipts require explicit migration')
    current = current.fresh()
    if not isinstance(fixed_revision,str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',fixed_revision):
        raise PolicyError('query authority revision unavailable')
    root, _, manifest = current._binding
    _git(root, 'merge-base', '--is-ancestor', fixed_revision, current.policy_revision)
    if getattr(current, 'format_version', None) == 'folder':
        if authority_format == 'v1':
            if historical_manifest is None: raise PolicyError('historical v1 manifest must be selected explicitly')
            return _policy_at(root, fixed_revision, safe_path(historical_manifest))
        if authority_format == 'folder': return _folder_policy_at(root, fixed_revision)
        raise PolicyError('unknown historical authority format')
    if authority_format != 'v1': raise PolicyError('historical authority format unavailable')
    return _policy_at(root, fixed_revision, manifest)

def valid_adapter_report(report):
    if not isinstance(report, dict) or set(report) != {'verification', 'capabilities', 'scope', 'limitation'}: return False
    caps, scopes, limitation = report['capabilities'], report['scope'], report['limitation']
    return (report['verification'] == 'verified' and isinstance(caps, list) and bool(caps)
            and all(isinstance(x, str) and x.strip() for x in caps)
            and isinstance(scopes, list) and bool(scopes)
            and all(isinstance(x, str) and x.strip() and not any(c in x for c in '*?[]') for x in scopes)
            and isinstance(limitation, str) and bool(limitation.strip()))

def capability_status(policy, cid, capability, adapter_report, *, target=None):
    if not policy.permits_effect(cid, 'capabilities', capability): return 'denied'
    if not valid_adapter_report(adapter_report) or not isinstance(target, str) or not target.strip(): return 'pending'
    return 'available' if capability in adapter_report['capabilities'] and target in adapter_report['scope'] else 'pending'
