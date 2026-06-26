---
title: "AQAL quadrant alignment check"
page_id: report-aqal-quadrant-alignment-2026-06-25
page_type: evaluation_report
context: system
visibility: private_self
updated_at: 2026-06-26
stale_after_days: 180
sources_policy: public_reference_concept_check
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# AQAL quadrant alignment check

Status: concept review completed for the open-source kit after an external
application appeared to attribute an incorrect quadrant interpretation to the
kit.

## Reference Concepts

| Concept | Checked source | Operational consequence |
| --- | --- | --- |
| Four-quadrant axes | [Integral Life: Four Quadrants](https://integrallife.com/four-quadrants/) describes subjective/objective development in individuals and collectives. | The kit keeps the canonical axis pair: interior/exterior x individual/collective. |
| Quadrant names | [Integral Life: Guided Tour](https://integrallife.com/the-four-quadrants-a-guided-tour/) names Upper Left as interior-individual, Upper Right as exterior-individual, Lower Left as interior-collective and Lower Right as exterior-collective. | `q1/q2/q3/q4` remain `I/It/We/Its`, respectively. |
| Lower-left boundary | [Integral Life: 2nd person](https://integrallife.com/meaning-2nd-person/) explains that a real `you` enters the lower-left only through a `we`, and that a collective holon can be represented by its own framework. | Q3 must not be reduced to a plain people list; it captures shared meaning, mutual expectation, culture and relationship context. |
| Lower-right boundary | [Integral Life: Integral Approach](https://integrallife.com/what-is-integral-approach/) distinguishes cultural interiors from exterior social systems and structures. | Formal governance, workflows, systems, platforms and administered role structures are Q4. |

## Kit Finding

The deterministic mapping was not inverted:

| Kit id | AQAL position | Status |
| --- | --- | --- |
| `q1` | `I` / interior individual | Correct, but now clarified for non-person roots as lived or declared intent, not literal consciousness. |
| `q2` | `It` / exterior individual | Correct, but now clarified as observable output/evidence of the root holon, not any document/repository. |
| `q3` | `We` / interior collective | Correct, but now clarified as shared meaning, roles-as-lived, relationships, norms and culture, not a roster. |
| `q4` | `Its` / exterior collective | Correct, and now explicitly includes systems, tools, workflows, governance and roles-as-administered. |

## External Application Compatibility Finding

The current kit does not support the interpretation "Q3 = any people/roles
list" or "Q2 = any file/repository". Those are stale or lossy readings. A
consumer that attributes either rule to the kit is either reading a historical
proposal without its boundary note, using a derived mapping from outside this
repo, or collapsing the AQAL axes into entity buckets.

The compatibility rule for downstream apps is:

- expose the canonical axis pair (`interior/exterior` x
  `individual/collective`);
- preserve `q1/q2/q3/q4` as `I/It/We/Its`;
- classify the extracted fact in relation to the root holon;
- treat rosters, org charts, RACIs, governance forums and workflow assignments
  as Q4 unless the source preserves shared meaning, relationship context,
  culture or roles-as-lived;
- treat files/repositories/tools as Q2 only when the specific fact is owned
  output/evidence; the coordinating platform/workflow is Q4.

Topical perspectives are not quadrant definitions. For example, the stakeholder
perspective can extract people, roles and commitments across quadrants; only the
roles-and-relationships perspective with `quadrant: q3` is the Q3 AQAL contract,
and even there plain administered structures remain Q4 unless shared interior
meaning is present.

## Boundary Rule

Classify the fact being extracted, not merely the source type:

| Item | Q2 when | Q3 when | Q4 when |
| --- | --- | --- | --- |
| Repository | Owned code/output/evidence of the root entity. | It carries shared coding norms or collaboration meaning. | CI, branching, review gates or workflow coordination are the relevant facts. |
| Document | It is evidence, artifact, report or direct output. | It records shared narrative, relationship meaning or lived expectations. | It defines a process, policy, governance rule or operating cadence. |
| Person/role | Individual observable action belongs to that person's own exterior view. | The role is lived as mutual expectation or relationship context. | The role is an administered org chart, RACI, approval rule or workflow assignment. |
| Tool/channel | An exported object from the tool is evidence. | A conversation establishes shared meaning. | The platform/channel coordinates work, access, cadence or governance. |

## Repository Changes

- [wiki_core/input_stage.py](../../../wiki_core/input_stage.py) now emits the
  clarified quadrant semantics and boundary rule into generated input-stage
  catalogs.
- [wiki_core/config.py](../../../wiki_core/config.py) now defaults
  `context_deep_read` to `v3`, so external consumers that instantiate the kit
  without an explicit `wiki.config.yaml` receive the canonical root-holon AQAL
  contract instead of the historical prompt.
- [context_deep_read.v3.md](../../../wiki_core/llm/prompts/context_deep_read.v3.md)
  now carries the same Q3/Q4 boundary so delegated LLM reads cannot reduce Q3 to
  a roster or administered role structure.
- [root-entity.md](../templates/wiki/root-entity.md), the kit root entity and
  perspective pages now teach the same boundary.
- Historical planning labels that could be read out of context were tightened:
  Q3 is now described as shared meaning, culture, relationships and
  roles-as-lived, not as a generic people/roles bucket.
- [tests/test_input_stage.py](../../../tests/test_input_stage.py) and
  [test_aqal_quadrants.py](../../../tests/test_aqal_quadrants.py) prevent
  regression to the older ambiguous wording.

## Validation

```sh
python3 scripts/wiki_input_stage.py --check
python3 scripts/wiki_audit.py --check
python3 -m pytest tests/test_config.py tests/test_wiki_pipeline.py
python3 -m pytest tests/test_input_stage.py tests/test_aqal_quadrants.py
```
