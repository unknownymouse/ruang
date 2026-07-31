from __future__ import annotations

from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.members.decorators import require_permission
from apps.social_accounts.models import SocialAccount

from .models import (
    Campaign,
    ContentDraft,
    MediaGenerationJob,
    PromptTemplate,
)
from .services.orchestration import (
    DEFAULT_CAMPAIGN_PROMPT,
    audit,
    get_active_prompt,
    get_or_create_brand_brain,
    materialize_campaign,
    moderate_text,
    usage_summary,
)
from .services.providers import configured_providers
from .tasks import generate_campaign_task, process_media_job_task


def _campaign_for_workspace(workspace, campaign_id):
    return get_object_or_404(
        Campaign.objects.filter(workspace=workspace).select_related("created_by", "approved_by"),
        pk=campaign_id,
    )


@login_required
@require_GET
def dashboard(request, workspace_id):
    workspace = request.workspace
    brain = get_or_create_brand_brain(workspace)
    campaigns = Campaign.objects.for_workspace(workspace.id).select_related("created_by")[:20]
    accounts = (
        SocialAccount.objects.for_workspace(workspace.id)
        .filter(connection_status=SocialAccount.ConnectionStatus.CONNECTED)
        .order_by("platform", "account_name")
    )
    prompt = get_active_prompt(workspace, request.user)
    usage = usage_summary(workspace)
    provider_names = [provider.name for provider in configured_providers()]
    return render(
        request,
        "ai_automation/dashboard.html",
        {
            "workspace": workspace,
            "brain": brain,
            "campaigns": campaigns,
            "accounts": accounts,
            "prompt": prompt,
            "usage": usage,
            "provider_names": provider_names,
            "default_start": date.today(),
            "default_end": date.today() + timedelta(days=30),
            "can_manage_brand": request.workspace_membership.effective_permissions.get(
                "manage_workspace_settings", False
            ),
            "can_approve": request.workspace_membership.effective_permissions.get("approve_posts", False),
        },
    )


@require_POST
@require_permission("manage_workspace_settings")
def update_brand_brain(request, workspace_id):
    brain = get_or_create_brand_brain(request.workspace)
    brain.tone = request.POST.get("tone", "").strip()
    brain.persona = request.POST.get("persona", "").strip()
    brain.products = _lines(request.POST.get("products", ""))
    brain.audiences = _lines(request.POST.get("audiences", ""))
    brain.guidelines = request.POST.get("guidelines", "").strip()
    brain.forbidden_topics = _lines(request.POST.get("forbidden_topics", ""))
    brain.knowledge_base = request.POST.get("knowledge_base", "").strip()
    brain.traffic_strategy_enabled = request.POST.get("traffic_strategy_enabled") == "on"
    brain.traffic_goals = request.POST.get("traffic_goals", "").strip()
    brain.topic_seeds = _lines(request.POST.get("topic_seeds", ""))
    brain.conversion_actions = request.POST.get("conversion_actions", "").strip()
    brain.default_language = request.POST.get("default_language", "id").strip()[:20] or "id"
    try:
        brain.monthly_token_limit = max(int(request.POST.get("monthly_token_limit") or 0), 1)
        brain.monthly_cost_limit_usd = max(float(request.POST.get("monthly_cost_limit_usd") or 0), 0)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Quota values must be numeric.")
    brain.save()
    audit(request.workspace, request.user, "brand_brain.updated", brain)
    messages.success(request, "Brand Brain berhasil diperbarui.")
    return redirect("automation:dashboard", workspace_id=workspace_id)


