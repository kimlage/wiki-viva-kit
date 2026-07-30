# Inventory the experimental lineages and untracked WIP

Type: research
Mode: AFK
Status: resolved
Blocked by: none
Owner: Codex research thread, 2026-07-30

## Question

Which committed branches and uncommitted artifacts contain product intent,
runtime capability or visual evidence, and which one is safe as the new base?

## Answer

Use `wiki/consolidacao-2026-07-21` as the technical base. Its committed runtime
tip was `eb664503`; commit `44913a1d` adds only the preserved vNext proposal and
is the base of this branch. The working tree's launch configuration and npm
cache were not copied.

Treat the visual lineage as a library, not a base:

- `wiki/planetary-prototype-gallery` at `e492f08c` records the implemented
  planetary gallery and cinematic journey.
- `wiki/mundos-vivos-gdd-3-20260726` diverged from consolidation and reached
  `7142a3fe`; its distinct Mundos Vivos GDD is preserved at `a1459090`.
- `wiki/anatta-worlds-gdd-3-narrativa-20260727` now preserves the distinct
  Anatta Worlds GDD at `ecada7e2`.
- `wiki/mundo-vivo-composto` is an alias of the earlier `7142a3fe` tip and is
  historical until its intent has been compared.

The consolidation and visual line diverged at `7fb64859`, with 28 and 25
exclusive commits respectively. Neither is ancestor of the other, so an
unreviewed merge would combine two architectures and large asset histories.

Private-repository research, GDD proposals and storyboards remain separate
sources of intent. They are not implementation bases. Cloud Code scratchpads
outside Git contain several gigabytes of source, references and caches; they
remain quarantine WIP until a ticket separates code and evidence from generated
or downloaded material.

No branch is proven absorbed into `origin/main`, and no branch or worktree is
safe to delete.
