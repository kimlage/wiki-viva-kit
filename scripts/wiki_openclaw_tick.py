#!/usr/bin/env python3
"""Observe one approved rule via a fresh, ephemeral native operator session.

No direct dispatch API, durable credential, task queue or scheduler. Run by the
authorized local coordinator; the configured rule is its complete effect scope.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import threading
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.config import load_config
from wiki_core.web.server import CockpitServer
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER


def observe(root, rule_id, *, dry_run=False):
    config = load_config(root)
    if rule_id not in config.openclaw.get('recurring', {}):
        return {'ok': False, 'error_code': 'openclaw_recurring_not_configured'}
    code = {}
    def announce(line):
        match = re.fullmatch(r'\[wiki-admin\] one-time unlock code: ([A-Z0-9-]+) \(.*\)', line)
        if match:
            code['value'] = match.group(1)
    server = CockpitServer(('127.0.0.1', 0), root, config, admin_announce=announce)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = 'http://127.0.0.1:' + str(server.server_address[1])
    token = None
    nonce = None
    def request(path, payload=None):
        # This is a native HTTP client, not a browser origin. The existing
        # operator's CLI path still requires nonce, startup unlock and session.
        headers = {'Content-Type': 'application/json',
                   'X-Wiki-Attempt-Key': str(uuid.uuid4())}
        if nonce:
            headers['X-Wiki-Operator-Nonce'] = nonce
        if token:
            headers[ADMIN_SESSION_HEADER] = token
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(origin + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            return json.load(error)
    try:
        nonce = request('/api/health')['operator_security']['nonce']
        challenge = request('/api/admin/session/challenge', {})
        unlocked = request('/api/admin/session/unlock', {'challenge': challenge.get('challenge'),
                                                       'code': code.pop('value', '')})
        if not unlocked.get('ok'):
            return {'ok': False, 'error_code': unlocked.get('error_code', 'admin_session_required')}
        token = unlocked['token']
        plan = request('/api/admin/commands/plan', {'command_id': 'agents.openclaw.tick',
            'params': {'rule_id': rule_id}, 'dry_run': dry_run})
        if not plan.get('ok'):
            return {'ok': False, 'error_code': plan.get('error_code'), 'detail': plan.get('detail')}
        result = request('/api/admin/commands/execute', {'plan_id': plan['plan_id'],
            'plan_sha': plan['plan_sha'], 'confirmation': plan['plan']['confirmation']['text']})
        output = result.get('output', {})
        # Never emit the unlock/token/nonce, prompt, native message or response
        # text. The retained native receipt is the normal result port.
        return {'ok': result.get('ok', False), 'error_code': result.get('error_code'),
                **{k: output[k] for k in ('mode', 'effect_key', 'run_id', 'native_run_id', 'status',
                    'result_available', 'new_dispatch', 'integration_hold', 'dry_run') if k in output}}
    finally:
        try:
            if token:
                request('/api/admin/session/lock', {})
        finally:
            token = nonce = None
            code.clear()
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--rule', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    result = observe(args.root.resolve(), args.rule, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