@require_POST
@require_permission("manage_workspace_settings")
@transaction.atomic
def create_prompt_version(request, workspace_id):
    key = "campaign-plan"
    latest = (
        PromptTemplate.objects.filter(workspace=request.workspace, key=key)
        .aggregate(version=Max("version"))
        .get("version")
        or 0
    )
    template = request.POST.get("template", "").strip()
    if not template:
        template = DEFAULT_CAMPAIGN_PROMPT
    PromptTemplate.objects.filter(
        workspace=request.workspace,
        key=key,
        status=PromptTemplate.Status.ACTIVE,
    ).update(status=PromptTemplate.Status.ARCHIVED)
    prompt = PromptTemplate.objects.create(
        workspace=request.workspace,
        key=key,
        name="Campaign planner",
        purpose="Brief → strategy → platform-native content calendar",
        template=template,
        version=latest + 1,
        status=PromptTemplate.Status.ACTIVE,
        created_by=request.user,
    )
    audit(request.workspace, request.user, "prompt.activated", prompt, {"version": prompt.version})
    messages.success(request, f"Prompt campaign v{prompt.version} sekarang aktif.")
    return redirect("automation:dashboard", workspace_id=workspace_id)


@require_POST
@require_permission("create_posts")
def create_campaign(request, workspace_id):
    platforms = list(dict.fromkeys(request.POST.getlist("platforms")))
    if not platforms:
        messages.error(request, "Pilih minimal satu channel.")
        return redirect("automation:dashboard", workspace_id=workspace_id)
    try:
        start_date = date.fromisoformat(request.POST.get("start_date", ""))
        end_date = date.fromisoformat(request.POST.get("end_date", ""))
        cadence = min(max(int(request.POST.get("cadence_per_week") or 3), 1), 14)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Invalid campaign dates or cadence.")
    if end_date < start_date:
        messages.error(request, "Tanggal selesai harus sesudah tanggal mulai.")
        return redirect("automation:dashboard", workspace_id=workspace_id)
    valid_platforms = set(
        SocialAccount.objects.for_workspace(request.workspace.id)
        .filter(
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
            platform__in=platforms,
        )
        .values_list("platform", flat=True)
    )
    if not valid_platforms:
        messages.error(request, "Tidak ada akun terhubung untuk channel yang dipilih.")
        return redirect("automation:dashboard", workspace_id=workspace_id)
    campaign = Campaign.objects.create(
        workspace=request.workspace,
        created_by=request.user,
        name=request.POST.get("name", "").strip()[:180] or "Untitled campaign",
        brief=request.POST.get("brief", "").strip(),
        objective=request.POST.get("objective", "").strip()[:500],
        target_audience=request.POST.get("target_audience", "").strip()[:500],
        platforms=sorted(valid_platforms),
        cadence_per_week=cadence,
        start_date=start_date,
        end_date=end_date,
        status=Campaign.Status.GENERATING,
    )
    if not campaign.brief:
        campaign.delete()
        messages.error(request, "Brief kampanye wajib diisi.")
        return redirect("automation:dashboard", workspace_id=workspace_id)
    audit(request.workspace, request.user, "campaign.created", campaign, {"platforms": campaign.platforms})
    generate_campaign_task(str(campaign.id), str(request.user.id))
    messages.success(request, "Kampanye masuk antrean generasi AI. Worker akan memprosesnya.")
    return redirect("automation:campaign_detail", workspace_id=workspace_id, campaign_id=campaign.id)


@login_required
@require_GET
def campaign_detail(request, workspace_id, campaign_id):
    campaign = _campaign_for_workspace(request.workspace, campaign_id)
    drafts = campaign.content_drafts.select_related("social_account", "post").prefetch_related("media_jobs")
    return render(
        request,
        "ai_automation/campaign_detail.html",
        {
            "workspace": request.workspace,
            "campaign": campaign,
            "drafts": drafts,
            "can_approve": request.workspace_membership.effective_permissions.get("approve_posts", False),
            "can_edit": request.workspace_membership.effective_permissions.get("create_posts", False),
        },
    )


@require_POST
@require_permission("create_posts")
def regenerate_campaign(request, workspace_id, campaign_id):
    campaign = _campaign_for_workspace(request.workspace, campaign_id)
    if campaign.content_drafts.filter(post__isnull=False).exists():
        messages.error(request, "Kampanye yang sudah masuk composer tidak dapat dibuat ulang.")
        return redirect("automation:campaign_detail", workspace_id=workspace_id, campaign_id=campaign.id)
    campaign.status = Campaign.Status.GENERATING
    campaign.generation_error = ""
    campaign.save(update_fields=["status", "generation_error", "updated_at"])
    generate_campaign_task(str(campaign.id), str(request.user.id))
    audit(request.workspace, request.user, "campaign.regeneration_queued", campaign)
    messages.success(request, "Regenerasi kampanye masuk antrean.")
    return redirect("automation:campaign_detail", workspace_id=workspace_id, campaign_id=campaign.id)


