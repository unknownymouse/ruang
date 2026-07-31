from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.common.managers import WorkspaceScopedManager


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
