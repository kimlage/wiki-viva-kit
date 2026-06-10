# Template - infographic (visual insight artifact)

```yaml
---
page_id: template-infographic
page_type: infographic
title: "Infographic - visual artifact"
aliases:
  - Infographic
  - Visualization
  - Insight chart
tags:
  - wiki/template
  - wiki/perception
  - wiki/infographic
  - status/template
status: template
context: system
visibility: private_reference
purpose: "Communicate an insight or data point visually, with a question, a source, and an accessible textual alternative."
owner: {{owner_id}}
updated_at: YYYY-MM-DD
stale_after_days: 30
status_epistemologico: insight
moc_parent: memories/index.md
related_pages:
  - docs/references/templates/wiki/insight.md
  - docs/references/templates/wiki/source.md
perception_policy:
  layer: perceptiva
  is_canonical_truth: false
  preferred_outputs:
    - infografico
    - grafico
    - diagrama
  accessibility:
    alt_text_required: true
    color_only_encoding_forbidden: true
    plain_language_summary_required: true
source_counts:
  live_sources: 0
  references: 0
  derived_artifacts: 1
attachment_policy: "Image of the artifact in data/derived or data/raw with a Markdown link. Private repo: personal data (names, values) is acceptable at the appropriate visibility; never embed access secrets."
---
```

# Infographic - visual artifact

Updated on: YYYY-MM-DD

> An infographic is a perceptive layer: it **interprets** data, it does not replace it.
> The canonical reading lives in the cited sources. Every image needs a textual
> alternative (alt text) and a plain-language summary.

## Question it answers

-

## Audience

- Who it is for:
- Assumed level of context:

## Data used

| Data | Source | Time window | Reliability |
| --- | --- | --- | --- |
|  |  |  |  |

## Transformations applied

- Filters, aggregations, normalizations:
- Scale/axis choices:
- What was intentionally omitted:

## Visual artifact

- Image: [infographic file](../../../../data/derived/) <!-- replace with the real file -->
- Format (svg/png/diagram):

## Accessible textual alternative

- Alt text (short description of the image):
- Plain-language summary (what the chart shows, without relying on color):
- Encoding used beyond color (label, shape, order):

## Limitations and confidence level

- Known limitations:
- Confidence level: `low` | `medium` | `high`
- What could change the reading:

## Source, authorship, version, visibility

- Authorship:
- Version:
- Visibility: `private_reference`
- Gate: PR on GitHub

## Related

- MOC: [index.md](../../../../memories/index.md)
- Associated insight: [insight.md](insight.md)
- Data source: [source.md](source.md)
