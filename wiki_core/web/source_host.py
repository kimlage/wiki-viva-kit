"""Ephemeral host pairing for an explicitly enabled opaque Electron embed.

No source permission, provider credential or account observation is granted.
Attestation is POSTed through the existing local operator nonce/attempt gate
by the authenticated native plugin backend, never by an iframe message.
"""
import secrets
import threading
import time


class SourceHostPairing:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = {}

    def challenge(self):
        with self.lock:
            now = time.monotonic()
            self.rows = {key: value for key, value in self.rows.items() if value['expires'] > now}
            if len(self.rows) >= 128:
                raise ValueError('source_host_busy')
            key = secrets.token_hex(24)
            self.rows[key] = {'expires': now + 45, 'host_id': None}
            return key

    def attest(self, key, host_id):
        with self.lock:
            row = self.rows.get(key)
            if not row or row['expires'] <= time.monotonic() or row['host_id'] is not None or host_id != 'wiki-viva-board':
                raise ValueError('source_host_challenge_invalid')
            row['host_id'] = host_id
            return {'attested': True}

    def status(self, key):
        with self.lock:
            row = self.rows.get(key)
            return {'attested': bool(row and row['expires'] > time.monotonic() and row['host_id'] == 'wiki-viva-board')}
