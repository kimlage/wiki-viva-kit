# Context folder entry template

Use this as an authoring checklist for a context's `AGENTS.md`; keep the actual
instructions in that file, not a copy of this template. Make the paths below
real relative Markdown links in the context. Adapt to the project and avoid
restating applicable ancestor rules. Auxiliary directories do not require an
entry file.

```markdown
# Context purpose

State what belongs here and the context's responsibility.

## Start and find

Read the context index at its actual path. Identify relevant child contexts, canonical
sources, connected repositories and task-specific procedures from that index.
Read required instruction and evidence bodies before relying on them.

## Work and limits

State the local procedures, applicable boundaries and destination for results;
link to canonical procedures rather than copying them. A reference is not a
grant. Identify unavailable inputs and incomplete coverage.

## Review and return

Report the actual reads, revisions, changes and blockers. Follow the target
repository's review and integration policy and read back the authorized result.
```

When a protected v2 packet needs canonical bodies in addition to the AGENTS
chain, declare them as a flat list of real relative Markdown links under the
exact heading `## Wiki v2: mandatory references`. List only whole documents
owned by this context; do not copy their instructions. The packet reads each
body after checking ownership, denials, provenance and byte limits. Ordinary
links elsewhere are not mandatory declarations. Omit the heading when there
are no additional mandatory documents.

For an explicitly selectable index outside the conventional local `index.md`,
declare its real relative link in a flat list under `## Wiki v2: indexes`.
The caller still selects the index or section and must have actual authorization;
the heading and link grant no access. In particular, a project root should
declare its canonical wiki index rather than implicitly substituting a README.

The index organizes knowledge and links; it does not automatically load their
contents. Use the [context hub template](context-hub.md) and
[folder, source and repository guide](../../guides/context-folders-sources-repositories.md).
