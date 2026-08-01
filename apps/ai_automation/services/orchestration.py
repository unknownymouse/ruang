from __future__ import annotations

import hashlib
import json
import math
import time
import zoneinfo
from datetime import datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal
from typing import Any

from dateutil.parser import isoparse
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.analytics.models import PostInsightsSnapshot
from apps.composer.services import create_post
from apps.social_accounts.models import SocialAccount

from ..models import (
    AIUsageEvent,
    AutomationAuditLog,
    BrandBrain,
    Campaign,
    ContentDraft,
    PromptTemplate,
)
from .providers import AIResult, ProviderError, ProviderRouter
from .strategy import build_traffic_playbook

DEFAULT_CAMPAIGN_PROMPT = """You are Ruang's senior content growth strategist.
Turn the campaign context into a useful, evidence-aware, cross-platform content
calendar. Respect the Brand Brain and traffic_playbook. Treat performance signals
as directional--not causal--and adapt every item to native platform conventions.

Return a single JSON object with:
- strategy: north_star, narrative, pillars (array), channel_roles (object),
  traffic_objective, demand_hypotheses (array), search_intents (array),
  hook_angles (array), distribution_plan (array), conversion_path,
  experiments (array), success_metrics (array), evidence_plan (array),
  source_alignment (array), and optimization_note.
- items: array of objects containing platform, scheduled_for (ISO-8601), title,
  caption, caption_variants (exactly 3), visual_prompt, video_script,
  content_pillar, and call_to_action.

Never invent live trend volume, popularity, statistics, evidence, or testimonials.
Treat supplied trend signals as hypotheses until a human verifies them. Never
schedule outside the campaign date range. Never claim facts absent from the
knowledge base. Do not publish or bypass human approval."""


class QuotaExceededError(RuntimeError):
    pass


def get_or_create_brand_brain(workspace) -> BrandBrain:
    return BrandBrain.objects.get_or_create(
        workspace=workspace,
        defaults={
            "tone": "Jelas, hangat, cerdas, dan tidak berlebihan.",
            "persona": "Partner strategis yang membumi dan membantu audiens mengambil tindakan.",
            "default_language": "id",
            "monthly_token_limit": getattr(settings, "RUANG_AI_MONTHLY_TOKEN_LIMIT", 1_000_000),
            "monthly_cost_limit_usd": getattr(settings, "RUANG_AI_MONTHLY_COST_LIMIT_USD", Decimal("50")),
        },
    )[0]


def get_active_prompt(workspace, actor=None) -> PromptTemplate:
    prompt = (
        PromptTemplate.objects.filter(
            workspace=workspace,
            key="campaign-plan",
            status=PromptTemplate.Status.ACTIVE,
        )
        .order_by("-version")
        .first()
    )
    if prompt:
        return prompt
    return PromptTemplate.objects.create(
        workspace=workspace,
        key="campaign-plan",
        name="Campaign planner",
        purpose="Brief → strategy → platform-native content calendar",
        template=DEFAULT_CAMPAIGN_PROMPT,
        version=1,
        status=PromptTemplate.Status.ACTIVE,
        created_by=actor,
    )


def usage_summary(workspace) -> dict[str, Any]:
    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    totals = AIUsageEvent.objects.filter(workspace=workspace, created_at__gte=start).aggregate(
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        cost=Sum("estimated_cost_usd"),
    )
    input_tokens = int(totals["input_tokens"] or 0)
    output_tokens = int(totals["output_tokens"] or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost": totals["cost"] or Decimal("0"),
    }


def enforce_quota(workspace, brand_brain: BrandBrain) -> None:
    usage = usage_summary(workspace)
    if usage["total_tokens"] >= brand_brain.monthly_token_limit:
        raise QuotaExceededError("Monthly AI token quota has been reached.")
    if usage["cost"] >= brand_brain.monthly_cost_limit_usd:
        raise QuotaExceededError("Monthly AI cost quota has been reached.")


