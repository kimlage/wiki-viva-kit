# Opt-in modular page templates

A page **type** defines the entity and required metadata through the existing
consumer-owned `wiki.page-types.yaml` registry. A page **template** supplies
an initial document. A content **section** is an addressable Markdown slice with
an explicit stable ID; it is parsed by [content_sections.py](../../../wiki_core/content_sections.py).
Existing template **blocks** can describe facets, UI, perspectives and capabilities;
they are not automatically content slices. A wiki/context/process template can
organize a collection of pages; this small contract only composes one page.
A decision may link to a source as evidence and to an action as follow-up without
becoming those page types. Hubs organize these relationships without duplicating
facts. No template grants context authority, tools, credentials or publication.

## Enable for one type

Use the existing `templates.page_type_overrides` in a consumer's config, or add
`section_contract` to that type's registry shape. An explicit config value wins.
No new registry or global switch is required. This example uses the committed,
public synthetic [decision skeleton](../../../docs/references/templates/wiki/modular-example/decision.md)
and [risk extension](../../../docs/references/templates/wiki/modular-example/decision-risk.yaml):

```yaml
templates:
  page_type_overrides:
    decision:
      template: docs/references/templates/wiki/modular-example/decision.md
      section_contract: docs/references/templates/wiki/modular-example/decision-risk.yaml
```

[templates.py](../../../wiki_core/templates.py) resolves the selected skeleton,
optional legacy overlay, and contract. For this opt-in path the skeleton and
overlay must not already declare section markers. Composition appends the
contract's sections; instantiation supplies normal page metadata plus the chosen
`template_id` and `template_version`. Existing templates, overlays, IDs, metadata
and generated text remain unchanged when `section_contract` is absent. Installed
immutable experience-pack templates reject this opt-in contract rather than
loading an unverified local extension.

## Small additive contract

The [base decision](../../../docs/references/templates/wiki/modular-example/decision.yaml)
uses schema `wiki_template_sections.v1`, a template identity/version, a list of
sections and `allowed_slots`. Every section has `id`, visual `title`, semantic
`role`, and boolean `required`. Roles are `facts`, `decision`, `constraints`,
`evidence`, `uncertainty`, and `next_step`. One role can map to multiple sections.
Slots use `before:<id>` or `after:<id>` and must name a declared section.

The derived risk template declares `extends` as an object with `path` (repository
root relative), `template_id` and `template_version`, pinning its parent's identity
and version. Resolution rejects a parent whose identity/version differs, even if
all section IDs are unchanged. Updating that pin and choosing a child version
require explicit review; neither is automatic. It uses `add_sections` with an
authorized `slot`. It cannot redefine inherited
IDs, roles, titles, requiredness or slots; it cannot remove a required section.
Multiple additions to a slot preserve declaration order. A new title for an
existing page section preserves the selector ID. Changes in meaning require
review, a new template version and explicit consumer migration; the validator
cannot infer semantic equivalence or incompatible meaning.

The [JSON schema](../schemas/wiki-template-sections-v1.schema.json) describes the
file shape. The [runtime loader](../../../wiki_core/template_sections.py) also
checks inheritance and slots. YAML keys must be unique strings. Contracts,
skeletons and overlays must be regular files inside the repository, without
symlinks or traversal. FIFOs, devices and directories are rejected before open. Contracts have an aggregate 64 KiB budget, at most eight files in an
inheritance chain and 64 resolved sections. Skeletons and overlays each have a
64 KiB limit. Cycles, malformed selectors and duplicate IDs fail explicitly.
The loader never executes contract content. These checks do not replace the
host's filesystem sandbox or the reader's authorization policy.

## Structure, filling and selectors

A resolved contract has been checked as a definition, without claiming a page
exists or is filled. `validate_section_page(..., mode='structure')` checks page
template identity/version, required sections, duplicate/malformed selectors,
undeclared IDs and order. Optional sections may be absent. Headings may change
visually without breaking their explicit IDs. The existing marker format requires a `version` attribute; generated markers
use `version=1`. This contract adds no per-section version setting, and does not
compare that marker attribute as a separate migration policy.

`mode='filled'` additionally requires text in every required section, excluding
headings, HTML comments, `{{...}}`, `TODO`, `TBD`, `FIXME` and empty checkboxes.
It only checks lexical presence beyond those known placeholders. It does not
prove factual validity, semantic substance, reader coverage or actual reading.
Drafts pass structure validation while failing filled validation. A required
empty section never passes filled validation merely because its marker exists.

`selectors_for_roles(contract, ['constraints', 'evidence'])` produces stable
`section:<id>` selectors. The existing reader can consume each selector after
its caller applies authorization. Missing/duplicate sections fail rather than
falling back to the whole page. The synthetic
end-to-end test `tests/test_template_sections.py` in the kit source checkout exercises
`resolve_template → instantiate_template → RepositoryReader.read → validation`,
including the risk section and a renamed evidence heading.

```sh
python3 scripts/wiki_template_sections.py --root . --page-type decision
python3 scripts/wiki_template_sections.py --root . --page-type decision \
  --page memories/decisions/example.md --mode structure
python3 scripts/wiki_template_sections.py --root . --page-type decision \
  --page memories/decisions/example.md --mode filled
```

The [CLI](../../../scripts/wiki_template_sections.py) prints JSON and returns
nonzero for invalid definitions/pages. Its page argument is repository relative;
it is a read-only preview of a trusted working tree, not a committed-revision
reader, approval gate or ACL check. Config/registry loading uses the existing
trusted-workspace APIs; callers must establish trust and authorization separately.
Opt-out legacy types are reported as having no section contract.

Template version is distinct from a page's `schema_version` and from Git revision.
Changing a contract never rewrites existing pages. Validation against the newly
selected contract reports an old template version as a mismatch requiring
explicit review/migration. To validate historical pages against their original
contract, explicitly select a preserved version through the same override.
There is no automatic migration, audit-wide activation or rewrite of legacy
page templates in this change.

## Context instructions

The kit's `context_instructions` page type uses the same resolver, overlay,
section composition and versioned validator to draft native folder instructions.
If a project explicitly opts out of the section contract, section validation is
unavailable; its selected template and overlay remain subject to the same
repository and symlink boundaries.
Choose the folder explicitly; the generator accepts the two native instruction
filenames, refuses existing files, symlinks and nested Git repositories, and does
not create or modify an index. For example:

```sh
python3 scripts/wiki_new.py --type context_instructions --title "Context name" \
  --output path/to/context/AGENTS.md
python3 scripts/wiki_template_sections.py --root . --page-type context_instructions \
  --page path/to/context/AGENTS.md --mode filled
```

Fill and review the draft before relying on it. Structure and lexical presence
do not prove meaningful content, authorization, native loading or task coverage.
When native discovery selects an `AGENTS.override.md` in a folder, it replaces
that folder's `AGENTS.md`; it does not combine the two. Keep any necessary local
instructions in the file that will actually be selected.
Folder location defines instruction ancestry; editorial metadata and a hub's
`moc_parent` do not define it. The kit's own development instructions are not
automatically consumer policy. No pages are generated during synchronization.

Each consumer owns its page-type registry. To adopt this type, review and add
the following entry once to that existing registry; the template files are
distributed by kit sync. This config describes a reusable template, not a list
of context folders or an access grant:

```yaml
context_instructions:
  template: docs/references/templates/wiki/context-instructions.md
  section_contract: docs/references/templates/wiki/context-instructions.yaml
  required_frontmatter: [page_type, title, context]
```
