from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import LegalAcceptance, OAuthConnection, PrivacyRequest, Session, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "name", "is_active", "is_staff", "created_at")
    list_filter = ("is_active", "is_staff", "totp_enabled")
    search_fields = ("email", "name")
    ordering = ("-created_at",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal info",
            {"fields": ("name", "avatar", "tos_accepted_at", "tos_version", "privacy_version")},
        ),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("2FA", {"fields": ("totp_enabled",)}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)


@admin.register(OAuthConnection)
class OAuthConnectionAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "provider_email", "created_at")
    list_filter = ("provider",)


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("user", "device_info", "ip_address", "last_active_at", "expires_at")
    list_filter = ("created_at",)


@admin.register(LegalAcceptance)
class LegalAcceptanceAdmin(admin.ModelAdmin):
    list_display = ("user", "terms_version", "privacy_version", "source", "accepted_at")
    list_filter = ("terms_version", "privacy_version", "source")
    search_fields = ("subject_id_hash",)
    readonly_fields = (
        "user",
        "subject_id_hash",
        "terms_version",
        "privacy_version",
        "source",
        "source_revision",
        "terms_url",
        "privacy_url",
        "accepted_at",
    )


@admin.register(PrivacyRequest)
class PrivacyRequestAdmin(admin.ModelAdmin):
    list_display = ("request_type", "status", "user", "submitted_at", "completed_at")
    list_filter = ("request_type", "status", "submitted_at")
    search_fields = ("subject_id_hash",)
    readonly_fields = ("user", "subject_id_hash", "requester_email", "request_type", "details", "submitted_at")