def moderate_text(
    text: str,
    brand_brain: BrandBrain,
) -> tuple[ContentDraft.ModerationStatus, list[str]]:
    normalized = text.casefold()
    reasons = []
    configured = [str(topic).strip() for topic in brand_brain.forbidden_topics if str(topic).strip()]
    for topic in configured:
        if topic.casefold() in normalized:
            reasons.append(f"Forbidden brand topic: {topic}")
    safety_phrases = {
        "instructions for self-harm": "Self-harm instructions",
        "targeted hate speech": "Targeted hate speech",
        "guaranteed financial return": "Unverifiable financial guarantee",
    }
    for phrase, label in safety_phrases.items():
        if phrase in normalized:
            reasons.append(label)
    return (
        (ContentDraft.ModerationStatus.FLAGGED, reasons)
        if reasons
        else (
            ContentDraft.ModerationStatus.PASSED,
            [],
        )
    )


def generate_campaign(campaign: Campaign, actor=None, router: ProviderRouter | None = None) -> Campaign:
    brand_brain = get_or_create_brand_brain(campaign.workspace)
    prompt_version = get_active_prompt(campaign.workspace, actor)
    campaign.status = Campaign.Status.GENERATING
    campaign.generation_error = ""
    campaign.save(update_fields=["status", "generation_error", "updated_at"])

    context = _campaign_context(campaign, brand_brain)
    campaign.strategy_sources = context["traffic_playbook"]["sources"]
    campaign.save(update_fields=["strategy_sources", "updated_at"])
    prompt = (
        f"{prompt_version.template}\n\n"
        f"<campaign_context>{json.dumps(context, ensure_ascii=False, default=str)}</campaign_context>"
    )
    started = time.monotonic()
    try:
        enforce_quota(campaign.workspace, brand_brain)
        result = (router or ProviderRouter(organization=campaign.workspace.organization)).generate_json(
            system="You create brand-safe, evidence-aware, platform-native content plans as strict JSON.",
            prompt=prompt,
        )
        drafts = _validate_and_normalize_items(campaign, result.data)
        latency_ms = int((time.monotonic() - started) * 1000)
        moderation_status = _persist_generation(campaign, drafts, result, prompt_version, brand_brain)
        _record_usage(
            campaign=campaign,
            actor=actor,
            operation="campaign.generate",
            result=result,
            prompt_version=prompt_version.version,
            input_text=prompt,
            latency_ms=latency_ms,
            status=AIUsageEvent.Status.SUCCEEDED,
            moderation_status=moderation_status,
        )
        audit(
            campaign.workspace,
            actor,
            "campaign.generated",
            campaign,
            {
                "provider": result.provider,
                "model": result.model,
                "prompt_version": prompt_version.version,
                "draft_count": len(drafts),
            },
        )
        return campaign
    except (ProviderError, QuotaExceededError, ValueError, TypeError, KeyError) as exc:
        blocked = isinstance(exc, QuotaExceededError)
        campaign.status = Campaign.Status.FAILED
        campaign.generation_error = str(exc)[:4000]
        campaign.save(update_fields=["status", "generation_error", "updated_at"])
        AIUsageEvent.objects.create(
            workspace=campaign.workspace,
            campaign=campaign,
            actor=actor,
            operation="campaign.generate",
            provider="quota" if blocked else "router",
            prompt_version=prompt_version.version,
            latency_ms=int((time.monotonic() - started) * 1000),
            status=AIUsageEvent.Status.BLOCKED if blocked else AIUsageEvent.Status.FAILED,
            input_digest=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            error=str(exc)[:4000],
        )
        action = "campaign.generation_blocked" if blocked else "campaign.generation_failed"
        audit(campaign.workspace, actor, action, campaign, {"error": str(exc)[:500]})
        raise


