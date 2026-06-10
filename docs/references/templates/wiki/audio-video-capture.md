# Template - audio/video capture (with transcript and markers)

```yaml
---
page_id: template-audio-video-capture
page_type: media_capture
title: "Audio/video capture"
aliases:
  - Audio capture
  - Video capture
  - Media capture
tags:
  - wiki/template
  - wiki/perception
  - wiki/media-capture
  - status/template
status: template
context: system
visibility: private_reference
purpose: "Record audio or video with transcript, temporal markers and privacy policy."
owner: {{owner_id}}
updated_at: YYYY-MM-DD
stale_after_days: 30
status_epistemologico: fato
moc_parent: memories/index.md
related_pages:
  - docs/references/templates/wiki/source.md
  - docs/references/templates/wiki/ingestion-event.md
perception_policy:
  layer: perceptiva
  is_canonical_truth: false
  preferred_outputs:
    - transcricao
    - marcadores_temporais
    - capturas_de_tela
  accessibility:
    alt_text_required: true
    color_only_encoding_forbidden: true
    plain_language_summary_required: true
source_counts:
  live_sources: 1
  references: 0
  derived_artifacts: 0
attachment_policy: "Raw media in data/raw or Drive (Markdown link). Never embed credentials; respect the consent of those who appear/speak."
---
```

# Audio/video capture

Updated on: YYYY-MM-DD

> The transcript is treated as `fato` (what was said/recorded); derived
> interpretations should become a separate insight. Every visual capture needs alt text
> and the media needs a clear privacy policy.

## Media artifact

- Artifact link: [media file](../../../../data/raw/) <!-- or a Drive link -->
- Type: `audio` | `video`
- Duration:
- Captured on (date):
- Captured by:

## Participants and consent

- Who appears/speaks:
- Consent to record: `yes` | `no` | `partial`
- Usage restrictions:

## Transcript

- Language:
- Method (manual / automatic + review):

```text
(paste the transcript here)
```

## Plain language summary

-

## Temporal markers

| Time | Marker / topic | Note |
| --- | --- | --- |
| 00:00 |  |  |
| 00:00 |  |  |

## Selected captures (frames)

| Time | Image | Alt text (description) |
| --- | --- | --- |
| 00:00 | [frame](../../../../data/derived/) |  |

## Privacy policy

- Visibility: `private_reference`
- Sensitive data present: `yes` | `no`
- Handling (anonymization/cropping before sharing):
- Who can access the raw media:
- Gate: PR on GitHub

## Limitations

- Inaudible or uncertain segments:
- Transcript confidence level: `low` | `medium` | `high`

## Related

- MOC: [index.md](../../../../memories/index.md)
- Source: [source.md](source.md)
- Ingestion event: [ingestion-event.md](ingestion-event.md)
