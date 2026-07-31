from datetime import timedelta

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.legal import record_current_legal_acceptance
from apps.accounts.models import LegalAcceptance, PrivacyRequest, Session, User


@pytest.mark.django_db
def test_legal_pages_are_public_and_offer_deployed_source(client):
    for name in ("legal:terms", "legal:privacy", "legal:open_source"):
        response = client.get(reverse(name))
        assert response.status_code == 200

    source_response = client.get(reverse("legal:open_source"))
    assert settings.RUANG_DEPLOYED_SOURCE_URL.encode() in source_response.content
    assert b"AGPL" in source_response.content


@pytest.mark.django_db
def test_current_versions_are_required_and_acceptance_is_audited(client):
    user = User.objects.create_user(email="legal@example.com", password="pw")
    client.force_login(user)

    response = client.get("/")
    assert response.status_code == 302
    assert response.url == reverse("accounts:accept_terms")

    response = client.post(reverse("accounts:accept_terms"), {"agree_terms": "on"})
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.tos_accepted_at is None

    response = client.post(
        reverse("accounts:accept_terms"),
        {"agree_terms": "on", "agree_privacy": "on"},
    )
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.tos_version == settings.RUANG_TERMS_VERSION
    assert user.privacy_version == settings.RUANG_PRIVACY_VERSION

    acceptance = LegalAcceptance.objects.get(user=user)
    assert acceptance.source == "web"
    assert acceptance.source_revision == settings.RUANG_SOURCE_CODE_REVISION
    assert acceptance.terms_url == settings.RUANG_TERMS_URL
    assert acceptance.privacy_url == settings.RUANG_PRIVACY_URL
    assert len(acceptance.subject_id_hash) == 64


@pytest.mark.django_db
def test_version_change_forces_reacceptance(client, settings):
    user = User.objects.create_user(
        email="version@example.com",
        password="pw",
        tos_accepted_at=timezone.now(),
    )
    client.force_login(user)
    settings.RUANG_TERMS_VERSION = "2099-01-01"

    response = client.get("/")
    assert response.status_code == 302
    assert response.url == reverse("accounts:accept_terms")


@pytest.mark.django_db
def test_account_export_excludes_session_token_hash(client):
    user = User.objects.create_user(
        email="export@example.com",
        password="pw",
        tos_accepted_at=timezone.now(),
    )
    Session.objects.create(
        user=user,
        token_hash="a" * 64,
        device_info="Browser",
        ip_address="127.0.0.1",
        expires_at=timezone.now() + timedelta(days=1),
    )
    record_current_legal_acceptance(user, source="test")
    client.force_login(user)

    response = client.get(reverse("accounts:data_export"))
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store, private"
    assert "attachment" in response["Content-Disposition"]
    assert b"token_hash" not in response.content
    assert ("a" * 64).encode() not in response.content
    assert response.json()["profile"]["email"] == user.email


@pytest.mark.django_db
def test_privacy_request_is_recorded(client):
    user = User.objects.create_user(
        email="privacy@example.com",
        password="pw",
        tos_accepted_at=timezone.now(),
    )
    client.force_login(user)

    response = client.post(
        reverse("accounts:settings"),
        {
            "action": "privacy_request",
            "request_type": PrivacyRequest.RequestType.ACCESS,
            "details": "Please include workspace content.",
        },
    )
    assert response.status_code == 302
    privacy_request = PrivacyRequest.objects.get(user=user)
    assert privacy_request.requester_email == user.email
    assert privacy_request.status == PrivacyRequest.Status.SUBMITTED
    assert len(privacy_request.subject_id_hash) == 64


@pytest.mark.django_db
def test_legal_evidence_is_pseudonymized_after_user_deletion():
    user = User.objects.create_user(email="delete@example.com", password="pw")
    acceptance = record_current_legal_acceptance(user, source="test")
    acceptance_id = acceptance.pk
    subject_hash = acceptance.subject_id_hash

    user.delete()

    acceptance = LegalAcceptance.objects.get(pk=acceptance_id)
    assert acceptance.user is None
    assert acceptance.subject_id_hash == subject_hash