def _campaign_context(campaign: Campaign, brain: BrandBrain) -> dict[str, Any]:
    total_days = max((campaign.end_date - campaign.start_date).days + 1, 1)
    desired_count = min(max(math.ceil(total_days / 7) * campaign.cadence_per_week, 1), 30)
    spacing = max(total_days / desired_count, 1)
    dates = [
        campaign.start_date + timedelta(days=min(int(index * spacing), total_days - 1))
        for index in range(desired_count)
    ]
    performance = analytics_feedback(campaign.workspace)
    traffic_playbook = build_traffic_playbook(brain, campaign.platforms, performance)
    return {
        "name": campaign.name,
        "brief": campaign.brief,
        "objective": campaign.objective,
        "target_audience": campaign.target_audience,
        "platforms": campaign.platforms,
        "cadence_per_week": campaign.cadence_per_week,
        "start_date": campaign.start_date.isoformat(),
        "end_date": campaign.end_date.isoformat(),
        "suggested_dates": [date.isoformat() for date in dates],
        "brand_brain": {
            "tone": brain.tone,
            "persona": brain.persona,
            "products": brain.products,
            "audiences": brain.audiences,
            "guidelines": brain.guidelines,
            "forbidden_topics": brain.forbidden_topics,
            "knowledge_base": brain.knowledge_base,
            "traffic_goals": brain.traffic_goals,
            "topic_seeds": brain.topic_seeds,
            "conversion_actions": brain.conversion_actions,
            "language": brain.default_language,
        },
        "analytics_feedback": performance,
        "traffic_playbook": traffic_playbook,
    }


def analytics_feedback(workspace) -> str:
    since = timezone.now().date() - timedelta(days=30)
    rows = (
        PostInsightsSnapshot.objects.filter(
            platform_post__post__workspace=workspace,
            date__gte=since,
            metric_key__in=["likes", "comments", "shares", "saves", "views", "impressions"],
        )
        .values("platform_post__social_account__platform", "metric_key")
        .annotate(total=Sum("value"))
        .order_by("-total")[:24]
    )
    if not rows:
        return "No 30-day performance baseline yet. Prioritize learning and format diversity."
    signals = [
        f"{row['platform_post__social_account__platform']} {row['metric_key']}={round(row['total'] or 0)}"
        for row in rows
    ]
    return "30-day directional signals (cumulative, use comparatively): " + ", ".join(signals)


def _validate_and_normalize_items(campaign: Campaign, payload: dict[str, Any]) -> list[dict[str, Any]]:
    strategy = payload.get("strategy")
    items = payload.get("items")
    if not isinstance(strategy, dict) or not isinstance(items, list) or not items:
        raise ValueError("Provider response must include a strategy object and a non-empty items array.")
    normalized = []
    allowed_platforms = set(campaign.platforms)
    for raw in items[:30]:
        if not isinstance(raw, dict):
            continue
        platform = str(raw.get("platform") or "").strip()
        if platform not in allowed_platforms:
            continue
        caption = _fit_platform_caption(raw.get("caption"), platform)
        if not caption:
            continue
        scheduled_for = _parse_schedule(raw.get("scheduled_for"), campaign)
        variants = []
        for value in raw.get("caption_variants") or []:
            variant = _fit_platform_caption(value, platform)
            if variant and variant != caption and variant not in variants:
                variants.append(variant)
        fallbacks = [
            f"{caption}\n\nApa sudut pandangmu?",
            f"{caption}\n\nSimpan untuk dipraktikkan nanti.",
            f"{caption}\n\nBagikan kepada rekan yang membutuhkannya.",
        ]
        for fallback in fallbacks:
            if len(variants) >= 3:
                break
            fallback = _fit_platform_caption(fallback, platform)
            if fallback not in variants:
                variants.append(fallback)
        normalized.append(
            {
                "platform": platform,
                "scheduled_for": scheduled_for,
                "title": str(raw.get("title") or "")[:255],
                "caption": caption,
                "caption_variants": variants[:3],
                "visual_prompt": str(raw.get("visual_prompt") or ""),
                "video_script": str(raw.get("video_script") or ""),
                "content_pillar": str(raw.get("content_pillar") or "")[:120],
                "call_to_action": str(raw.get("call_to_action") or "")[:300],
            }
        )
    if not normalized:
        raise ValueError("Provider response did not contain any valid content items.")
    campaign.strategy = strategy
    return normalized


