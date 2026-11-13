# Synthetic integral context

A person's root, a company context and a child project can use the same four
quadrants while adding a thematic perspective for their own work. All names
below are fictional. Each referenced perspective must exist as a `perspective`
page; the four AQAL IDs are shown in the root configuration.

```yaml
# wiki.config.yaml
root_entity:
  page: memories/index.md
  entity_type: person
  perspective_bundle:
    required: [perspective-identity-intent, perspective-artifacts-evidence,
               perspective-roles-relationships, perspective-systems-processes]
    optional: []
```

```yaml
# memories/index.md
page_id: person-example
page_type: root_entity
root_entity_type: person
```

```yaml
# memories/company/index.md
page_id: company-example
page_type: context_hub
moc_parent: memories/index.md
perspective_bundle_optional: [perspective-financial]
```

```yaml
# memories/company/project/index.md
page_id: project-example
page_type: project
moc_parent: memories/company/index.md
perspective_bundle_required: [perspective-financial]
```

For a source routed to the project, financial is required and the four AQAL
lenses remain required. A source routed only to the company receives financial
as optional. Place the context/project template's markers in each anchor page
and run `wiki_integral_map.py --anchor` for each independently.
