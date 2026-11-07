# Finite failure routing primitives

The host-only functions in [failure_routing.py](../../../wiki_core/failure_routing.py)
provide one bounded attempt to reconcile an issue, start a repair worker, or
hand off adoption after a verified upstream merge. This is a reusable library,
not a scheduler, runtime installation, event listener, GitHub integration or
proof of real worker execution. No endpoint or command exposes it. A host must
provide fixed, independently authorized provider and executor adapters before
it can be used outside synthetic tests.

## Boundary

The trusted host constructs the `FailureIntent`, chooses the issue target,
template and coordinator routes, and binds each port. These are host-owned
choices, not fields taken from a failure message, issue body or untrusted HTTP
request. The key is a stable opaque, non-secret incident identifier. The issue
adapter must map the template to an approved sanitized public or private body;
this library sends the target, template identifier and a random marker, never
exception text or the incident key. Syntax and secret checks are defense in
depth, not proof that a template or target is safe. Before each effect, the
host's `admit` callback must enforce current policy, actual account/capability,
repository identity and visibility. It must refuse before calling the effect
when authorization is missing. This callback and the ports must never be
selected by a remote caller.

The optional [GitHub issue port](../../../wiki_core/failure_github.py) binds one
host-selected account, repository, visibility and set of reviewed templates.
It checks the live GitHub account and repository on every call and checks write
permission before creation. It invokes the GitHub CLI with an argument array,
puts the approved body in a temporary file, and only returns exact marker or
issue-number readback. Issue search may be delayed; it is not an atomic lock.
Templates are host-curated and scanned for common secrets and personal data;
scanning cannot establish that a text is safe for public release. A host still
needs explicit effect admission and must not expose configuration or template
selection to an untrusted caller. This port cannot verify merged changes or
start a worker.

An optional host-selected existing issue is linked only after exact provider
readback. Otherwise the provider port searches for the stored marker and, if
none exists, creates an issue using the approved template. The returned issue
is not trusted until read back. `IssueRef` and `RunRef` are observations from
trusted host adapters; a fake observation is not execution or authority.

## Reservation and ambiguous outcomes

A per-incident lock serializes attempts from processes sharing the same physical
repository and local lock directory. Receipts use the consumer's configured
derived-data root, which must be local, private and ignored. A small receipt is flushed before
external create/start effects. Replays compare the original intent, issue and
run identities. A different intent or multiple provider matches fails closed.
Unrelated incidents hold different locks and can continue independently.

After a timeout, exception or restart, the router searches for its previous
marker/key. If the effect is observed, it records the result. If a prior intent
exists but no effect is visible, it returns `outcome_uncertain` and does not
retry blindly; remote search can be eventually consistent. Recovery requires a
trustworthy readback or an operator decision outside this API. Admission denial
before an effect is safe to retry. Do not delete receipts while provider effects
may exist. State loss, separate repository clones, separate hosts, network file
systems and untrusted host filesystem mutation are outside this local locking
contract. This does not provide a distributed exactly-once guarantee.

## Handoff and honest state

`route_failure` can observe an existing issue or request its creation and then
ask the executor port to start a repair. A returned `queued`, `running`,
`succeeded` or `failed` is only the provider's readback. `executor_unavailable`
means no worker was started. It does not mark the wiki action complete.

`route_adoption` first rechecks the issue and asks the trusted issue adapter to
verify the *exact* merged revision, required independent review and successful
applicable upstream CI. Until all three are verified, it does not dispatch the
consumer coordinator. The adoption job is keyed separately and pinned to that
revision; revision changes are conflicts. A queued or completed adoption worker
is not evidence that sync, consumer review, merge or publication happened. The
consumer must perform its normal dry run, guarded action transitions, validation
and independent review. A future installed host must bind these ports to the
protected context and existing action contract; this module does not do so.

Focused synthetic tests in [test_failure_routing.py](../../../tests/test_failure_routing.py)
cover linking, creation, admission refusal, recovery, same-repository process
concurrency, unrelated work and the upstream-before-adoption ordering. They do
not test a real GitHub account, installed host, external runtime or consumer.
