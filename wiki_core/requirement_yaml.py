"""Check requirement-key ambiguity in already authorized Markdown text."""
from __future__ import annotations

import json
import yaml

from wiki_core.frontmatter import FRONTMATTER_RE


class RequirementYamlError(ValueError):
    pass


NO_REPAIR_VALUE = object()


def _canonical_bounded(value) -> str:
    """Bound expanded JSON before retaining it, including shared YAML aliases."""
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'), allow_nan=False)
    chunks = []
    size = 0
    for part in encoder.iterencode(value):
        size += len(part.encode('utf-8'))
        if size > 2_000_000 or len(chunks) >= 100_000:
            raise RequirementYamlError('ambiguous information requirements')
        chunks.append(part)
    return ''.join(chunks)


def check_requirement_yaml(text: str, *, repair_value=NO_REPAIR_VALUE) -> None:
    """Refuse ambiguous requirement mappings; do not grant or read anything.

    A bounded event pass precedes composition. Aliases outside the protected
    subtree are not inspected, except where a top-level merge can supply the
    protected key. The caller must already have authorized the text.
    """
    match = FRONTMATTER_RE.match(text)
    if match is None:
        return
    raw = match.group(1)
    if len(raw.encode('utf-8')) > 2_000_000:
        raise RequirementYamlError('requirement frontmatter unavailable')
    try:
        depth = events = 0
        has_alias = False
        for event in yaml.parse(raw, Loader=yaml.SafeLoader):
            events += 1
            if events > 100_000:
                raise RequirementYamlError('requirement frontmatter unavailable')
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
                if depth > 128:
                    raise RequirementYamlError('requirement frontmatter unavailable')
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            elif isinstance(event, yaml.AliasEvent):
                has_alias = True
        root = yaml.compose(raw, Loader=yaml.SafeLoader)
    except (yaml.YAMLError, RecursionError, UnicodeError, ValueError) as exc:
        raise RequirementYamlError('requirement frontmatter unavailable') from None
    if root is None:
        return
    if not isinstance(root, yaml.MappingNode):
        return  # Existing parser does not treat non-mapping frontmatter as requirements.

    steps = 0
    def consume():
        nonlocal steps
        steps += 1
        if steps > 100_000:
            raise RequirementYamlError('requirement frontmatter unavailable')

    def pairs(node, active, *, protected_only=False):
        """Flatten merge precedence like SafeLoader, retaining direct-key checks."""
        consume()
        if not isinstance(node, yaml.MappingNode) or id(node) in active or len(active) >= 128:
            raise RequirementYamlError('ambiguous information requirements')
        active.add(id(node))
        try:
            merged, direct = [], []
            seen = set()
            saw_merge = False
            for key, value in node.value:
                consume()
                if key.tag == 'tag:yaml.org,2002:merge':
                    if saw_merge:
                        raise RequirementYamlError('ambiguous information requirements')
                    saw_merge = True
                    sources = value.value if isinstance(value, yaml.SequenceNode) else [value]
                    # SafeLoader prepends merge sources in reverse sequence order;
                    # local keys are appended afterward and therefore win.
                    for source in reversed(sources) if isinstance(value, yaml.SequenceNode) else sources:
                        merged.extend(pairs(source, active, protected_only=protected_only))
                else:
                    if not isinstance(key, yaml.ScalarNode):
                        raise RequirementYamlError('ambiguous information requirements')
                    selected = not protected_only or (key.tag == 'tag:yaml.org,2002:str'
                                                       and key.value == 'information_requirements')
                    if selected:
                        if key.tag != 'tag:yaml.org,2002:str' or key.value in seen:
                            raise RequirementYamlError('ambiguous information requirements')
                        seen.add(key.value)
                    direct.append((key, value))
            return merged + direct
        finally:
            active.remove(id(node))

    direct_protected = [value for key, value in root.value
                        if isinstance(key, yaml.ScalarNode) and key.tag == 'tag:yaml.org,2002:str'
                        and key.value == 'information_requirements']

    visited = set()
    def visit(node, active, *, no_merge=False):
        consume()
        if id(node) in active or len(active) >= 128:
            raise RequirementYamlError('ambiguous information requirements')
        cache_key = (id(node), no_merge)
        if cache_key in visited:
            return
        if isinstance(node, yaml.ScalarNode):
            visited.add(cache_key)
            return
        active.add(id(node))
        try:
            if isinstance(node, yaml.SequenceNode):
                for item in node.value:
                    visit(item, active, no_merge=no_merge)
            elif isinstance(node, yaml.MappingNode):
                if no_merge and any(key.tag == 'tag:yaml.org,2002:merge' for key, _ in node.value):
                    raise RequirementYamlError('ambiguous information requirements')
                for key, value in pairs(node, set()):
                    if key.tag != 'tag:yaml.org,2002:str':
                        raise RequirementYamlError('ambiguous information requirements')
                    visit(value, active, no_merge=no_merge)
        finally:
            active.remove(id(node))
        visited.add(cache_key)

    if len(direct_protected) > 1:
        # Only a narrowly proved repair is admitted: no aliases/merges in the
        # base and every independently decoded list exactly equals the single
        # unambiguous list in the proposal, with JSON scalar types preserved.
        if (repair_value is NO_REPAIR_VALUE or not isinstance(repair_value, list) or has_alias
                or any(key.tag == 'tag:yaml.org,2002:merge' for key, _ in root.value)):
            raise RequirementYamlError('ambiguous information requirements')
        try:
            expected = _canonical_bounded(repair_value)
            for node in direct_protected:
                if not isinstance(node, yaml.SequenceNode):
                    raise RequirementYamlError('ambiguous information requirements')
                visit(node, set(), no_merge=True)
                if _canonical_bounded(yaml.safe_load(yaml.serialize(node, Dumper=yaml.SafeDumper))) != expected:
                    raise RequirementYamlError('ambiguous information requirements')
        except RequirementYamlError:
            raise
        except (yaml.YAMLError, RecursionError, TypeError, ValueError):
            raise RequirementYamlError('ambiguous information requirements') from None
        return
    protected = [value for key, value in pairs(root, set(), protected_only=True)
                 if key.tag == 'tag:yaml.org,2002:str' and key.value == 'information_requirements']
    # Merge overrides are deterministic in SafeLoader. Inspect every protected
    # origin for direct duplicates while leaving its existing winner unchanged.
    for node in protected:
        visit(node, set())
