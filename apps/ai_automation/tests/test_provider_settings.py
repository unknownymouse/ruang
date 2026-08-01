from unittest.mock import patch

import httpx
import pytest
from django.db import connection as db_connection
from django.test import Client
from django.urls import reverse

from apps.accounts.legal import record_current_legal_acceptance
from apps.accounts.models import User
from apps.ai_automation.forms import AIProviderConnectionForm
from apps.ai_automation.models import AIProviderAuditLog, AIProviderConnection
from apps.ai_automation.services.providers import (
    AnthropicProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    ProviderError,
    configured_providers,
    provider_from_connection,
)
from apps.ai_automation.services.providers import (
    test_provider_connection as run_provider_connection_test,
)
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


@pytest.fixture
def provider_owner(db):
    user = User.objects.create_user(email="owner-ai@ruang.test", password="test-password")
    record_current_legal_acceptance(user, source="test")
    organization = Organization.objects.create(name="AI Organization")
    OrgMembership.objects.create(
        user=user,
        organization=organization,
        org_role=OrgMembership.OrgRole.OWNER,
    )
    workspace = Workspace.objects.create(organization=organization, name="AI Workspace")
    WorkspaceMembership.objects.create(
        user=user,
        workspace=workspace,
        workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
    )
    client = Client()
    client.force_login(user)
    return client, user, organization


@pytest.mark.django_db
def test_api_key_is_encrypted_at_rest_and_masked(provider_owner):
    _client, user, organization = provider_owner
    connection = AIProviderConnection.objects.create(
        organization=organization,
        provider=AIProviderConnection.Provider.OPENAI,
        api_key="sk-super-secret-value",
        base_url="https://api.openai.com/v1",
        model_name="test-model",
        created_by=user,
        updated_by=user,
    )

    pk_value = connection.id.hex if db_connection.vendor == "sqlite" else connection.id
    with db_connection.cursor() as cursor:
        cursor.execute(
            "SELECT api_key FROM ai_automation_provider_connection WHERE id = %s",
            [pk_value],
        )
        stored_value = cursor.fetchone()[0]

    assert "sk-super-secret-value" not in stored_value
    connection.refresh_from_db()
    assert connection.api_key == "sk-super-secret-value"
    assert connection.masked_api_key == "****alue"


@pytest.mark.django_db
def test_owner_can_open_provider_menu(provider_owner):
    client, _user, organization = provider_owner

    response = client.get(reverse("ai_provider_settings:index", args=[organization.id]))

    assert response.status_code == 200
    assert b"AI Providers" in response.content
    assert b"Connect provider" in response.content


@pytest.mark.django_db
def test_owner_can_connect_provider_from_settings(provider_owner):
    client, user, organization = provider_owner

    response = client.post(
        reverse("ai_provider_settings:index", args=[organization.id]),
        {
            "action": "create",
            "provider": "openai",
            "api_key": "sk-owner-secret",
            "base_url": "",
            "model_name": "provider-model",
            "priority": "10",
            "is_active": "on",
        },
    )

    assert response.status_code == 302, response.content.decode()
    connection = AIProviderConnection.objects.get(organization=organization)
    assert connection.api_key == "sk-owner-secret"
    assert connection.base_url == "https://api.openai.com/v1"
    assert connection.created_by == user
    assert AIProviderAuditLog.objects.filter(
        organization=organization,
        provider="openai",
        action="created",
    ).exists()


@pytest.mark.django_db
def test_blank_key_on_update_keeps_existing_secret(provider_owner):
    client, user, organization = provider_owner
    connection = AIProviderConnection.objects.create(
        organization=organization,
        provider="anthropic",
        api_key="anthropic-secret",
        model_name="old-model",
        created_by=user,
        updated_by=user,
    )

    response = client.post(
        reverse("ai_provider_settings:index", args=[organization.id]),
        {
            "action": "update",
            "connection_id": str(connection.id),
            "provider": "anthropic",
            "api_key": "",
            "base_url": "",
            "model_name": "new-model",
            "priority": "20",
            "is_active": "on",
        },
    )

    assert response.status_code == 302, response.content.decode()
    connection.refresh_from_db()
    assert connection.api_key == "anthropic-secret"
    assert connection.model_name == "new-model"
    assert connection.test_result == AIProviderConnection.TestResult.UNTESTED


