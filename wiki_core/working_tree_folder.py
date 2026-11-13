"""Read a caller-selected working-tree context, without asserting authority."""
from pathlib import Path
import stat

from wiki_core.context_policy import safe_path, within
from wiki_core.detectors import scan_text
from wiki_core.ids import sha256_text


def read_folder_entry(root, folder, index, *, max_bytes):
    """Read the physical AGENTS chain and one explicit index, with no Git fallback."""
    root = Path(root).resolve(strict=True)
    folder = safe_path(folder, allow_root=True)
    index = safe_path(index)
    if not within(index, folder) or type(max_bytes) is not int or max_bytes < 1:
        raise ValueError('invalid working-tree folder selection')
    components = [] if folder == '.' else folder.split('/')

    def checked(parts):
        path = root
        for offset, part in enumerate(parts):
            path = path / part
            try:
                mode = path.lstat().st_mode
            except FileNotFoundError:
                return None
            if stat.S_ISLNK(mode):
                raise ValueError('symlink in working-tree context')
            if offset < len(parts) - 1:
                if not stat.S_ISDIR(mode):
                    raise ValueError('working-tree context is not a directory')
                marker = path / '.git'
                if marker.exists() or marker.is_symlink():
                    raise ValueError('nested repository requires separate selection')
        return path

    refs = []
    directories = ['.'] + ['/'.join(components[:i]) for i in range(1, len(components) + 1)]
    for directory in directories:
        prefix = '' if directory == '.' else directory + '/'
        override_ref, normal_ref = prefix + 'AGENTS.override.md', prefix + 'AGENTS.md'
        override = checked(override_ref.split('/'))
        if override is not None and override.is_file() and override.stat().st_size:
            refs.append(override_ref)
        else:
            normal = checked(normal_ref.split('/'))
            if normal is not None and normal.is_file():
                refs.append(normal_ref)
    prefix = '' if folder == '.' else folder + '/'
    if not any(ref in (prefix + 'AGENTS.md', prefix + 'AGENTS.override.md') for ref in refs):
        raise ValueError('selected folder instructions unavailable')
    selected_index = checked(index.split('/'))
    if selected_index is None or not selected_index.is_file():
        raise ValueError('selected folder index unavailable')
    if index in refs:
        raise ValueError('index must be distinct from instructions')
    refs.append(index)
    documents = []
    remaining = max_bytes
    for ref in dict.fromkeys(refs):
        path = checked(ref.split('/'))
        if path is None or not path.is_file():
            raise ValueError('working-tree context changed')
        with path.open('rb') as stream:
            raw = stream.read(remaining + 1)
        if len(raw) > remaining:
            raise ValueError('working-tree context exceeds byte budget')
        remaining -= len(raw)
        text = raw.decode('utf-8')
        if not text.strip() or any(item.category == 'secret' for item in scan_text(text)):
            raise ValueError('working-tree context unavailable')
        documents.append({'path':ref, 'page_id':None, 'text':text,
                          'content_sha256':sha256_text(text), 'origin':'working_tree'})
    return {'folder':folder, 'index_path':index, 'documents':documents}


def folder_input_context(root, folder, index, *, max_bytes):
    return {'root_entity':None, 'input_channel':None, 'quadrant_map':{}, 'quadrant_semantics':{},
            'quadrant_boundary_rule':'', 'target_pages':[], 'perspectives_required':[],
            'perspectives_optional':[], 'input_stage_status':'working_tree_folder_entry',
            'folder_entry':read_folder_entry(root, folder, index, max_bytes=max_bytes)}


def guard_request_path(path, request):
    """Keep an existing working-tree entry request until coexistence is supported."""
    import json
    path = Path(path)
    selected = (request.get('block_context_package') or {}).get('policy_mode') == 'working_tree_folder_entry'
    if path.is_symlink():
        if selected:
            raise ValueError('working-tree request path unavailable')
        return False
    if not path.exists():
        return selected
    try:
        retained = json.loads(path.read_text(encoding='utf-8'))
        retained_selected = (retained.get('block_context_package') or {}).get('policy_mode') == 'working_tree_folder_entry'
    except (ValueError, AttributeError):
        if selected:
            raise ValueError('existing request must be preserved') from None
        return False
    if not selected and not retained_selected:
        return False
    def keys(value):
        chunks = value.get('chunks')
        if not isinstance(chunks, list) or not chunks:
            raise ValueError('existing request must be preserved')
        keys = [row.get('cache_key') if isinstance(row, dict) else None for row in chunks]
        if any(not isinstance(key, str) or len(key) != 64 for key in keys):
            raise ValueError('existing request must be preserved')
        return keys
    if request.get('source_id') != retained.get('source_id') or keys(request) != keys(retained):
        raise ValueError('a different context request for this source already exists; coexistence is unavailable')
    return True


def retain_request(path, request):
    """Never replace a retained working-tree entry request."""
    from wiki_core.folder_request_identity_v2 import _install_once
    from wiki_core.llm.context_pass import canonical_request_text
    try:
        _install_once(Path(path), canonical_request_text(request))
    except FileExistsError:
        if not guard_request_path(path, request):
            raise ValueError('existing request must be preserved') from None
