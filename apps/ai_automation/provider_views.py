from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from apps.members.models import OrgMembership, has_org_permission

from .forms import AIProviderConnectionForm, provider_defaults
from .models import AIProviderAuditLog, AIProviderConnection
from .services.providers import ProviderError, configured_providers, test_provider_connection


def _managed_organization(request, org_id):
    try:
        membership = OrgMembership.objects.select_related("organization").get(
            user=request.user,
            organization_id=org_id,
        )
    except OrgMembership.DoesNotExist as exc:
        raise PermissionDenied("You are not a member of this organization.") from exc
    if not has_org_permission(membership, "manage_ai_providers"):
        raise PermissionDenied("You cannot manage AI provider connections for this organization.")
    request.org_membership = membership
    request.org = membership.organization
    return membership.organization


def _audit(request, provider: str, action: str, metadata: dict | None = None) -> None:
    AIProviderAuditLog.objects.create(
        organization=request.org,
        actor=request.user,
        provider=provider,
        action=action,
        metadata=metadata or {},
    )


def _form_errors(form: AIProviderConnectionForm) -> str:
    return " ".join(
        f"{field.replace('_', ' ').title()}: {'; '.join(str(error) for error in errors)}"
        for field, errors in form.errors.items()
    )


@login_required
@require_http_methods(["GET", "POST"])
def provider_settings(request, org_id):
    organization = _managed_organization(request, org_id)
    create_form = AIProviderConnectionForm(organization=organization)

    if request.method == "POST":
        action = request.POST.get("action", "create")
        if action == "create":
            create_form = AIProviderConnectionForm(request.POST, organization=organization)
            if create_form.is_valid():
                connection = create_form.save(commit=False)
                connection.organization = organization
                connection.created_by = request.user
                connection.updated_by = request.user
                connection.save()
                _audit(
                    request,
                    connection.provider,
                    "created",
                    {"model": connection.model_name, "priority": connection.priority, "active": connection.is_active},
                )
                route_note = (
                    " Provider was auto-detected from the model and endpoint."
                    if create_form.auto_detected_provider
                    else ""
                )
                messages.success(
                    request,
                    f"{connection.get_provider_display()} was saved and is ready for an actual connection test."
                    + route_note,
                )
                return redirect("ai_provider_settings:index", org_id=organization.id)
            messages.error(request, _form_errors(create_form))
        elif action in {"update", "delete"}:
            connection = get_object_or_404(
                AIProviderConnection.objects.filter(organization=organization),
                pk=request.POST.get("connection_id"),
            )
            if action == "delete":
                provider = connection.provider
                label = connection.get_provider_display()
                connection.delete()
                _audit(request, provider, "deleted")
                messages.success(request, f"{label} connection was removed.")
                return redirect("ai_provider_settings:index", org_id=organization.id)

            form = AIProviderConnectionForm(
                request.POST,
                instance=connection,
                organization=organization,
            )
            if form.is_valid():
                connection = form.save(commit=False)
                connection.updated_by = request.user
                connection.test_result = AIProviderConnection.TestResult.UNTESTED
                connection.tested_at = None
                connection.last_error = ""
                connection.save()
                _audit(
                    request,
                    connection.provider,
                    "updated",
                    {"model": connection.model_name, "priority": connection.priority, "active": connection.is_active},
                )
                route_note = (
                    " Provider was auto-detected from the model and endpoint." if form.auto_detected_provider else ""
                )
                messages.success(
                    request,
                    f"{connection.get_provider_display()} settings were updated." + route_note,
                )
                return redirect("ai_provider_settings:index", org_id=organization.id)
            messages.error(request, _form_errors(form))
        else:
            messages.error(request, "Unsupported provider action.")

    connections = AIProviderConnection.objects.filter(organization=organization).order_by("priority", "provider")
    environment_providers = [provider.name for provider in configured_providers()]
    return render(
        request,
        "ai_automation/provider_settings.html",
        {
            "organization": organization,
            "connections": connections,
            "create_form": create_form,
            "provider_choices": AIProviderConnection.Provider.choices,
            "provider_defaults": provider_defaults(),
            "environment_providers": environment_providers,
            "settings_active": "ai_providers",
        },
    )


@login_required
@require_POST
@ratelimit(key="user", rate="5/m", method="POST", block=True)
def test_connection(request, org_id, connection_id):
    organization = _managed_organization(request, org_id)
    connection = get_object_or_404(
        AIProviderConnection.objects.filter(organization=organization),
        pk=connection_id,
    )
    try:
        test_provider_connection(connection)
    except ProviderError as exc:
        connection.test_result = AIProviderConnection.TestResult.FAILURE
        connection.tested_at = timezone.now()
        connection.last_error = str(exc)[:500]
        connection.save(update_fields=["test_result", "tested_at", "last_error", "updated_at"])
        _audit(request, connection.provider, "tested", {"result": "failure"})
        messages.error(request, f"{connection.get_provider_display()} test failed: {connection.last_error}")
    except Exception:
        connection.test_result = AIProviderConnection.TestResult.FAILURE
        connection.tested_at = timezone.now()
        connection.last_error = "Unexpected provider test failure."
        connection.save(update_fields=["test_result", "tested_at", "last_error", "updated_at"])
        _audit(request, connection.provider, "tested", {"result": "failure"})
        messages.error(request, f"{connection.get_provider_display()} test failed.")
    else:
        connection.test_result = AIProviderConnection.TestResult.SUCCESS
        connection.tested_at = timezone.now()
        connection.last_error = ""
        connection.save(update_fields=["test_result", "tested_at", "last_error", "updated_at"])
        _audit(request, connection.provider, "tested", {"result": "success"})
        messages.success(request, f"{connection.get_provider_display()} connection test passed.")
    return redirect("ai_provider_settings:index", org_id=organization.id)