@pytest.mark.django_db
def test_regular_org_member_cannot_open_provider_settings(provider_owner):
    _client, _owner, organization = provider_owner
    member = User.objects.create_user(email="member-ai@ruang.test", password="test-password")
    record_current_legal_acceptance(member, source="test")
    OrgMembership.objects.create(
        user=member,
        organization=organization,
        org_role=OrgMembership.OrgRole.MEMBER,
    )
    client = Client()
    client.force_login(member)

    response = client.get(reverse("ai_provider_settings:index", args=[organization.id]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_provider_route_rejects_other_organization(provider_owner):
    client, _user, _organization = provider_owner
    other_organization = Organization.objects.create(name="Other Organization")

    response = client.get(reverse("ai_provider_settings:index", args=[other_organization.id]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_connection_test_updates_status_and_audit(provider_owner):
    client, user, organization = provider_owner
    connection = AIProviderConnection.objects.create(
        organization=organization,
        provider="gemini",
        api_key="gemini-secret",
        model_name="gemini-test",
        created_by=user,
        updated_by=user,
    )

    with patch("apps.ai_automation.provider_views.test_provider_connection"):
        response = client.post(reverse("ai_provider_settings:test", args=[organization.id, connection.id]))

    assert response.status_code == 302, response.content.decode()
    connection.refresh_from_db()
    assert connection.test_result == AIProviderConnection.TestResult.SUCCESS
    assert connection.tested_at is not None
    assert AIProviderAuditLog.objects.filter(
        organization=organization,
        provider="gemini",
        action="tested",
        metadata={"result": "success"},
    ).exists()


@pytest.mark.django_db
def test_database_connections_precede_environment_fallbacks(settings, provider_owner):
    _client, user, organization = provider_owner
    settings.RUANG_AI_PROVIDERS = ["demo"]
    AIProviderConnection.objects.create(
        organization=organization,
        provider="anthropic",
        api_key="anthropic-secret",
        model_name="anthropic-test",
        priority=20,
        created_by=user,
        updated_by=user,
    )
    AIProviderConnection.objects.create(
        organization=organization,
        provider="openai",
        api_key="openai-secret",
        base_url="https://api.openai.com/v1",
        model_name="openai-test",
        priority=10,
        created_by=user,
        updated_by=user,
    )

    providers = configured_providers(organization=organization)

    assert [provider.name for provider in providers] == ["openai", "anthropic", "demo"]


@pytest.mark.django_db
def test_custom_endpoint_accepts_public_http(provider_owner):
    _client, _user, organization = provider_owner
    form = AIProviderConnectionForm(
        {
            "provider": "openai_compatible",
            "api_key": "secret",
            "base_url": "http://31.186.86.47:62003/v1",
            "model_name": "custom-model",
            "priority": "1",
            "is_active": "on",
        },
        organization=organization,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["base_url"] == "http://31.186.86.47:62003/v1"


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.django_db
def test_custom_endpoint_rejects_private_network(provider_owner, scheme):
    _client, _user, organization = provider_owner
    form = AIProviderConnectionForm(
        {
            "provider": "openai_compatible",
            "api_key": "secret",
            "base_url": f"{scheme}://127.0.0.1:11434/v1",
            "model_name": "local-model",
            "priority": "1",
            "is_active": "on",
        },
        organization=organization,
    )

    assert not form.is_valid()
    assert "private-network" in str(form.errors["base_url"])


def test_provider_http_error_does_not_leak_gemini_key():
    request = httpx.Request(
        "POST", "https://generativelanguage.googleapis.com/v1beta/models/test:generateContent?key=secret"
    )
    response = httpx.Response(401, request=request)

    with (
        patch("apps.ai_automation.services.providers.httpx.post", return_value=response),
        pytest.raises(ProviderError) as exc_info,
    ):
        GeminiProvider(api_key="secret", model="test").generate_json(system="system", prompt="prompt")

    assert "secret" not in str(exc_info.value)
    assert "HTTP 401" in str(exc_info.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": [{"message": {"content": [{"type": "text", "text": '{"ok": true}'}]}}]},
        {"choices": [{"message": {"content": {"ok": True}}}]},
        {"result": {"ok": True}},
        {"output_text": '{"ok": true}'},
        {"output": [{"content": [{"type": "output_text", "text": '{"ok": true}'}]}]},
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [{"function": {"arguments": '{"ok": true}'}}],
                    }
                }
            ]
        },
    ],
)
def test_openai_compatible_accepts_common_response_envelopes(payload):
    request = httpx.Request("POST", "https://gateway.example.test/v1/chat/completions")
    response = httpx.Response(
        200,
        request=request,
        json=payload,
        headers={"x-request-id": "request-123"},
    )

    with patch("apps.ai_automation.services.providers.httpx.post", return_value=response):
        result = OpenAICompatibleProvider(
            name="openai_compatible",
            api_key="secret",
            base_url="https://gateway.example.test/v1",
            model="custom-model",
        ).generate_json(system="system", prompt="prompt")

    assert result.data == {"ok": True}
    assert result.request_id == "request-123"


def test_openai_compatible_reports_missing_content_without_leaking_body():
    request = httpx.Request("POST", "https://gateway.example.test/v1/chat/completions")
    response = httpx.Response(
        200,
        request=request,
        json={"id": "response-id", "choices": [{"message": {"role": "assistant"}}]},
    )

    with (
        patch("apps.ai_automation.services.providers.httpx.post", return_value=response),
        pytest.raises(ProviderError, match="missing generated content"),
    ):
        OpenAICompatibleProvider(
            name="openai_compatible",
            api_key="secret",
            base_url="https://gateway.example.test/v1",
            model="custom-model",
        ).generate_json(system="system", prompt="prompt")


