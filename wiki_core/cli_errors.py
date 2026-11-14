"""Bounded CLI diagnostics that do not echo operator-supplied values."""
from __future__ import annotations

import argparse
import sys

# These messages are authored by the CLI, not built from argument values.
_STATIC_ARGUMENT_ERRORS = frozenset({
    'host binding readback does not accept stage or task options',
    'source stage requires approved-revision; provide stage JSON on stdin',
    'protected mode requires context-id, approved-revision and packet-request; legacy profile/event options are separate',
    'folder and index require protected packet mode',
    '--event-file requires --profile, --action-id, --action-path and --expected-sha256',
    'write options require --event-file',
    '--action-id requires --profile',
    'event file exceeds limit',
    'event coordinator must equal selected profile',
    'event input unavailable',
    'repository root unavailable',
})

class SafeArgumentParser(argparse.ArgumentParser):
    """Keep usage while preventing parser errors from echoing values."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        detail = message if message in _STATIC_ARGUMENT_ERRORS else 'invalid arguments; use --help'
        self.exit(2, f'{self.prog}: error: {detail}\n')


def report_context_error(error: Exception) -> None:
    """Keep audited diagnostics only for the exact exception class and text."""
    from wiki_core.context_policy import PolicyError
    from wiki_core.context_impact import ImpactError
    from wiki_core.context_integration import IntegrationError
    from wiki_core.context_requirements import RequirementError

    safe = {
        PolicyError: frozenset({
            'current Git root unavailable', 'policy revision is not current trusted approval ref',
            'coordination host binding required', 'folder coordination host binding required',
            'host binding requires authorized requalification', 'composite participant input unavailable',
            'owned range does not support extra trusted contexts',
            'explicit executor context required for trusted selection',
            'current folder is outside the selected wiki', 'packet context differs from explicit executor',
            'complete authorized action route required', 'secret detected in packet input',
            'invalid byte budget', 'context qualification exceeds byte budget',
            'producer qualification exceeds byte budget', 'complete packet exceeds byte budget',
            'mandatory content exceeds byte budget', 'selected content exceeds byte budget',
            'query operation byte limit exceeded',
        }),
        IntegrationError: frozenset({
            'approved base moved', 'branch head changed', 'result changes do not match branch',
            'host binding unavailable', 'additional reader host binding unavailable',
            'composite host binding unavailable', 'folder authority cannot be requalified',
            'existing normative requirement requires requalification',
            'existing query requirement cannot be revalidated', 'secret detected in proposal',
            'secret detected in integration metadata',
        }),
        ImpactError: frozenset({
            'impact after revision must be current approval', 'folder context requires authorized requalification',
            'cross-context folder authority requires requalification',
            'historical target requires authorized requalification',
            'historical source requires authorized requalification',
            'secret detected in selected content', 'secret detected in impact metadata',
            'secret detected in review metadata',
        }),
        RequirementError: frozenset({
            'coordination host binding required', 'host binding unavailable',
            'additional reader host binding unavailable', 'folder context requires authorized requalification',
            'packet authority format differs; requalification required',
            'folder context input requires requalification', 'complete authorized action route required',
            'secret detected in consumer',
            'secret detected in task metadata', 'secret detected in output',
            'secret detected in input', 'secret detected in requirement metadata',
        }),
    }
    try:
        message = str(error)
    except Exception:
        message = ''
    detail = message if message in safe.get(type(error), ()) else 'context operation unavailable'
    print(detail, file=sys.stderr)
