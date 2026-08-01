from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from .models import AIProviderConnection


def provider_defaults() -> dict[str, dict[str, str]]:
    return {
        AIProviderConnection.Provider.OPENAI: {
            "base_url": settings.RUANG_OPENAI_BASE_URL,
            "model_name": settings.RUANG_OPENAI_MODEL,
        },
        AIProviderConnection.Provider.ANTHROPIC: {
            "base_url": "",
            "model_name": settings.RUANG_ANTHROPIC_MODEL,
        },
        AIProviderConnection.Provider.GEMINI: {
            "base_url": "",
            "model_name": settings.RUANG_GEMINI_MODEL,
        },
        AIProviderConnection.Provider.OPENAI_COMPATIBLE: {
            "base_url": settings.RUANG_COMPATIBLE_BASE_URL,
            "model_name": settings.RUANG_COMPATIBLE_MODEL,
        },
    }


def validate_public_endpoint(value: str) -> str:
    """Allow public HTTP(S) endpoints while rejecting obvious SSRF targets."""

    candidate = value.strip().rstrip("/")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("Enter a valid HTTP or HTTPS endpoint.") from exc

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError("Custom endpoints must use HTTP or HTTPS.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError("Endpoint URLs cannot contain credentials, query strings, or fragments.")

    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise ValidationError("Local and private-network endpoints are not allowed.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValidationError("Local and private-network endpoints are not allowed.")
    if port is not None and not 1 <= port <= 65535:
        raise ValidationError("Enter a valid endpoint port.")
    return candidate


class AIProviderConnectionForm(forms.ModelForm):
    base_url = forms.URLField(required=False, assume_scheme="https")
    api_key = forms.CharField(
        required=False,
        strip=True,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank while editing to keep the current encrypted key.",
    )
    priority = forms.IntegerField(min_value=1, max_value=1000, initial=100)

    class Meta:
        model = AIProviderConnection
        fields = ["provider", "api_key", "base_url", "model_name", "priority", "is_active"]

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        defaults = provider_defaults()
        if not self.is_bound and not self.instance.pk:
            self.initial.setdefault("priority", 100)
        self.fields["base_url"].required = False
        self.fields["model_name"].required = False
        self.fields["api_key"].widget.attrs.update(
            {
                "autocomplete": "new-password",
                "spellcheck": "false",
            }
        )
        if self.instance.pk:
            self.fields["api_key"].widget.attrs["placeholder"] = self.instance.masked_api_key
        self.provider_defaults = defaults

    def clean_api_key(self) -> str:
        value = self.cleaned_data.get("api_key", "").strip()
        if value:
            return value
        if self.instance.pk:
            return str(self.instance.api_key)
        raise ValidationError("API key is required for a new provider connection.")

    def clean(self):
        cleaned = super().clean()
        provider = cleaned.get("provider")
        if not provider:
            return cleaned

        requested_provider = provider
        selected_defaults = provider_defaults()[requested_provider]
        model_name = str(cleaned.get("model_name") or selected_defaults["model_name"]).strip()
        supplied_base_url = str(cleaned.get("base_url") or "").strip()
        official_openai_url = provider_defaults()[AIProviderConnection.Provider.OPENAI]["base_url"].rstrip("/")
        has_custom_endpoint = bool(supplied_base_url) and (supplied_base_url.rstrip("/") != official_openai_url)

        detected_provider = AIProviderConnection.infer_provider_for_model(model_name)
        if has_custom_endpoint:
            provider = AIProviderConnection.Provider.OPENAI_COMPATIBLE
        elif detected_provider:
            provider = detected_provider
        cleaned["provider"] = provider
        self.auto_detected_provider = provider if provider != requested_provider else ""

        defaults = provider_defaults()[provider]
        if not model_name:
            self.add_error("model_name", "Model name is required.")
        else:
            cleaned["model_name"] = model_name

        if provider == AIProviderConnection.Provider.OPENAI_COMPATIBLE:
            base_url = str(supplied_base_url or defaults["base_url"]).strip()
            if not base_url:
                self.add_error("base_url", "Base URL is required for an OpenAI-compatible provider.")
            else:
                try:
                    cleaned["base_url"] = validate_public_endpoint(base_url)
                except ValidationError as exc:
                    self.add_error("base_url", exc)
        elif provider == AIProviderConnection.Provider.OPENAI:
            cleaned["base_url"] = official_openai_url
        else:
            cleaned["base_url"] = ""

        duplicate = AIProviderConnection.objects.filter(
            organization=self.organization,
            provider=provider,
        )
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            self.add_error("provider", "This provider is already connected for the organization.")
        return cleaned
