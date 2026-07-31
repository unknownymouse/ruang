from __future__ import annotations

import logging

from background_task import background

from .models import Campaign, MediaGenerationJob
from .services.media import MediaProviderError, process_media_job
from .services.orchestration import generate_campaign

logger = logging.getLogger(__name__)


@background(schedule=0)
def generate_campaign_task(campaign_id: str, actor_id: str | None = None):
    campaign = Campaign.objects.select_related("workspace").get(pk=campaign_id)
    actor = None
    if actor_id:
        from apps.accounts.models import User

        actor = User.objects.filter(pk=actor_id).first()
    try:
        generate_campaign(campaign, actor=actor)
    except Exception:
        logger.exception("AI campaign generation failed for %s", campaign_id)


@background(schedule=0)
def process_media_job_task(job_id: str):
    job = MediaGenerationJob.objects.select_related("content_draft__campaign").get(pk=job_id)
    try:
        process_media_job(job)
    except MediaProviderError as exc:
        job.retry_count += 1
        job.last_error = str(exc)[:4000]
        if job.retry_count >= job.max_retries:
            job.status = MediaGenerationJob.Status.FAILED
        else:
            job.status = MediaGenerationJob.Status.QUEUED
        job.save(update_fields=["retry_count", "last_error", "status", "updated_at"])
        if job.status == MediaGenerationJob.Status.QUEUED:
            process_media_job_task(str(job.id), schedule=2**job.retry_count * 60)
