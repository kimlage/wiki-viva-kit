# Synthetic ingestion pilot (E2E fixture)

This file contains NO real data. It is a synthetic, versioned source used by
the end-to-end test to exercise the complete ingestion chain of the living wiki
without depending on raw data (which is never versioned in git).

## Context

The June operational meeting decided to consolidate the weekly cockpit and
review the queue of pending actions. The owner became responsible for validating
the financial reconciliations before the monthly close. The team recorded the
risk of rework when the deep reading does not happen before consolidating
canonical memory.

## Decisions and actions

The main decision was to adopt the LLM pass gate as blocking: no source becomes
consolidated memory while the contextual reading of each chunk has not been
recorded in the cache. The immediate action is to run the pilot over a real
source when the owner authorizes it, keeping the original out of git and linked
through Drive.

## Relationships

The ingestion system relates to the operational cockpit (consumes score), to the
privacy detectors (pre-scan at capture) and to the gate state machine (rebase
and supersede by logical target). These links sustain the living wiki as a
single organism, not as manually triggered islands.
