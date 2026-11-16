"""Issue #524: access codes and hash-config fields are secrets.

Synthetic values only. Every finding is fully masked, so no code survives in an
audit report, and ordinary prose about these secrets is not flagged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import scripts.wiki_audit as audit
from wiki_core.config import load_config
from wiki_core.detectors.secrets import scan_secrets

# Fixtures are joined at runtime so no source line holds a detectable value;
# the kit's pre-push hook scans every pushed blob with this same detector.
SIGNER = "c3ludGhldGljLXNpZ25lci1rZXkt" + "bm90LXJlYWwtMTIzNDU2Nzg5MA=="
CODE = "4829" + "13"
SALT = "Bw" + "=="

# (prefix, value, suffix, kind)
POSITIVE_PARTS = [
    ('invite_code: "', "Ab3k" + "Z9qL", '"', "access_code"),
    ('{"inviteCode": "', "Q7fK" + "2mXp", '"}', "access_code"),
    ("VERIFICATION_CODE=", CODE, "", "access_code"),
    ("otp: ", CODE, "", "access_code"),
    ("pairing_pin = ", "77" + "31", "", "access_code"),
    ("Your verification code is ", CODE, ".", "access_code"),
    ("Código de verificação: ", CODE, "", "access_code"),
    ("Codigo de convite ", "ZQ71" + "KD", "", "access_code"),
    ("código de invitación ", "ABc9" + "xYz2", "", "access_code"),
    ("Join: https://example.test/invite/", "AbCdEf" + "123456", "", "individualized_access_link"),
    ("https://example.test/join?invite=", "Zx81Kp" + "22aa", "", "individualized_access_link"),
    ('"hashConfig": {"signerKey": "', SIGNER, '"}', "hash_config_secret"),
    ('saltSeparator: "', SALT, '"', "hash_config_secret"),
    ("base64_signer_key=", SIGNER, "", "hash_config_secret"),
]
POSITIVES = [(prefix + value + suffix, kind, value) for prefix, value, suffix, kind in POSITIVE_PARTS]

NEGATIVES = [
    "Invite codes and verification codes are secrets.",
    "verification code: <redacted>",
    "invite_code: example",
    "invite_code: XXXXXX",
    "The hashConfig fields signerKey and saltSeparator are secret.",
    "signerKey: <redacted>",
    "saltSeparator: none",
    "verification_status: passed",
    "confirmation code expired",
    "Nao registrar codigo de acesso DocuSign nem link seguro individualizado.",
    "https://github.com/example/repo/issues/524",
    "https://example.test/verify/email",
    "Code review: 2 rounds",
]


@pytest.mark.parametrize(("text", "kind", "value"), POSITIVES)
def test_access_codes_and_hash_config_are_secrets(text, kind, value):
    findings = [f for f in scan_secrets(text) if f.kind == kind]
    assert findings, text
    for finding in findings:
        assert finding.category == "secret"
        assert value not in finding.excerpt
        assert value[:3] not in finding.excerpt.split(":", 1)[1]


@pytest.mark.parametrize("text", NEGATIVES)
def test_prose_and_placeholders_are_not_flagged(text):
    new_kinds = {"access_code", "individualized_access_link", "hash_config_secret"}
    assert [f.kind for f in scan_secrets(text) if f.kind in new_kinds] == []


def test_full_hash_config_response_is_blocked_by_the_audit(tmp_path, monkeypatch):
    root = tmp_path / "consumer"
    root.mkdir()
    (root / "wiki.config.yaml").write_text("audit: {}\n", encoding="utf-8")
    response = ('{"signIn": {"hashConfig": {"algorithm": "SCRYPT", "signerKey": "' + SIGNER
                + '", "saltSeparator": "' + SALT + '", "rounds": 8, "memoryCost": 14}}}\n')
    (root / "notes.md").write_text("# Synthetic\n\nSee verification code " + CODE + ".\n", encoding="utf-8")
    (root / "response.json").write_text(response, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    monkeypatch.setattr(audit, "ROOT", root)
    audit._audit_git_inventory.cache_clear()
    audit.tracked_files.cache_clear()
    try:
        errors: list[str] = []
        audit.audit_secrets(errors, load_config(root))
    finally:
        audit._audit_git_inventory.cache_clear()
        audit.tracked_files.cache_clear()
    assert any(e.startswith("notes.md:3: possible access_code secret") for e in errors)
    assert sum("hash_config_secret" in e for e in errors) == 2
    joined = "\n".join(errors)
    assert SIGNER not in joined and CODE not in joined and SALT not in joined
