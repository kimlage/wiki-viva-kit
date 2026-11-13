# Changelog

## 9.2.4 — release preparation

- Add opt-in `context_discovery.exclude` folder prefixes to keep explicitly
  selected documentary trees from becoming automatic context owners. Default
  discovery is unchanged. Root exclusion, malformed configuration and conflicts
  with explicit context access fail closed; path safety and read denials remain
  enforced. Files retain the nearest remaining context owner.
- Document the existing parent read ceilings and exact bilateral connections:
  a broad child requires broad enough ancestors, and `read: ["."]` alone does
  not authorize foreign document bodies. No permission semantics are widened.

### Upgrading

No configuration migration is required for existing behavior. To exclude a
documentary tree, review its ownership change and add the explicit option to
the approved `wiki.config.yaml`; see the [context reader guide](docs/references/guides/context-reader.md#documentary-trees-and-context-discovery).
Rebuild affected packets against the approved policy and an authorized content
revision. Exclusions do not reauthorize historical evidence.

The [release notes](docs/references/releases/wiki-viva-v9.2.4.md) also summarize
the already integrated changes since v9.2.3 and their adoption requirements.
Release preparation follows the existing [release policy](README.md#release-policy):
independent review, normal CI, release notes with an Upgrading section and a
tag. Adoption uses the reviewed B0/C1/C2/C3 flow; this entry does not publish a
release. The candidate version and README identify 9.2.4; use its tag only after
publication.