def _fit_platform_caption(value: Any, platform: str) -> str:
    text = str(value or "").strip()
    limit = SocialAccount.PLATFORM_CHAR_LIMITS.get(platform)
    if not limit or len(text) <= limit:
        return text
    cutoff = max(limit - 3, 1)
    clipped = text[:cutoff].rsplit(" ", 1)[0].rstrip() or text[:cutoff]
    return f"{clipped}..."


def _parse_schedule(value: Any, campaign: Campaign):
    workspace_tz = zoneinfo.ZoneInfo(campaign.workspace.effective_timezone or "UTC")
    try:
        parsed = isoparse(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=workspace_tz)
    except (TypeError, ValueError, OverflowError):
        parsed = datetime.combine(campaign.start_date, dt_time(hour=9), tzinfo=workspace_tz)
    local_date = parsed.astimezone(workspace_tz).date()
    if local_date < campaign.start_date:
        parsed = datetime.combine(campaign.start_date, dt_time(hour=9), tzinfo=workspace_tz)
    elif local_date > campaign.end_date:
        parsed = datetime.combine(campaign.end_date, dt_time(hour=9), tzinfo=workspace_tz)
    return parsed


@transaction.atomic
def _persist_generation(
    campaign: Campaign,
    drafts: list[dict[str, Any]],
    result: AIResult,
    prompt_version: PromptTemplate,
    brain: BrandBrain,
) -> str:
    campaign.content_drafts.filter(post__isnull=True).delete()
    accounts = {
        account.platform: account
        for account in SocialAccount.objects.filter(
            workspace=campaign.workspace,
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
            platform__in=campaign.platforms,
        ).order_by("created_at")
    }
    overall = ContentDraft.ModerationStatus.PASSED
    for draft in drafts:
        moderation_text = "\n".join(
            [
                draft["title"],
                draft["caption"],
                *draft["caption_variants"],
                draft["visual_prompt"],
                draft["video_script"],
            ]
        )
        moderation_status, reasons = moderate_text(moderation_text, brain)
        if moderation_status == ContentDraft.ModerationStatus.FLAGGED:
            overall = moderation_status
        ContentDraft.objects.create(
            campaign=campaign,
            social_account=accounts.get(draft["platform"]),
            platform=draft["platform"],
            scheduled_for=draft["scheduled_for"],
            title=draft["title"],
            caption=draft["caption"],
            caption_variants=draft["caption_variants"],
            visual_prompt=draft["visual_prompt"],
            video_script=draft["video_script"],
            content_pillar=draft["content_pillar"],
            call_to_action=draft["call_to_action"],
            moderation_status=moderation_status,
            moderation_reasons=reasons,
        )
    campaign.status = Campaign.Status.PENDING_APPROVAL
    campaign.provider = result.provider
    campaign.model_name = result.model
    campaign.prompt_version = prompt_version.version
    campaign.generation_error = ""
    campaign.save(
        update_fields=[
            "strategy",
            "strategy_sources",
            "status",
            "provider",
            "model_name",
            "prompt_version",
            "generation_error",
            "updated_at",
        ]
    )
    return overall


