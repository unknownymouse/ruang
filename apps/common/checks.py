import re
from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, register
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


def _error(message, hint, error_id):
    return Error(message, hint=hint, id=error_id)


def _valid_public_https_url(value):
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and bool(hostname)
        and not parsed.username
        and not parsed.password
        and hostname not in {"localhost", "127.0.0.1", "::1", "example.com"}
        and "yourdomain" not in hostname
        and not hostname.endswith((".localhost", ".test", ".invalid", ".example", ".example.com"))
    )


@register(Tags.security, deploy=True)
def legal_deployment_checks(app_configs, **kwargs):
    """Fail production deployment when the legal baseline is still a placeholder."""
    errors = []
    placeholders = ("development operator", "set operator", "yourdomain", "example.com")

    for setting_name, label in (
        ("RUANG_LEGAL_ENTITY_NAME", "legal entity name"),
        ("RUANG_LEGAL_ENTITY_ADDRESS", "legal entity address"),
    ):
        value = str(getattr(settings, setting_name, "")).strip()
        if not value or any(token in value.lower() for token in placeholders):
            errors.append(
                _error(
                    f"Ruang {label} is missing or still a placeholder.",
                    f"Set {setting_name} to the operator's verified public identity.",
                    "ruang.E001",
                )
            )

    for setting_name in ("RUANG_SUPPORT_EMAIL", "RUANG_PRIVACY_EMAIL"):
        value = str(getattr(settings, setting_name, "")).strip()
        try:
            validate_email(value)
            email_placeholder = "yourdomain" in value.lower() or value.lower().endswith("@example.com")
        except ValidationError:
            email_placeholder = True
        if email_placeholder:
            errors.append(
                _error(
                    f"{setting_name} is not a valid public contact email.",
                    f"Set {setting_name} to a monitored mailbox on the production domain.",
                    "ruang.E002",
                )
            )

    for setting_name in (
        "RUANG_TERMS_URL",
        "RUANG_PRIVACY_URL",
        "RUANG_SOURCE_CODE_URL",
        "RUANG_DEPLOYED_SOURCE_URL",
    ):
        value = str(getattr(settings, setting_name, "")).strip()
        if not _valid_public_https_url(value):
            errors.append(
                _error(
                    f"{setting_name} must be a public HTTPS URL.",
                    "Use the production origin; localhost and example domains are rejected.",
                    "ruang.E003",
                )
            )

    for setting_name in ("RUANG_TERMS_VERSION", "RUANG_PRIVACY_VERSION"):
        value = str(getattr(settings, setting_name, "")).strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:\.\d+)?", value):
            errors.append(
                _error(
                    f"{setting_name} must be a version such as 2026-07-31 or 2026-07-31.1.",
                    "Increase the version whenever the corresponding document materially changes.",
                    "ruang.E004",
                )
            )

    if not str(getattr(settings, "RUANG_LEGAL_EFFECTIVE_DATE", "")).strip():
        errors.append(
            _error(
                "RUANG_LEGAL_EFFECTIVE_DATE is required.",
                "Publish the effective date shown in Terms and Privacy.",
                "ruang.E005",
            )
        )

    revision = str(getattr(settings, "RUANG_SOURCE_CODE_REVISION", "")).strip()
    if not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", revision):
        errors.append(
            _error(
                "RUANG_SOURCE_CODE_REVISION must identify the exact deployed Git commit.",
                "Set it to the output of: git rev-parse HEAD",
                "ruang.E006",
            )
        )
    elif revision.lower() not in str(settings.RUANG_DEPLOYED_SOURCE_URL).lower():
        errors.append(
            _error(
                "RUANG_DEPLOYED_SOURCE_URL does not identify the configured deployed revision.",
                "Use a public commit/tree/archive URL containing RUANG_SOURCE_CODE_REVISION.",
                "ruang.E013",
            )
        )

    audit_key = str(getattr(settings, "RUANG_PRIVACY_AUDIT_KEY", ""))
    if len(audit_key) < 32 or audit_key == settings.SECRET_KEY:
        errors.append(
            _error(
                "RUANG_PRIVACY_AUDIT_KEY must be a separate stable secret of at least 32 characters.",
                "Generate it once, store it in the secret manager, and do not rotate it without a migration plan.",
                "ruang.E007",
            )
        )

    subprocessors = getattr(settings, "RUANG_SUBPROCESSORS", [])
    if not isinstance(subprocessors, list):
        errors.append(
            _error(
                "RUANG_SUBPROCESSORS_JSON must be a JSON array.",
                "Each entry needs name, purpose, privacy_url, and location.",
                "ruang.E008",
            )
        )
        subprocessors = []

    for index, item in enumerate(subprocessors):
        if not isinstance(item, dict):
            errors.append(
                _error(
                    f"Subprocessor entry {index + 1} is not an object.",
                    "Use keys: name, purpose, privacy_url, location.",
                    "ruang.E009",
                )
            )
            continue
        missing = [key for key in ("name", "purpose", "privacy_url", "location") if not item.get(key)]
        if missing or not _valid_public_https_url(str(item.get("privacy_url", ""))):
            errors.append(
                _error(
                    f"Subprocessor entry {index + 1} is incomplete or has a non-HTTPS privacy URL.",
                    "Required keys: name, purpose, privacy_url, location.",
                    "ruang.E010",
                )
            )

    external_ai = {item for item in settings.RUANG_AI_PROVIDERS if item != "demo"}
    if (external_ai or settings.RUANG_MEDIA_WEBHOOK_URL or settings.INTELLIGENCE_ENABLED) and not subprocessors:
        errors.append(
            _error(
                "External AI/media processing is enabled but no subprocessors are disclosed.",
                "Populate RUANG_SUBPROCESSORS_JSON with every applicable provider.",
                "ruang.E011",
            )
        )

    for setting_name in (
        "RUANG_ACCOUNT_RECORD_RETENTION_DAYS",
        "RUANG_SECURITY_LOG_RETENTION_DAYS",
        "RUANG_BACKUP_RETENTION_DAYS",
    ):
        if getattr(settings, setting_name, 0) <= 0:
            errors.append(
                _error(
                    f"{setting_name} must be greater than zero.",
                    "Set and document a retention period aligned with operational and legal needs.",
                    "ruang.E012",
                )
            )

    return errors