@require_POST
@require_permission("approve_posts")
def approve_campaign(request, workspace_id, campaign_id):
    campaign = _campaign_for_workspace(request.workspace, campaign_id)
    if campaign.status not in {Campaign.Status.PENDING_APPROVAL, Campaign.Status.APPROVED}:
        messages.error(request, "Kampanye belum siap untuk disetujui.")
        return redirect("automation:campaign_detail", workspace_id=workspace_id, campaign_id=campaign.id)
    try:
        created, missing = materialize_campaign(campaign, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        message = f"{created} draft dipindahkan ke composer untuk penjadwalan final."
        if missing:
            message += f" {missing} item menunggu channel terhubung."
        messages.success(request, message)
    return redirect("automation:campaign_detail", workspace_id=workspace_id, campaign_id=campaign.id)


@require_POST
@require_permission("create_posts")
def update_draft(request, workspace_id, draft_id):
    draft = get_object_or_404(
        ContentDraft.objects.select_related("campaign__workspace", "post"),
        pk=draft_id,
        campaign__workspace=request.workspace,
    )
    if draft.post_id:
        messages.error(request, "Edit item ini dari composer karena sudah dimaterialisasi.")
        return redirect(
            "automation:campaign_detail",
            workspace_id=workspace_id,
            campaign_id=draft.campaign_id,
        )
    draft.title = request.POST.get("title", "").strip()[:255]
    draft.caption = request.POST.get("caption", "").strip()
    draft.caption_variants = [
        value.strip() for value in request.POST.get("caption_variants", "").split("\n---\n") if value.strip()
    ][:3]
    draft.visual_prompt = request.POST.get("visual_prompt", "").strip()
    draft.video_script = request.POST.get("video_script", "").strip()
    moderation_text = "\n".join(
        [draft.title, draft.caption, *draft.caption_variants, draft.visual_prompt, draft.video_script]
    )
    brain = get_or_create_brand_brain(request.workspace)
    draft.moderation_status, draft.moderation_reasons = moderate_text(moderation_text, brain)
    draft.status = ContentDraft.Status.PENDING_APPROVAL
    draft.save()
    audit(
        request.workspace,
        request.user,
        "content_draft.updated",
        draft,
        {"moderation_status": draft.moderation_status},
    )
    messages.success(request, "Draft diperbarui dan dimoderasi ulang.")
    return redirect(
        "automation:campaign_detail",
        workspace_id=workspace_id,
        campaign_id=draft.campaign_id,
    )


@require_POST
@require_permission("create_posts")
def queue_media(request, workspace_id, draft_id, kind):
    if kind not in {MediaGenerationJob.Kind.IMAGE, MediaGenerationJob.Kind.VIDEO}:
        return HttpResponseBadRequest("Unsupported media kind.")
    draft = get_object_or_404(
        ContentDraft.objects.select_related("campaign__workspace"),
        pk=draft_id,
        campaign__workspace=request.workspace,
    )
    prompt = draft.visual_prompt if kind == MediaGenerationJob.Kind.IMAGE else draft.video_script
    if not prompt:
        messages.error(request, f"{kind.title()} prompt belum tersedia.")
        return redirect(
            "automation:campaign_detail",
            workspace_id=workspace_id,
            campaign_id=draft.campaign_id,
        )
    job = MediaGenerationJob.objects.create(content_draft=draft, kind=kind, prompt=prompt)
    process_media_job_task(str(job.id))
    audit(request.workspace, request.user, "media_job.queued", job, {"kind": kind})
    messages.success(request, f"Job {kind} masuk antrean pipeline.")
    return redirect(
        "automation:campaign_detail",
        workspace_id=workspace_id,
        campaign_id=draft.campaign_id,
    )


def _lines(value: str) -> list[str]:
    return [line.strip(" \t-•") for line in value.splitlines() if line.strip(" \t-•")]