@transaction.atomic
def materialize_campaign(campaign: Campaign, actor) -> tuple[int, int]:
    """Approve a campaign and create safe composer drafts with proposed times.

    No generated item is scheduled directly. Existing composer approval and
    scheduling remain the final gate before the publisher can see the item.
    """

    drafts = list(campaign.content_drafts.select_related("social_account", "post"))
    flagged = [draft for draft in drafts if draft.moderation_status == ContentDraft.ModerationStatus.FLAGGED]
    if flagged:
        raise ValueError("Resolve all moderation flags before approval.")
    accounts = {
        account.platform: account
        for account in SocialAccount.objects.filter(
            workspace=campaign.workspace,
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
            platform__in=campaign.platforms,
        ).order_by("created_at")
    }
    created = 0
    missing_accounts = 0
    for draft in drafts:
        if draft.post_id:
            continue
        account = draft.social_account
        if account is None or account.connection_status != SocialAccount.ConnectionStatus.CONNECTED:
            account = accounts.get(draft.platform)
        if account is None:
            missing_accounts += 1
            draft.status = ContentDraft.Status.APPROVED
            draft.save(update_fields=["status", "updated_at"])
            continue
        post = create_post(
            workspace=campaign.workspace,
            social_account=account,
            caption=draft.caption,
            title=draft.title,
            internal_notes=(
                f"Generated by Ruang AI campaign “{campaign.name}”. "
                f"Content pillar: {draft.content_pillar}. Human-approved before composer handoff."
            ),
            proposed_publish_at=draft.scheduled_for,
            author=campaign.created_by or actor,
            status="draft",
            platform_overrides={
                account.id: {
                    "title": draft.title,
                    "caption": draft.caption,
                    "first_comment": None,
                }
            },
        )
        draft.social_account = account
        draft.post = post
        draft.status = ContentDraft.Status.MATERIALIZED
        draft.save(update_fields=["social_account", "post", "status", "updated_at"])
        created += 1
    campaign.approved_by = actor
    campaign.approved_at = timezone.now()
    has_materialized_drafts = created > 0 or any(draft.post_id for draft in drafts)
    if missing_accounts:
        campaign.status = Campaign.Status.PENDING_APPROVAL
    elif has_materialized_drafts:
        campaign.status = Campaign.Status.MATERIALIZED
    else:
        campaign.status = Campaign.Status.APPROVED
    campaign.save(update_fields=["approved_by", "approved_at", "status", "updated_at"])
    audit(
        campaign.workspace,
        actor,
        "campaign.approved",
        campaign,
        {"posts_created": created, "missing_connected_accounts": missing_accounts},
    )
    return created, missing_accounts


def _record_usage(
    *,
    campaign: Campaign,
    actor,
    operation: str,
    result: AIResult,
    prompt_version: int,
    input_text: str,
    latency_ms: int,
    status: str,
    moderation_status: str,
) -> AIUsageEvent:
    cost = estimate_cost(result.model, result.input_tokens, result.output_tokens)
    return AIUsageEvent.objects.create(
        workspace=campaign.workspace,
        campaign=campaign,
        actor=actor,
        operation=operation,
        provider=result.provider,
        model_name=result.model,
        prompt_version=prompt_version,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        estimated_cost_usd=cost,
        latency_ms=latency_ms,
        status=status,
        moderation_status=moderation_status,
        input_digest=hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
        metadata={"request_id": result.request_id},
    )


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Estimate cost from operator-supplied per-million-token prices.

    No vendor price is hard-coded because pricing changes. Configure
    RUANG_AI_COSTS_JSON with {"model": {"input": n, "output": n}}.
    """

    pricing = getattr(settings, "RUANG_AI_COSTS", {}).get(model, {})
    input_rate = Decimal(str(pricing.get("input", 0)))
    output_rate = Decimal(str(pricing.get("output", 0)))
    return ((Decimal(input_tokens) * input_rate) + (Decimal(output_tokens) * output_rate)) / Decimal(1_000_000)


def audit(workspace, actor, action: str, obj, metadata: dict[str, Any] | None = None) -> AutomationAuditLog:
    return AutomationAuditLog.objects.create(
        workspace=workspace,
        actor=actor,
        action=action,
        object_type=obj._meta.label,
        object_id=str(obj.pk),
        metadata=metadata or {},
    )
