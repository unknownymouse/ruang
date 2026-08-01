from django.contrib import admin

from .models import (
    AIProviderAuditLog,
    AIUsageEvent,
    AutomationAuditLog,
    BrandBrain,
    Campaign,
    ContentDraft,
    MediaGenerationJob,
    PromptTemplate,
)


@admin.register(BrandBrain)
class BrandBrainAdmin(admin.ModelAdmin):
    list_display = ("workspace", "default_language", "monthly_token_limit", "monthly_cost_limit_usd", "updated_at")
    search_fields = ("workspace__name", "tone", "persona")


@admin.register(PromptTemplate)
class PromptTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "key", "version", "status", "created_at")
    list_filter = ("status", "key")


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "status", "provider", "start_date", "end_date", "created_at")
    list_filter = ("status", "provider")


@admin.register(ContentDraft)
class ContentDraftAdmin(admin.ModelAdmin):
    list_display = ("campaign", "platform", "status", "moderation_status", "scheduled_for")
    list_filter = ("platform", "status", "moderation_status")


@admin.register(MediaGenerationJob)
class MediaGenerationJobAdmin(admin.ModelAdmin):
    list_display = ("content_draft", "kind", "provider", "status", "retry_count", "updated_at")
    list_filter = ("kind", "provider", "status")


@admin.register(AIUsageEvent)
class AIUsageEventAdmin(admin.ModelAdmin):
    list_display = ("workspace", "operation", "provider", "status", "estimated_cost_usd", "created_at")
    list_filter = ("provider", "status", "operation")
    readonly_fields = [field.name for field in AIUsageEvent._meta.fields]


@admin.register(AutomationAuditLog)
class AutomationAuditLogAdmin(admin.ModelAdmin):
    list_display = ("workspace", "action", "object_type", "object_id", "actor", "created_at")
    list_filter = ("action", "object_type")
    readonly_fields = [field.name for field in AutomationAuditLog._meta.fields]

@admin.register(AIProviderAuditLog)
class AIProviderAuditLogAdmin(admin.ModelAdmin):
    list_display = ("organization", "provider", "action", "actor", "created_at")
    list_filter = ("provider", "action")
    readonly_fields = [field.name for field in AIProviderAuditLog._meta.fields]
