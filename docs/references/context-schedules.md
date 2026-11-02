# Optional context schedule advice

A declaration is disabled when `enabled` is omitted. The synthetic example in
`examples/context-schedule/request.json` is disabled and installs nothing. The
schema `wiki-context-schedule-v1.schema.json` describes the bounded JSON request.
This optional module is independent of runtime/UI/config and any scheduler vendor.

`validate_schedule(schedule)` validates a declaration. `evaluate_wake(policy,
schedule, wake, observation=None)` returns `no-op`, `eligible`, or `blocked` with
zero LLM calls. Eligibility only identifies work for further review:
`execution_authorized` is always false and `admission` always blocked. Missing
binding observation is `unknown`; supplied observation is merely `reported`,
even when it says `installed: true`. Neither this module nor its CLI verifies
installation, creates an automation, notifies anyone, executes a command/model,
or stores state. Cost and process termination remain unmeasured/unknown.

```sh
python3 scripts/wiki_context_schedule.py --repo /path/to/isolated/repo \
  --approved-revision APPROVED_SHA --request /path/to/request.json
```

The current trusted approval ref supplies context policy through `load_policy`.
The template must be a safe path owned by and readable to the selected context.
The snapshot may contain only that context's tasks and records. Inputs are
bounded to 64 KiB, arrays to 100, attempts/tasks to finite limits, with strict
fields, timezone/date validation and secret scanning. No source content is read.
The CLI rejects duplicate JSON keys and never prints invalid input or paths.

Pause globally wins over local eligibility and approval errors. Latest-only
catch-up skips older occurrences. Times come from the external scheduler; there
is no cron/DST computation. UTC-normalized due time plus context/schedule IDs
identify an occurrence; context plus stable external task ID identifies work.
Completed occurrence dedupes; unchanged completed fingerprint also yields no-op.
The external scheduler must retain stable task IDs and authoritative fingerprints.
The minimal contract treats one stable task as one effect attempt budget; adapters
with multiple effects must retain their separate journals outside this advice.
Only a classified `safe_failure` with remaining per-effect attempts may retry;
max tasks and max attempts per wake bound returned candidates, with each candidate
consuming one prospective attempt. `uncertain`, `running` and `denied` records
block the whole wake; omission of a retained record is not reconciliation.
An expired lease never proves an executor stopped. This is not exactly-once
execution and does not cancel a running process or reverse an effect.

The scheduler adapter remains responsible for:

- Authorizing the caller to inspect the selected context and providing a complete,
  authentic context-scoped snapshot; this library is not an authentication boundary.
- Calculating due/latest occurrences, timezone/DST/catch-up and clock validity;
  refreshing binding, host, owner, installed agenda, interaction and pause reports.
- Revalidating global pause, approved declaration, policy, template existence,
  packet read/write permissions, capabilities and sending authorization immediately
  before any actual task/model/effect admission. The JSON declaration itself is
  not approved policy and does not widen permissions.
- Atomically reserving existing scheduler task/occurrence identities, attempts and
  concurrency budgets, with owner/expiry leases and fencing where supported;
  preserving intent/receipt and reconciling unknown effects before replay.
- Keeping denials and relevant new authorization evidence without changing IDs to
  bypass them; reconciling changed policy before resumption. No parallel queue is
  created here. A reported stopped/paused schedule proves no process cancellation.
- Measuring calls, tokens, duration and cost only from actual observed reports.

There is no scheduler adoption or migration in this change. To roll back this
optional feature, stop consuming its advice and retain external receipts/state;
removing a module cannot reconcile an external effect. Focused synthetic tests
exercise pause, dedupe, unchanged fingerprints, budgets, overlap, uncertainty,
revocation, owner isolation, disabled declarations, observations and CLI bounds.
