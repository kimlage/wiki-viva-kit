# Anatta Worlds comparable prototype contract

## Question

Which spatial grammar makes one Anatta Worlds loop feel like a single,
inhabitable 3D + 2D experience while remaining legible, truthful and feasible?

Three structurally different variants run on one route and one state machine.
Switching variants never resets the session.

## Synthetic world

**World:** Jardim Aurora
**Intention:** Keep the garden healthy with responsible water use and traceable
decisions.

The fixture is public and synthetic. It represents a small community garden
because a safe physical action, a returned observation and one localized
geographic consequence can be understood without private context.

### Source and snapshots

`source.aurora-station` is the authorized synthetic community station. It is
read-only, has a declared owner, daily observation recipe and immutable raw
snapshots.

| Snapshot | Observed fact | Limit |
| --- | --- | --- |
| `snapshot.day-0` | Leste 31%; Oeste 32%; chuva observada 0 mm; reservatório 64% | historical observation |
| `snapshot.day-1` | Leste 16%; Oeste 31%; chuva observada 0 mm; reservatório 62%; previsão de chuva em 6 h: 70% | forecast is not observed rain |
| `snapshot.return` | Leste before 15%; observed rain 0 mm; 8 L applied; Leste after 20 min 26% | exists only after the prototype's explicit time jump |

Event time and record time remain distinct. The pre-return world may show a
projection, never promote forecast to observed rain or imply action occurred.

### Two lenses

- `module.hydrology@1` detects the localized deficit and proposes a conditional
  8 L intervention if field evidence confirms at most 18%.
- `module.climate@1` exposes a 70% rain forecast and recommends waiting or
  seeking evidence, while stating that forecast is not observed rain.

Both projections point to the same immutable snapshots, declare inputs and
limits and remain interpretations. Their disagreement creates
`tension.east-dryness`.

### Mission and choices

`mission.inspect-water-east` asks the player to measure the East bed; if it is
at most 18% with no observed rain, apply 8 L, wait 20 minutes and measure again.
Cost imported from reality is 25 minutes and at most 8 L. The player may:

1. do;
2. delegate;
3. ask for evidence;
4. compost without guilt.

The prototype can time-jump a returned source only through an explicitly
labelled **Simulate synthetic source return** action. It never claims a real
person acted.

### Human gate and receipt

After the returned snapshot, an agent operating under
`grant.agent-proposal-only` may normalize and propose, but not decide. The human
gate shows source owner, before/after snapshots, event/record times, both
lenses, the returned evidence, grant, impact and the alternative of no change.

The canonical partial gate:

- accepts “8 L were applied”;
- corrects “East is resolved” to “East is recovering”;
- rejects “the whole garden climate risk is resolved”.

It emits `receipt.aurora-001` before mutation. Only then may
`worldPatch.east-recovering` change `entity.bed-east`. West, reservoir, sky and
global world state remain untouched. Evidence-only, compost and rejection
receipts are valid and do not mutate geography.

## Shared state machine

```text
quiet
  → diff_available
    → tension_focused
      → mission_selected
        → offscreen_action
          → evidence_returned
            → agent_proposal
              → human_gate
                → receipt_issued
                  → local_mutation_committed
                    → session_closed
```

The canonical comparison uses **do**. `delegate` is blocked by the agent's
proposal-only grant; `ask for evidence` remains pending without mutation;
`compost` closes without guilt and with an explicit no-change receipt. Reset is
always available.

Every operational mark resolves to one of the IDs above, its typed state, the
source snapshot and the rule that authorized its appearance. Ambient motion is
labelled decorative and cannot encode activity, urgency or health.

## Variant boundaries

| Variant | May change | Must not change |
| --- | --- | --- |
| A — Living organism | perspective camera, persistent world, projected anchor, dock transition | fixture, labels, choices, reducer, receipt |
| B — Topographic table | orthographic camera, height/contour treatment, in-place layers | fixture, labels, choices, reducer, receipt |
| C — Direct scales | world/district/interior composition and direct transitions | fixture, labels, choices, reducer, receipt |

## Budget

| Walking skeleton | Desktop | Mobile |
| --- | ---: | ---: |
| interactive 3D anchors | 96 | 48 |
| simultaneous relations | 80 | 40 |
| diegetic labels | 16 | 12 |
| particles | 60 | 0 |
| primary 2D focus surfaces | 1 | 1 |
| target / minimum FPS | 60 / 30 | 45 / 24 |
| input feedback | at most 100 ms | at most 150 ms |

Additional limits:

- one Canvas and one camera per mounted variant;
- no video or structural eager image;
- no bespoke visual assets in P0;
- at most 512 kB of transferred visual assets;
- pointer, keyboard and touch access;
- reduced motion and forced 2D equivalent;
- verification at 360×800, 390×844 and 1280px or wider;
- initial and lazy chunks remain within the cockpit's existing gates.

## Human comparison

For each variant, answer:

1. What became easier to understand because it was spatial?
2. Did the 2D surface feel like the same place or another application?
3. Could you distinguish observation, projection, proposal, decision and receipt?
4. Did the localized mutation feel earned and traceable?
5. Where did the interface become expensive, confusing or fragile?

The winner may combine roles only when the responsibility of each grammar is
explicit, for example direct scales for navigation, a topographic district for
operation and organism behavior only for visible consequence.
