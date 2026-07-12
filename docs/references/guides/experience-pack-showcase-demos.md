# Deterministic experience-pack showcase demos

The public demo builder has two pack-enabled mini-wikis. They use the packs'
authored `fixtures/normal` data, install the pinned pack into a disposable
fixture repository, and compile the same real snapshot contract used by a wiki.
The kit's root `wiki.packs.lock.yaml` is never read as installation state and is
never mutated by showcase generation.

## Allowlisted scenarios

| Scenario | Active pack | Public pages | Generated snapshot | Representative route |
| --- | --- | ---: | --- | --- |
| `study_research_showcase` | `study-research@0.1.0` | 5 | `sample-snapshot/scenarios/study_research_showcase` | `/demo/w?demo_scenario=study_research_showcase&center=root-study-research-showcase&view=quadrants&overlay=evidence&tour=0` |
| `personal_finance_showcase` | `personal-finance@0.1.0` | 10 | `sample-snapshot/scenarios/personal_finance_showcase` | `/demo/w?demo_scenario=personal_finance_showcase&center=finance-transaction-income&view=timeline&time_mode=event&time_lanes=page&tour=0` |

The executable allowlist and exact page-set hashes live under
[`scenarios/pack-showcases`](../fixtures/demo-wiki/scenarios/pack-showcases/manifest.yaml).
The normal, dense-stress and Genesis registries remain separate. Their fixture
selection and active-pack state are therefore unchanged: they continue to
publish the exact empty pack composition unless their own contract is advanced.

## Generate and verify

Generate only one showcase without rebuilding the default, dense or Genesis
artifacts:

```sh
/opt/anaconda3/bin/python scripts/wiki_build_demo.py --pack-showcase study_research_showcase
/opt/anaconda3/bin/python scripts/wiki_build_demo.py --pack-showcase personal_finance_showcase
```

Generate the complete committed demo tree, including both showcases:

```sh
/opt/anaconda3/bin/python scripts/wiki_build_demo.py
```

Verify every committed fixture and snapshot by isolated regeneration:

```sh
/opt/anaconda3/bin/python scripts/wiki_build_demo.py --check
```

Every showcase must prove all of these conditions:

- `manifest.json.contract_errors` is empty;
- `manifest.json.capabilities` advertises `experience_packs`;
- `experience_packs.json` has the expected active pack, block packages and
  non-empty view, command, operation and timeline slots;
- every declared fixture page exists in `pages.json` and has a content sidecar;
- the semantic timeline has at least the manifest's minimum event count;
- two isolated generations are byte-identical;
- the kit root lock is byte-identical before and after generation.

## Navigation adapter

Pack fixture pages keep their authored domain fields. The disposable demo adds
only common graph fields (`context`, `updated_at`, `moc_parent`, normalized
source/evidence/related-page references) and a backlink to the showcase root.
This makes fixture pages, evidence and synthetic review anchors navigable in
the current core world without rewriting the reusable pack.

The finance showcase adds two demo-only public anchors: a synthetic statement
and a synthetic human close review. They close the fixture's source and review
references; they are not installed as pack content.

## Honest limits

- A static showcase displays compiled contributions; it never executes an
  operation or writes user data. Real pack operations remain dry-run first and
  human-Git-gated.
- The finance data is entirely synthetic and is neither a live ledger nor
  financial advice.
- Fixture-field adaptation remains a demo bridge, while the reusable runtime
  now registers active-pack page types/templates for real `wiki_new.py` flows.
  Pack schema v1 declares field names but not domain types/requiredness, so
  semantic field validation remains a future contract revision.
- The cockpit allowlists both scenario IDs and exposes them on `/demo`; unknown
  values still fail closed to `normal_operations`.
- The cockpit renders the composed catalog and a generic, shareable
  `pack_view` workbench over canonical namespaced pages. It can open the real
  reader and hand temporal descriptors to the verified Chronoscope, while
  keeping commands/operations disabled with an explanation. Pack-specific
  renderers, operation executors and profile-aware temporal filters remain
  adapter work; unmounted contributions are never presented as executable.
- Composition v1 publishes `block_packages` globally rather than attributing
  each package to one pack. The UI therefore labels the collection as composed
  state and does not invent per-pack ownership.
