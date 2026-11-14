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
})

# Preserve useful, exact domain diagnostics without printing variable errors.
_STATIC_OPERATION_ERRORS = frozenset({
    'current Git root unavailable',
    'coordination host binding required',
    'folder coordination host binding required',
    'host binding unavailable',
    'additional reader host binding unavailable',
    'composite host binding unavailable',
    'host binding requires authorized requalification',
    'composite participant input unavailable',
    'owned range does not support extra trusted contexts',
    'explicit executor context required for trusted selection',
    'current folder is outside the selected wiki',
    'packet context differs from explicit executor',
    'complete authorized action route required',
})


class SafeArgumentParser(argparse.ArgumentParser):
    """Keep usage while preventing parser errors from echoing values."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        detail = message if message in _STATIC_ARGUMENT_ERRORS else 'invalid arguments; use --help'
        self.exit(2, f'{self.prog}: error: {detail}\n')


def report_context_error(error: Exception) -> None:
    """Print only an exact known diagnostic or an opaque fallback."""
    message = str(error)
    detail = message if not isinstance(error, OSError) and message in _STATIC_OPERATION_ERRORS else 'context operation unavailable'
    print(detail, file=sys.stderr)
