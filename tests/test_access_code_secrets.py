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
    # Review of #528: all-zero and uppercase-only codes are issued codes too.
    ("otp: ", "000" + "000", "", "access_code"),
    ("Your verification code is ", "000" + "000", "", "access_code"),
    ("invite_code: ", "ABC" + "DEF", "", "access_code"),
    ("INVITE_CODE=", "QKZ" + "TWM", "", "access_code"),
    ('{"pairingPin": "', "00" + "00", '"}', "access_code"),
    ("verification_code = ", "ABC" + "-DEF", "", "access_code"),
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
    "otp: enabled",
    "mfa_code: totp",
    "verification_code: required",
    "invite_code: TBD",
    "invite_code: ****",
    "Verification code: NOT RECEIVED",
    # Round-2 review of #528: typical .env.example and configuration lines.
    "INVITE_CODE=" + "CHANGE_ME",
    "INVITE_CODE=" + "YOUR_CODE_HERE",
    "OTP=" + "REPLACE_ME",
    "invite_code: " + "INVITE_CODE",
    "otp: " + "TOTP",
    "mfa_code: " + "HOTP",
    "mfa_key: " + "YUBIKEY",
    # Round 3 (automated review): numbered identifiers are names, not codes.
    "INVITE_CODE=" + "INVITE_CODE_V2",
    "OTP=" + "OTP_CODE_1",
    "otp: " + "otp_code_2",
    "invite_code: " + "invite_code_v2",
    "VERIFICATION_CODE=" + "CHANGE_ME_2",
    "PAIRING_PIN=" + "YOUR_PIN_1234",
    "Verification code: " + "OTP_CODE_1",
]

# Real codes stay detected next to the identifier rule (round 3).
REAL_CODES = [
    ("INVITE_CODE=", "X7K2" + "Q9"),
    ("otp: ", "4829" + "13"),
    ("invite_code: ", "AB-12" + "-CD"),
    ("verification_code=", "1234" + "_5678"),
    ("INVITE_CODE=", "Ab3k" + "_Z9qL"),
    ("Your verification code is ", "A1B2" + "C3"),
]

# What the identifier rule lets through, on purpose: a code that starts with a
# letter, contains "_" and has letters of one case reads as an identifier.
IDENTIFIER_SHAPED_CODES = [
    ("invite_code: ", "AB_12" + "CD"),
    ("otp: ", "k7_x9" + "q2"),
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


@pytest.mark.parametrize(("prefix", "value"), REAL_CODES)
def test_real_codes_stay_detected_next_to_identifiers(prefix, value):
    findings = [f for f in scan_secrets(prefix + value) if f.kind == "access_code"]
    assert findings and all(value not in f.excerpt for f in findings)


@pytest.mark.parametrize(("prefix", "value"), IDENTIFIER_SHAPED_CODES)
def test_identifier_shaped_codes_are_a_documented_blind_spot(prefix, value):
    assert [f for f in scan_secrets(prefix + value) if f.kind == "access_code"] == []
