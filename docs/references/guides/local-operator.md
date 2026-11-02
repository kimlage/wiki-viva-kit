# Optional local operator

The wiki's Git reader, context packages and finite ingestion commands work
without a web server, frontend, scheduler or external agent process. Start the
[local operator](../../../scripts/wiki_web_server.py) only when an HTTP client
needs it. The [board](native-action-board.md) projects canonical Markdown actions;
its presence does not prove that an executor or schedule is running.

## Read and effect boundaries

Page, source, coordination and version observations are read routes. The
operator observation reports separate code-at-boot, current code, content commit
and served frontend bytes; an unknown frontend source commit stays unknown.
This read does not reconcile jobs, contact an external agent or rebuild a global
snapshot.

Action writers, briefs, job submission, gates, snapshot publication and source
copy/apply/refresh operations require a current
administrative session and the capabilities for that effect. The same checks
apply on execution after a plan was reviewed. Origin checks, expected revisions,
attempt keys, locks and atomic writers remain necessary; a local address or a
configuration declaration grants none of those capabilities.

The existing `wiki.proposal.prepare`, `publish`, `promote` and `adopt` commands
retain separate effects. Preparation returns the observed proposal branch,
base and head in `output.proposal`; it does not claim publication, merge or
served installation. Promotion requires independent review and gates on the
exact head. Adoption verifies the approved remote state and preserves the
proposal branch. A lost response requires observation before retry; revocation
can leave a recoverable intermediate checkout instead of authorizing rollback
or another effect automatically.

## Explicit execution extensions

External agent adapters default to disabled. An installation can explicitly
choose its available adapter through `codex.enabled` or `claude.enabled` in
[wiki.config.yaml](../../../wiki.config.yaml). This controls availability;
account authentication, target permission and task authorization still require
the adapter's actual checks.

Deterministic source-review execution is a separate opt-in:

```yaml
admin:
  source_review_enabled: false
```

Without it, `sources.review_pending` is absent from the administrative catalog
and cannot be planned through the bus. Its finite
[source-review planner](../../../wiki_core/web/source_review_jobs.py) remains
available to trusted Python callers. Enabling the extension retains source
allowlists, explicit budgets, proposal branches and current session admission;
collection alone does not verify facts. The operator starts no job worker when
all execution extensions are disabled. No setting installs or resumes a schedule.

## Applying changes

A new content commit is a new read revision. Loaded operator code and process
configuration require a controlled restart; a frontend change requires a new
build and installation of that bundle. The UI cannot perform a universal
reload/rebuild/restart. Preserve prior artifacts, pending evidence and the
paused state of schedules before an installation change; apply the normal
review and consumer adoption policy.
