from django.test import override_settings

from apps.common.checks import legal_deployment_checks

VALID_SETTINGS = {
    "SECRET_KEY": "secret-key-that-is-not-the-audit-key",
    "RUANG_LEGAL_ENTITY_NAME": "PT Ruang Aman Indonesia",
    "RUANG_LEGAL_ENTITY_ADDRESS": "Jalan Legal 1, Jakarta",
    "RUANG_SUPPORT_EMAIL": "support@ruang.id",
    "RUANG_PRIVACY_EMAIL": "privacy@ruang.id",
    "RUANG_TERMS_URL": "https://ruang.id/legal/terms/",
    "RUANG_PRIVACY_URL": "https://ruang.id/legal/privacy/",
    "RUANG_SOURCE_CODE_URL": "https://github.com/unknownymouse/ruang",
    "RUANG_SOURCE_CODE_REVISION": "a" * 40,
    "RUANG_DEPLOYED_SOURCE_URL": f"https://github.com/unknownymouse/ruang/tree/{'a' * 40}",
    "RUANG_TERMS_VERSION": "2026-07-31",
    "RUANG_PRIVACY_VERSION": "2026-07-31",
    "RUANG_LEGAL_EFFECTIVE_DATE": "31 Juli 2026",
    "RUANG_PRIVACY_AUDIT_KEY": "audit-key-that-remains-stable-for-years",
    "RUANG_SUBPROCESSORS": [],
    "RUANG_AI_PROVIDERS": ["demo"],
    "RUANG_MEDIA_WEBHOOK_URL": "",
    "INTELLIGENCE_ENABLED": False,
    "RUANG_ACCOUNT_RECORD_RETENTION_DAYS": 1825,
    "RUANG_SECURITY_LOG_RETENTION_DAYS": 180,
    "RUANG_BACKUP_RETENTION_DAYS": 30,
}


@override_settings(**VALID_SETTINGS)
def test_valid_production_legal_configuration_passes():
    assert legal_deployment_checks(None) == []


@override_settings(
    **{
        **VALID_SETTINGS,
        "RUANG_LEGAL_ENTITY_NAME": "Ruang Development Operator",
        "RUANG_SOURCE_CODE_REVISION": "development",
    }
)
def test_placeholders_and_non_commit_revision_fail():
    ids = {error.id for error in legal_deployment_checks(None)}
    assert "ruang.E001" in ids
    assert "ruang.E006" in ids


@override_settings(
    **{
        **VALID_SETTINGS,
        "RUANG_AI_PROVIDERS": ["openai"],
        "RUANG_SUBPROCESSORS": [],
    }
)
def test_external_ai_requires_subprocessor_disclosure():
    ids = {error.id for error in legal_deployment_checks(None)}
    assert "ruang.E011" in ids


@override_settings(
    **{
        **VALID_SETTINGS,
        "RUANG_TERMS_URL": "https://example.com/legal/terms/",
        "RUANG_PRIVACY_URL": "https://yourdomain.invalid/legal/privacy/",
        "RUANG_SOURCE_CODE_REVISION": "abcdef1",
        "RUANG_DEPLOYED_SOURCE_URL": "https://github.com/unknownymouse/ruang/tree/abcdef1",
    }
)
def test_placeholder_urls_and_short_revision_fail():
    ids = {error.id for error in legal_deployment_checks(None)}
    assert "ruang.E003" in ids
    assert "ruang.E006" in ids


@override_settings(
    **{
        **VALID_SETTINGS,
        "RUANG_DEPLOYED_SOURCE_URL": "https://github.com/unknownymouse/ruang/tree/deadbeef",
    }
)
def test_deployed_source_url_must_include_exact_revision():
    ids = {error.id for error in legal_deployment_checks(None)}
    assert "ruang.E013" in ids
