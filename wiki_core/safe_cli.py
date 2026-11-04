"""Opaque CLI errors with stable non-sensitive reasons."""
import argparse
import json
import sys


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, json.dumps({'status': 'error', 'reason': 'invalid_arguments'}) + '\n')


_REASONS = {
    'v2 result required; v1 results need explicit migration': 'v1_result_requires_migration',
    'v2 packet required; v1 packets need explicit migration': 'v1_packet_requires_migration',
    'v2 policy requires a v2 packet; v1 receipts require explicit migration': 'v1_receipt_requires_migration',
    'v2 evidence connection unavailable': 'evidence_authority_unavailable',
    'historical v2 evidence authority unavailable': 'historical_authority_unavailable',
    'current input authority unavailable': 'current_authority_unavailable',
    'current source authority unavailable': 'current_authority_unavailable',
    'policy revision is not current trusted approval ref': 'approval_ref_moved',
    'context boundary or instructions require separate review': 'normative_review_required',
    'v2 requirement migration and revalidation unavailable': 'requirement_migration_required',
    'existing output needs a reported whole prior read': 'whole_prior_read_required',
    'ambiguous or normative change requires separate review': 'normative_review_required',
    'dynamic v1 query requires independent v2 requalification': 'dynamic_query_requalification_required',
    'historical v1 policy access unavailable; normative equivalence not assessed': 'historical_policy_authority_unavailable',
    'v1 context requires explicit owner migration': 'owner_migration_required',
    'source owner changed; explicit migration required': 'owner_migration_required',
    'approved consumer differs from proposal': 'consumer_changed_since_proposal',
}


def report_failure(exc):
    # Exception text may include paths, credentials, remote names or selectors.
    reason = _REASONS.get(str(exc), 'operation_failed') if not isinstance(exc, OSError) else 'operation_failed'
    print(json.dumps({'status': 'error', 'reason': reason}), file=sys.stderr)
