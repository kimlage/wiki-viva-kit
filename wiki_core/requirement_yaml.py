"""Check requirement-key ambiguity in already authorized Markdown text."""
from __future__ import annotations

import json
import yaml

from wiki_core.frontmatter import FRONTMATTER_RE


class RequirementYamlError(ValueError):
    pass


NO_REPAIR_VALUE = object()


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

    def pairs(node, active):
        consume()
        if not isinstance(node, yaml.MappingNode) or id(node) in active or len(active) >= 128:
            raise RequirementYamlError('ambiguous information requirements')
        active.add(id(node))
        try:
            for key, value in node.value:
                consume()
                if key.tag == 'tag:yaml.org,2002:merge':
                    sources = value.value if isinstance(value, yaml.SequenceNode) else [value]
                    for source in sources:
                        yield from pairs(source, active)
                else:
                    if not isinstance(key, yaml.ScalarNode):
                        raise RequirementYamlError('ambiguous information requirements')
                    yield key, value
        finally:
            active.remove(id(node))

    protected = [value for key, value in pairs(root, set())
                 if key.tag == 'tag:yaml.org,2002:str' and key.value == 'information_requirements']
    if not protected:
        return

    def visit(node, active, *, no_merge=False):
        consume()
        if id(node) in active or len(active) >= 128:
            raise RequirementYamlError('ambiguous information requirements')
        if isinstance(node, yaml.ScalarNode):
            return
        active.add(id(node))
        try:
            if isinstance(node, yaml.SequenceNode):
                for item in node.value:
                    visit(item, active, no_merge=no_merge)
            elif isinstance(node, yaml.MappingNode):
                if no_merge and any(key.tag == 'tag:yaml.org,2002:merge' for key, _ in node.value):
                    raise RequirementYamlError('ambiguous information requirements')
                keys = set()
                for key, value in pairs(node, set()):
                    if key.tag != 'tag:yaml.org,2002:str' or key.value in keys:
                        raise RequirementYamlError('ambiguous information requirements')
                    keys.add(key.value)
                    visit(value, active, no_merge=no_merge)
        finally:
            active.remove(id(node))

    if len(protected) > 1:
        # Only a narrowly proved repair is admitted: no aliases/merges in the
        # base and every independently decoded list exactly equals the single
        # unambiguous list in the proposal, with JSON scalar types preserved.
        if (repair_value is NO_REPAIR_VALUE or not isinstance(repair_value, list) or has_alias
                or any(key.tag == 'tag:yaml.org,2002:merge' for key, _ in root.value)):
            raise RequirementYamlError('ambiguous information requirements')
        try:
            canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True,
                                                 separators=(',', ':'), allow_nan=False)
            expected = canonical(repair_value)
            for node in protected:
                if not isinstance(node, yaml.SequenceNode):
                    raise RequirementYamlError('ambiguous information requirements')
                visit(node, set(), no_merge=True)
                if canonical(yaml.safe_load(yaml.serialize(node, Dumper=yaml.SafeDumper))) != expected:
                    raise RequirementYamlError('ambiguous information requirements')
        except (yaml.YAMLError, RecursionError, TypeError, ValueError):
            raise RequirementYamlError('ambiguous information requirements') from None
        return
    visit(protected[0], set())