@pytest.mark.parametrize(
    ("model_name", "selected_provider", "expected_provider"),
    [
        ("gpt-5.6-luna", "gemini", "openai"),
        ("o3-mini", "anthropic", "openai"),
        ("gemini-2.5-pro", "openai", "gemini"),
        ("gemma-3-27b-it", "anthropic", "gemini"),
        ("claude-sonnet-4-5", "gemini", "anthropic"),
    ],
)
@pytest.mark.django_db
def test_provider_is_auto_detected_for_known_model_families(
    provider_owner,
    model_name,
    selected_provider,
    expected_provider,
):
    _client, _user, organization = provider_owner
    form = AIProviderConnectionForm(
        {
            "provider": selected_provider,
            "api_key": "secret",
            "base_url": "",
            "model_name": model_name,
            "priority": "1",
            "is_active": "on",
        },
        organization=organization,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["provider"] == expected_provider
    assert form.auto_detected_provider == expected_provider


@pytest.mark.django_db
def test_custom_endpoint_auto_selects_openai_compatible_for_any_model(provider_owner):
    _client, _user, organization = provider_owner
    form = AIProviderConnectionForm(
        {
            "provider": "gemini",
            "api_key": "secret",
            "base_url": "http://31.186.86.47:62003/v1",
            "model_name": "gemini-2.5-pro",
            "priority": "1",
            "is_active": "on",
        },
        organization=organization,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["provider"] == "openai_compatible"
    assert form.cleaned_data["base_url"] == "http://31.186.86.47:62003/v1"


@pytest.mark.django_db
def test_saving_existing_mismatch_auto_corrects_provider(provider_owner):
    client, user, organization = provider_owner
    connection = AIProviderConnection.objects.create(
        organization=organization,
        provider="gemini",
        api_key="gateway-secret",
        model_name="gpt-5.6-luna",
        created_by=user,
        updated_by=user,
    )

    response = client.post(
        reverse("ai_provider_settings:index", args=[organization.id]),
        {
            "action": "update",
            "connection_id": str(connection.id),
            "provider": "openai_compatible",
            "api_key": "",
            "base_url": "http://31.186.86.47:62003/v1",
            "model_name": "gpt-5.6-luna",
            "priority": "100",
            "is_active": "on",
        },
    )

    assert response.status_code == 302, response.content.decode()
    connection.refresh_from_db()
    assert connection.provider == "openai_compatible"
    assert connection.base_url == "http://31.186.86.47:62003/v1"
    assert connection.api_key == "gateway-secret"


@pytest.mark.parametrize(
    ("stored_provider", "model_name", "expected_type", "expected_name"),
    [
        ("gemini", "gpt-5.6-luna", OpenAICompatibleProvider, "openai"),
        ("openai", "gemini-2.5-pro", GeminiProvider, "gemini"),
        ("gemini", "claude-sonnet-4-5", AnthropicProvider, "anthropic"),
    ],
)
def test_runtime_router_repairs_stale_provider_labels(
    stored_provider,
    model_name,
    expected_type,
    expected_name,
):
    connection = AIProviderConnection(
        provider=stored_provider,
        api_key="secret",
        base_url="",
        model_name=model_name,
    )

    provider = provider_from_connection(connection)

    assert isinstance(provider, expected_type)
    assert provider.name == expected_name


def test_actual_connection_test_uses_detected_protocol(settings):
    settings.RUANG_OPENAI_BASE_URL = "https://api.openai.com/v1"
    connection = AIProviderConnection(
        provider="gemini",
        api_key="secret",
        base_url="",
        model_name="gpt-5.6-luna",
    )
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        200,
        request=request,
        json={"choices": [{"message": {"content": '{"ok": true}'}}]},
    )

    with patch(
        "apps.ai_automation.services.providers.httpx.post",
        return_value=response,
    ) as post:
        result = run_provider_connection_test(connection)

    assert result.data == {"ok": True}
    assert post.call_args.args[0] == "https://api.openai.com/v1/chat/completions"
    assert "params" not in post.call_args.kwargs


@pytest.mark.django_db
def test_mismatched_connection_render_exposes_auto_routing_controls(provider_owner):
    client, user, organization = provider_owner
    AIProviderConnection.objects.create(
        organization=organization,
        provider="gemini",
        api_key="secret",
        model_name="gpt-5.6-luna",
        created_by=user,
        updated_by=user,
    )

    response = client.get(reverse("ai_provider_settings:index", args=[organization.id]))
    page = response.content.decode()

    assert response.status_code == 200
    assert "Auto-routing notice:" in page
    assert "data-provider-select" in page
    assert "data-model-input" in page
    assert "data-base-url-input" in page
    assert "Test actual connection" in page
    assert "Detects GPT/o-series, Gemini/Gemma, and Claude" in page
