"""Tests for the wiki_core.detectors secret/PII/entity module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki_core.detectors import Finding, redact, scan_file, scan_text
from wiki_core.detectors.secrets import scan_secrets
from wiki_core.detectors.sensitive_terms import scan_sensitive_terms

# Sample, non-real credentials used only as fixtures.
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # 4 + 16 chars, matches AKIA[0-9A-Z]{16}
GOOGLE_KEY = "AIza" + "B" * 35
SLACK_TOKEN = "xoxb-" + "123456789012-abcdefghijklmnop"  # split so scanners do not match the fixture
JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ"
    ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
)
PEM_BLOCK = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEpAIBAAKCAQEA1234567890abcdef\n"
    "-----END RSA PRIVATE KEY-----"
)
RANDOM_HEX_32 = "9f8c2a4b7e1d6035a9c8f2e1b4d70c63"  # 32 random hex chars
CPF = "529.982.247-25"
CNPJ = "11.222.333/0001-81"
CPF_BARE = "52998224725"  # same CPF, valid check digits, no punctuation
CNPJ_BARE = "11222333000181"  # same CNPJ, valid check digits, no punctuation
LUHN_CARD = "4111 1111 1111 1111"  # passes Luhn
# 4 + 36 chars matches gh[opsur]_[0-9A-Za-z]{36}; fictitious value.
GITHUB_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
BEARER_TOKEN = "Bearer abcdefABCDEF0123456789xyz"  # 20+ token chars


def _kinds(findings: list[Finding]) -> set[str]:
    return {f.kind for f in findings}


# --------------------------------------------------------------------------- #
# Positive cases
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text, kind",
    [
        (f"key = {AWS_KEY}", "aws_access_key"),
        (f"key = {GOOGLE_KEY}", "google_api_key"),
        (f"token: {SLACK_TOKEN}", "slack_token"),
        (f"auth header {JWT}", "jwt"),
        (PEM_BLOCK, "pem_private_key"),
        (f"token = {GITHUB_TOKEN}", "github_token"),
        (f"Authorization: {BEARER_TOKEN}", "bearer_token"),
    ],
)
def test_secret_positives(text: str, kind: str) -> None:
    assert kind in _kinds(scan_secrets(text))


def test_generic_secret_assignment_high_entropy() -> None:
    text = f'api_key = "{RANDOM_HEX_32}"'
    findings = scan_secrets(text)
    assert "generic_secret_assignment" in _kinds(findings)


def test_cpf_positive() -> None:
    findings = scan_sensitive_terms(f"meu CPF eh {CPF} ok")
    assert "cpf" in _kinds(findings)


def test_cnpj_positive() -> None:
    findings = scan_sensitive_terms(f"CNPJ {CNPJ} registrado")
    assert "cnpj" in _kinds(findings)


def test_credit_card_luhn_valid_positive() -> None:
    findings = scan_sensitive_terms(f"cartao {LUHN_CARD} validade 12/30")
    assert "credit_card" in _kinds(findings)


def test_cpf_bare_valid_positive() -> None:
    findings = scan_sensitive_terms(f"cpf sem pontos {CPF_BARE} no cadastro")
    assert "cpf_sem_pontuacao" in _kinds(findings)


def test_cnpj_bare_valid_positive() -> None:
    findings = scan_sensitive_terms(f"cnpj sem pontos {CNPJ_BARE} na nota")
    assert "cnpj_sem_pontuacao" in _kinds(findings)


def test_scan_text_aggregates_categories() -> None:
    text = f"{AWS_KEY}\n{CPF}\ncontato joao@example.com"
    findings = scan_text(text)
    categories = {f.category for f in findings}
    assert {"secret", "pii", "entity"} <= categories


# --------------------------------------------------------------------------- #
# Negative cases (must NOT fire)
# --------------------------------------------------------------------------- #


def test_luhn_invalid_card_not_reported() -> None:
    # 16 digits that fail the Luhn checksum.
    bad = "1234 5678 9012 3456"
    assert "credit_card" not in _kinds(scan_sensitive_terms(bad))


def test_plain_markdown_number_not_secret() -> None:
    text = "o saldo foi 1234 reais no fim do mes"
    findings = scan_text(text)
    assert findings == []


def test_portuguese_sentence_without_secrets() -> None:
    text = "Hoje revisei a wiki viva e atualizei o status operacional sem pendencias."
    assert scan_text(text) == []


def test_low_entropy_assignment_not_reported() -> None:
    # Word-like value: long enough but low entropy -> should be ignored.
    text = 'password = "aaaaaaaaaaaaaaaaaaaa"'
    assert "generic_secret_assignment" not in _kinds(scan_secrets(text))


def test_cpf_bare_invalid_check_digit_not_reported() -> None:
    # 11 digits, but check digits do not close -> must not fire.
    text = "numero 12345678901 qualquer"
    assert "cpf_sem_pontuacao" not in _kinds(scan_sensitive_terms(text))


def test_phone_number_not_reported_as_cpf() -> None:
    # 11-digit BR phone (DDD + 9 digits) is not a valid CPF -> no finding.
    text = "ligue para 11987654321 hoje"
    assert "cpf_sem_pontuacao" not in _kinds(scan_sensitive_terms(text))


def test_cnpj_bare_invalid_check_digit_not_reported() -> None:
    text = "codigo 12345678901234 interno"
    assert "cnpj_sem_pontuacao" not in _kinds(scan_sensitive_terms(text))


# --------------------------------------------------------------------------- #
# Redaction guarantees (security-critical)
# --------------------------------------------------------------------------- #


def test_excerpt_never_contains_full_aws_key() -> None:
    findings = scan_text(f"aws {AWS_KEY}")
    aws = [f for f in findings if f.kind == "aws_access_key"]
    assert aws, "expected an aws_access_key finding"
    for finding in aws:
        assert AWS_KEY not in finding.excerpt
        assert "*" in finding.excerpt
        assert finding.excerpt.startswith("AKIA")


def test_excerpt_never_contains_full_secret_for_any_finding() -> None:
    raw_secrets = [AWS_KEY, GOOGLE_KEY, SLACK_TOKEN, RANDOM_HEX_32]
    text = (
        f"{AWS_KEY}\n{GOOGLE_KEY}\ntoken: {SLACK_TOKEN}\n"
        f'api_key = "{RANDOM_HEX_32}"\n{CPF}\n{LUHN_CARD}'
    )
    for finding in scan_text(text):
        for secret in raw_secrets:
            assert secret not in finding.excerpt


def test_redact_short_value_fully_masked() -> None:
    assert redact("short") == "*****"
    assert set(redact("12345678")) == {"*"}


def test_redact_keeps_edges() -> None:
    out = redact("AKIAIOSFODNN7EXAMPLE")
    assert out.startswith("AKIA")
    assert out.endswith("MPLE")
    assert "IOSFODNN7EX" not in out


# --------------------------------------------------------------------------- #
# scan_file behaviour
# --------------------------------------------------------------------------- #


def test_scan_file_binary_returns_empty(tmp_path: Path) -> None:
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"AKIA" + b"\x00" + AWS_KEY.encode())
    assert scan_file(binary) == []


def test_scan_file_text(tmp_path: Path) -> None:
    doc = tmp_path / "note.md"
    doc.write_text(f"chave aws {AWS_KEY}\n", encoding="utf-8")
    findings = scan_file(doc)
    assert "aws_access_key" in _kinds(findings)
    assert scan_file(str(doc)) == findings  # accepts str too


def test_line_numbers_are_one_based() -> None:
    text = f"linha um\nlinha dois\n{CPF}"
    findings = scan_sensitive_terms(text)
    cpf = next(f for f in findings if f.kind == "cpf")
    assert cpf.line == 3


# --------------------------------------------------------------------------- #
# Generic detector recall (findings 5,6,7,8 of the critical review)
# --------------------------------------------------------------------------- #

_RND = "9f8c2a4b1d3e5f6a7b8c0d1e2f3a4b5c"  # high entropy, 32 chars


@pytest.mark.parametrize(
    "text",
    [
        f"MY_PASSWORD={_RND}",
        f"db_password={_RND}",
        f"DB_PASSWORD: {_RND}",
        f"POSTGRES_PASSWORD={_RND}",
        f"AWS_SECRET_ACCESS_KEY={_RND}",
    ],
)
def test_generic_assignment_underscore_prefix(text: str) -> None:
    # Finding 5: '\b' next to '_' let the compound identifier escape.
    assert "generic_secret_assignment" in _kinds(scan_secrets(text))


@pytest.mark.parametrize(
    "text",
    [f'"password": "{_RND}"', f"'api_key': '{_RND}'", f'"secret":"{_RND}"'],
)
def test_generic_assignment_quoted_key(text: str) -> None:
    # Finding 6: the key's closing quote broke the match.
    assert "generic_secret_assignment" in _kinds(scan_secrets(text))


def test_provider_keys_detected() -> None:
    # Finding 7: dedicated patterns were missing.
    assert "anthropic_api_key" in _kinds(scan_secrets("sk-ant-api03-" + "b" * 30))
    assert "openai_api_key" in _kinds(scan_secrets("OPENAI=sk-proj-" + "a" * 30))
    assert "stripe_secret_key" in _kinds(scan_secrets("STRIPE=sk_live_" + "c" * 24))


def test_anthropic_not_double_reported_as_openai() -> None:
    kinds = _kinds(scan_secrets("sk-ant-api03-" + "b" * 30))
    assert "anthropic_api_key" in kinds and "openai_api_key" not in kinds


@pytest.mark.parametrize(
    "text",
    [
        "DATABASE_URL=postgres://admin:S3cr3tPass@host/db",
        "mongodb+srv://user:p4ssw0rd@cluster0.mongodb.net",
        "redis://default:abc123def@127.0.0.1:6379",
    ],
)
def test_connection_string_credential(text: str) -> None:
    # Finding 8: a credential embedded in a connection URL escaped detection.
    assert "connection_string_credential" in _kinds(scan_secrets(text))


@pytest.mark.parametrize(
    "text",
    [
        'overlap_tokens = int(config.llm.get("chunk_overlap_tokens", 150))',
        "token_path = /Users/foo/bar/secret_token_file",
        "GOOGLE_APPLICATION_CREDENTIALS_PATH=$HOME/key.json",
        "a metodologia de revisao contextual aplicada ao gate",
        "veja https://example.com/docs e https://drive.google.com/drive/folders/abc",
    ],
)
def test_no_false_positive_on_code_or_prose(text: str) -> None:
    # A credential value is a TOKEN; code/paths/prose/URLs without userinfo do not fire.
    kinds = _kinds(scan_secrets(text))
    assert "generic_secret_assignment" not in kinds
    assert "connection_string_credential" not in kinds


def test_provider_and_generic_excerpts_are_redacted() -> None:
    for text in [f"password={_RND}", "sk-ant-api03-" + "d" * 30]:
        for finding in scan_secrets(text):
            assert _RND not in finding.excerpt
            assert "d" * 30 not in finding.excerpt


def test_dedup_identical_findings() -> None:
    text = f"{CPF} {CPF}"  # same kind, same line, same redacted excerpt
    findings = [f for f in scan_text(text) if f.kind == "cpf"]
    assert len(findings) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
