import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from apps.common.encryption import EncryptedJSONField, EncryptedTextField


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        # An explicit acceptance timestamp means the caller accepted the
        # documents currently deployed. Existing database rows remain blank
        # after migration and are therefore still required to re-accept.
        if extra_fields.get("tos_accepted_at") is not None:
            extra_fields.setdefault("tos_version", settings.RUANG_TERMS_VERSION)
            extra_fields.setdefault("privacy_version", settings.RUANG_PRIVACY_VERSION)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255, blank=True, default="")
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    # 2FA fields
    totp_secret = EncryptedTextField(blank=True, null=True)
    totp_recovery_codes = EncryptedJSONField(blank=True, null=True)
    totp_enabled = models.BooleanField(default=False)

    # Workspace persistence
    last_workspace_id = models.UUIDField(blank=True, null=True)

    # Terms of Service acceptance (null = not yet accepted)
    tos_accepted_at = models.DateTimeField(blank=True, null=True)
    tos_version = models.CharField(max_length=40, blank=True, default="")
    privacy_version = models.CharField(max_length=40, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "accounts_user"

    def __str__(self):
        return self.email

    @property
    def display_name(self):
        if self.name:
            return self.name
        if self.email:
            return self.email.split("@")[0]
        return "User"


class OAuthConnection(models.Model):
    class Provider(models.TextChoices):
        GOOGLE = "google", "Google"
        GITHUB = "github", "GitHub"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="oauth_connections")
    provider = models.CharField(max_length=20, choices=Provider.choices)
    provider_user_id = models.CharField(max_length=255)
    provider_email = models.EmailField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_oauth_connection"
        unique_together = [("provider", "provider_user_id")]

    def __str__(self):
        return f"{self.user.email} - {self.provider}"


class Session(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_sessions")
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    device_info = models.CharField(max_length=500, blank=True, default="")
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    last_active_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "accounts_session"

    def __str__(self):
        return f"Session for {self.user.email}"


class LegalAcceptance(models.Model):
    """Versioned evidence that a user accepted the legal documents.

    The pseudonymous subject hash survives account deletion so the operator can
    retain minimal proof of acceptance without retaining the deleted account's
    email address or UUID.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="legal_acceptances",
        blank=True,
        null=True,
    )
    subject_id_hash = models.CharField(max_length=64, db_index=True)
    terms_version = models.CharField(max_length=40)
    privacy_version = models.CharField(max_length=40)
    source = models.CharField(max_length=32, default="web")
    source_revision = models.CharField(max_length=64)
    terms_url = models.URLField(max_length=500)
    privacy_url = models.URLField(max_length=500)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_legal_acceptance"
        ordering = ("-accepted_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "terms_version", "privacy_version"),
                name="accounts_unique_user_legal_versions",
            )
        ]

    def __str__(self):
        return f"{self.terms_version} / {self.privacy_version} @ {self.accepted_at:%Y-%m-%d}"


class PrivacyRequest(models.Model):
    """Auditable intake for data-subject rights requests."""

    class RequestType(models.TextChoices):
        ACCESS = "access", "Access or comprehensive export"
        CORRECTION = "correction", "Correction"
        RESTRICTION = "restriction", "Restriction of processing"
        OBJECTION = "objection", "Objection to processing"
        WITHDRAW_CONSENT = "withdraw_consent", "Withdraw consent"
        OTHER = "other", "Other privacy request"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="privacy_requests",
        blank=True,
        null=True,
    )
    subject_id_hash = models.CharField(max_length=64, db_index=True)
    requester_email = EncryptedTextField()
    request_type = models.CharField(max_length=32, choices=RequestType.choices)
    details = EncryptedTextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    resolution_notes = EncryptedTextField(blank=True, default="")
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "accounts_privacy_request"
        ordering = ("-submitted_at",)

    def __str__(self):
        return f"{self.get_request_type_display()} ({self.status})"
