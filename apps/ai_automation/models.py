from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.common.encryption import EncryptedTextField
from apps.common.managers import OrgScopedManager, WorkspaceScopedManager


class AIProviderConnection(models.Model):
    """Organization-scoped AI credentials encrypted at rest."""

    class Provider(models.TextChoices):
        OPENAI = "openai", "OpenAI"
        ANTHROPIC = "anthropic", "Anthropic"
        GEMINI = "gemini", "Google Gemini"
        OPENAI_COMPATIBLE = "openai_compatible", "OpenAI-compatible"

    class TestResult(models.TextChoices):
        UNTESTED = "untested", "Untested"
        SUCCESS = "success", "Connected"
        FAILURE = "failure", "Connection failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="ai_provider_connections",
    )
    provider = models.CharField(max_length=32, choices=Provider.choices)
    api_key = EncryptedTextField()
    base_url = models.URLField(max_length=500, blank=True, default="")
    model_name = models.CharField(max_length=200)
    priority = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    test_result = models.CharField(
        max_length=16,
        choices=TestResult.choices,
        default=TestResult.UNTESTED,
    )
    tested_at = models.DateTimeField(blank=True, null=True)
    last_error = models.CharField(max_length=500, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_ai_provider_connections",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_ai_provider_connections",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrgScopedManager()

    class Meta:
        db_table = "ai_automation_provider_connection"
        ordering = ["priority", "provider"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider"],
                name="uniq_ai_provider_per_organization",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "is_active", "priority"],
                name="idx_ai_provider_org_active",
            )
        ]

    def __str__(self) -> str:
        return f"{self.organization.name} - {self.get_provider_display()}"

    @classmethod
    def infer_provider_for_model(cls, model_name: str) -> str:
        """Infer official provider families while allowing unknown gateway models."""

        normalized = str(model_name or "").strip().casefold()
        if (
            normalized.startswith(("gpt-", "chatgpt-", "text-embedding-", "omni-moderation-", "dall-e-"))
            or normalized in {"o1", "o3", "o4"}
            or normalized.startswith(("o1-", "o3-", "o4-"))
        ):
            return cls.Provider.OPENAI
        if normalized.startswith(("gemini-", "models/gemini-", "gemma-", "models/gemma-")):
            return cls.Provider.GEMINI
        if normalized.startswith("claude-"):
            return cls.Provider.ANTHROPIC
        return ""

    @classmethod
    def model_compatibility_error(cls, provider: str, model_name: str) -> str:
        """Return guidance for obvious cross-provider model mismatches."""

        model = str(model_name or "").strip()
        detected = cls.infer_provider_for_model(model)
        if detected and provider not in {detected, cls.Provider.OPENAI_COMPATIBLE}:
            detected_label = dict(cls.Provider.choices)[detected]
            return (
                f'Model "{model}" belongs to {detected_label}, not '
                f"{dict(cls.Provider.choices).get(provider, provider)}. "
                "Save the connection to auto-select the correct provider, or use "
                "OpenAI-compatible with a custom endpoint."
            )
        return ""

    @property
    def compatibility_error(self) -> str:
        return self.model_compatibility_error(self.provider, self.model_name)

    @property
    def masked_api_key(self) -> str:
        value = str(self.api_key or "")
        return f"****{value[-4:]}" if len(value) > 4 else "****"


