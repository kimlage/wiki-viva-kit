# Context folders, sources and connected repositories

A context is a place to enter and work: its folder has an `AGENTS.md` and an
index. The instructions state its purpose, where to look, procedures and
limits; the index maps its knowledge, relevant sources, connected repositories
and child contexts. Auxiliary folders need not repeat these files. The project
chooses its own tree and policy; a child adds its particularities within the
applicable ancestor rules. Do not keep a second manually maintained hierarchy
or copy the same instruction into multiple files.

The [context entry template](../templates/wiki/context-entry.md) is an authoring
aid, not a registry. Context instructions direct the agent to canonical
procedures and knowledge; links do not load their bodies. Read the index and
the bodies required for the task, reporting omissions and insufficient coverage.
An instruction file, a folder, or an index is not an access control boundary.

## From entry to integration

1. Select the authorized context and start the agent session at its folder.
   Verify the harness's actual discovery root, applicable ancestors, overrides,
   instruction budget and effective permissions. A link or moving the working
   directory of a command in an existing session does not prove native loading.
2. Read the context index and task-relevant procedures, then select authorized
   sources and repositories. Identify missing, unavailable or denied inputs;
   do not infer global absence or freshness from a partial search.
3. Record the actual reads, source and revision or observation, selection,
   provenance, scope and limitations. Execute only the authorized task, using
   the tools and permissions actually available.
4. Make a reviewable proposal in the correct repository. An independent
   reviewer and integrator follow that repository's policy and gates for the
   final revision. After authorized integration, read back the destination and
   assess affected consumers using the existing [impact procedure](context-impact-integration.md).

The [finite operation runbook](context-operation.md) describes the currently
implemented protected packet and preflight path. Where that path still requires
approved structured policy, keep and enforce it until the consumer is migrated
and reviewed. Native instructions alone do not replace its checks. A packet
proves neither native instruction discovery nor a semantic read or integration.

### Tool-specific discovery

Codex constructs its instruction chain at session start from its discovery
root to the starting directory, with override and size rules described in the
[official instructions guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
A nested Git root can change that chain; verify the actual session and target
repository separately.

Claude Code's [instruction documentation](https://code.claude.com/docs/en/memory#agentsmd)
describes different discovery rules: by default a project CLAUDE file on the
ancestor path can prevent direct AGENTS loading. Where that applies, a CLAUDE
file beside each relevant context instruction can import its canonical text:

```text
@AGENTS.md
```

An ordinary Markdown link or an instruction to read a file does not perform
that import. An import outside the session working directory can require a
first-time trust decision; a nested session must not assume that imports from
ancestor folders were accepted. Settings, other ancestor files and overrides
still affect a real session; inspect the installed configuration and verify actual loading. Do
not change a user's global settings by assumption or treat this documented
bridge as proof of an operational Claude run.

### Auxiliary instruction folders

An instruction folder without its own context index remains an unresolved
ownership boundary by default. Where the approved project policy already
permits the selected context to read the local instruction and to read/write
the requested output, its `AGENTS.md` can explicitly say that the folder is
auxiliary, without creating another context or owner:

```markdown
## Wiki v2: auxiliary

This folder adds instructions; ownership stays with the nearest context.
```

The experimental [folder packet](../../../scripts/wiki_folder_packet_v2.py)
accepts `--start-folder` for that physical entry, with the existing ancestor
context as its positional `folder` and an authorized context `--index`.
The approved Git revision must contain the exact declaration. Missing,
malformed, denied or unapproved instructions fail closed; the declared
auxiliary body is included in the packet's physical instruction chain. The
existing read/write ceilings and denials still apply. An auxiliary declaration
does not grant access, establish a new owner, prove sandboxing or demonstrate
that a native agent session actually loaded those instructions.

## Sources: identity, use and revision

Use the existing [source page](../templates/wiki/source.md) for the canonical
identity and location, responsibility and evidence; use its linked
[source configuration](../templates/wiki/source-config.md) for the recipe and
mechanically consumed selection/access settings. Do not create another catalog
for the same facts. Record purpose and relevant slice, conditions of access,
the authorized way to consult or obtain it, and the actual revision or dated
observation consumed. A reference, recipe or authentication pointer grants no
access, credentials, transmission, synchronization or publication.

The source, local cache, derived index and each context's interpretation have
distinct roles. Use [bounded ingestion](bounded-ingestion.md) when ingestion is
needed; a lookup is not automatically ingestion. Preserve the original and
provenance. A wiki edit does not renew source verification. Unavailable sources,
access refusals and incomplete coverage remain visible in the result.

An authorized source may support different interpretations in different
contexts. Record the selected source and revision each interpretation actually
consumed in the existing relationship/requirement where supported. After a
pertinent change, evaluate eligible consumers selectively; each owner decides
whether its own interpretation changes, remains valid, is superseded or is
blocked. Do not copy a conclusion or infer a cross-context grant from a link.
See [information impact](information-impact.md) for freshness and the limits of
the derived inventory.

## Independent Git repositories

A wiki context can link one or more repositories. Its versioned index keeps
the canonical repository identity/location, purpose, relevant paths and
revision-bearing references useful even when no clone is present. Each linked
repository owns its code, local instructions, Git history, branches, review and
publication. It remains usable without this wiki. Before Git operations,
verify the actual target root and remote; the instruction-discovery root can
be different from the Git root being changed.

For an independent clone inside the context, the parent wiki can ignore the
clone path while keeping its own `AGENTS.md` and index tracked. A local-only
exclusion can use the parent Git's `info/exclude`. Ignore does not untrack files
already tracked. A submodule instead records a commit in the parent and is
appropriate only when that fixed composition is needed.

Versioning, indexing and instruction discovery are separate. An ignored clone
must not be assumed excluded from filesystem walkers merely because Git ignores
it. Check the actual search, audit, ingestion and export paths before claiming
that general indexing excludes the clone. Search the wiki node normally; query
the selected repository explicitly, recording repository, revision and path.
The revision-bound wiki reader reads its own Git tree and does not automatically
read an ignored independent clone. For one selected path, the explicit
[repository reader](../../../scripts/wiki_repo_read.py) verifies the local Git
root and configured origin identity and returns its revision and path. The
configured origin is not proof of remote authentication or access. Check the
selected reader's exact scope and do not present its output as complete coverage
of another repository.

The wiki's adapted FTS readers verify the current page collection against the
index and refuse stale or unverified page entries; rebuild the page index when
requested. An explicitly selected non-page source can still be searched, with
page-index coverage reported as unchecked. Verification scans the page corpus
and indexed page rows, so its cost grows with the wiki. Raw low-level SQLite
search without this validation is not a protected wiki search.

Revision-bound authority readers use Git's `--no-lazy-fetch` option and fail
closed if the installed Git cannot run it. Git 2.50.1 was tested locally;
other versions and platforms require their own validation. The kit sync uses
descriptor-relative no-follow operations and refuses platforms without those
primitives. B0 and C1 refuse managed paths inside a nested `.git` directory or
worktree marker; cooperative custody remains required during the operation.
Native Windows sync and bounded pre-allocation for large Git tree
listings on Windows have not been qualified.

A nested `.git` can change where a harness starts discovering instructions.
Qualify the chosen entry in the actual harness, including wiki ancestors and
repo-local instructions, configured root markers, overrides and effective
permissions. Starting above a clone does not by itself load descendant
instructions. Never change global configuration by assumption, and never claim
that a marker or a documented behavior proves a real session received both
chains. If that session cannot be demonstrated, report the concrete limit.