class AIProviderAuditLog(models.Model):
    """Secret-free audit trail for provider credential lifecycle events."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="ai_provider_audit_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_provider_audit_logs",
    )
    provider = models.CharField(max_length=32)
    action = models.CharField(max_length=40, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ai_automation_provider_audit_log"
        ordering = ["-created_at"]


class BrandBrain(models.Model):
    """The durable brand context injected into every generation request."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="brand_brain",
    )
    tone = models.CharField(max_length=500, blank=True, default="")
    persona = models.TextField(blank=True, default="")
    products = models.JSONField(default=list, blank=True)
    audiences = models.JSONField(default=list, blank=True)
    guidelines = models.TextField(blank=True, default="")
    forbidden_topics = models.JSONField(default=list, blank=True)
    knowledge_base = models.TextField(blank=True, default="")
    traffic_strategy_enabled = models.BooleanField(default=True)
    traffic_goals = models.TextField(blank=True, default="")
    topic_seeds = models.JSONField(default=list, blank=True)
    conversion_actions = models.TextField(blank=True, default="")
    default_language = models.CharField(max_length=20, default="id")
    monthly_token_limit = models.PositiveIntegerField(default=1_000_000)
    monthly_cost_limit_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("50.00"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "ai_automation_brand_brain"

    def __str__(self) -> str:
        return f"Brand Brain · {self.workspace.name}"


class PromptTemplate(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_prompt_templates",
    )
    key = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    purpose = models.TextField(blank=True, default="")
    template = models.TextField()
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_ai_prompt_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "ai_automation_prompt_template"
        ordering = ["key", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "key", "version"],
                name="uniq_ai_prompt_workspace_key_version",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"


class Campaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATING = "generating", "Generating"
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        APPROVED = "approved", "Approved"
        MATERIALIZED = "materialized", "Added to content calendar"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_campaigns",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_ai_campaigns",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_ai_campaigns",
    )
    name = models.CharField(max_length=180)
    brief = models.TextField()
    objective = models.CharField(max_length=500, blank=True, default="")
    target_audience = models.CharField(max_length=500, blank=True, default="")
    platforms = models.JSONField(default=list)
    cadence_per_week = models.PositiveSmallIntegerField(default=3)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    strategy = models.JSONField(default=dict, blank=True)
    strategy_sources = models.JSONField(default=list, blank=True)
    provider = models.CharField(max_length=60, blank=True, default="")
    model_name = models.CharField(max_length=120, blank=True, default="")
    prompt_version = models.PositiveIntegerField(default=0)
    generation_error = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "ai_automation_campaign"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class ContentDraft(models.Model):
    class Status(models.TextChoices):
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        MATERIALIZED = "materialized", "Added to composer"

    class ModerationStatus(models.TextChoices):
        PASSED = "passed", "Passed"
        FLAGGED = "flagged", "Flagged"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="content_drafts")
    social_account = models.ForeignKey(
        "social_accounts.SocialAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_content_drafts",
    )
    post = models.OneToOneField(
        "composer.Post",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_source_draft",
    )
    platform = models.CharField(max_length=40)
    scheduled_for = models.DateTimeField(null=True, blank=True, db_index=True)
    title = models.CharField(max_length=255, blank=True, default="")
    caption = models.TextField()
    caption_variants = models.JSONField(default=list, blank=True)
    visual_prompt = models.TextField(blank=True, default="")
    video_script = models.TextField(blank=True, default="")
    content_pillar = models.CharField(max_length=120, blank=True, default="")
    call_to_action = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING_APPROVAL,
        db_index=True,
    )
    moderation_status = models.CharField(
        max_length=16,
        choices=ModerationStatus.choices,
        default=ModerationStatus.PASSED,
        db_index=True,
    )
    moderation_reasons = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_automation_content_draft"
        ordering = ["scheduled_for", "created_at"]

    def __str__(self) -> str:
        return f"{self.platform} · {self.title or self.caption[:50]}"


class MediaGenerationJob(models.Model):
    class Kind(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        WAITING_PROVIDER = "waiting_provider", "Waiting for provider"
        READY_FOR_REVIEW = "ready_for_review", "Ready for review"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content_draft = models.ForeignKey(ContentDraft, on_delete=models.CASCADE, related_name="media_jobs")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    prompt = models.TextField()
    provider = models.CharField(max_length=60, blank=True, default="")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED, db_index=True)
    external_job_id = models.CharField(max_length=255, blank=True, default="")
    output_url = models.URLField(max_length=2000, blank=True, default="")
    output_metadata = models.JSONField(default=dict, blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    max_retries = models.PositiveSmallIntegerField(default=3)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_automation_media_generation_job"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.kind} · {self.status}"


class AIUsageEvent(models.Model):
    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_usage_events",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_events",
    )
    operation = models.CharField(max_length=80)
    provider = models.CharField(max_length=60)
    model_name = models.CharField(max_length=120, blank=True, default="")
    prompt_version = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("0"))
    latency_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices)
    moderation_status = models.CharField(max_length=20, blank=True, default="")
    input_digest = models.CharField(max_length=64, blank=True, default="")
    error = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ai_automation_usage_event"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "created_at"], name="idx_ai_usage_workspace_date"),
        ]


class AutomationAuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_automation_audit_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_automation_audit_logs",
    )
    action = models.CharField(max_length=80, db_index=True)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ai_automation_audit_log"
        ordering = ["-created_at"]
