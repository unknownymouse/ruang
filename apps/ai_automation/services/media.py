from __future__ import annotations

import httpx
from django.conf import settings

from ..models import MediaGenerationJob


class MediaProviderError(RuntimeError):
    pass


def process_media_job(job: MediaGenerationJob) -> MediaGenerationJob:
    """Send an image/video job to a vendor-neutral generation webhook.

    The webhook contract is deliberately small so operators can route it to
    Fal, Replicate, ComfyUI, Runway, or an internal pipeline:
    POST {kind, prompt, campaign_id, content_draft_id}
    -> {status, provider, external_job_id, output_url, metadata}
    """

    webhook_url = getattr(settings, "RUANG_MEDIA_WEBHOOK_URL", "")
    if not webhook_url:
        job.status = MediaGenerationJob.Status.WAITING_PROVIDER
        job.last_error = "Configure RUANG_MEDIA_WEBHOOK_URL to enable image/video generation."
        job.save(update_fields=["status", "last_error", "updated_at"])
        return job

    job.status = MediaGenerationJob.Status.PROCESSING
    job.save(update_fields=["status", "updated_at"])
    headers = {}
    if settings.RUANG_MEDIA_WEBHOOK_TOKEN:
        headers["Authorization"] = f"Bearer {settings.RUANG_MEDIA_WEBHOOK_TOKEN}"
    try:
        response = httpx.post(
            webhook_url,
            headers=headers,
            json={
                "kind": job.kind,
                "prompt": job.prompt,
                "campaign_id": str(job.content_draft.campaign_id),
                "content_draft_id": str(job.content_draft_id),
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MediaProviderError(str(exc)) from exc

    job.provider = str(payload.get("provider") or "webhook")[:60]
    job.external_job_id = str(payload.get("external_job_id") or "")[:255]
    job.output_url = str(payload.get("output_url") or "")[:2000]
    job.output_metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    provider_status = str(payload.get("status") or "").lower()
    job.status = (
        MediaGenerationJob.Status.READY_FOR_REVIEW
        if job.output_url or provider_status in {"complete", "completed", "ready"}
        else MediaGenerationJob.Status.WAITING_PROVIDER
    )
    job.last_error = ""
    job.save(
        update_fields=[
            "provider",
            "external_job_id",
            "output_url",
            "output_metadata",
            "status",
            "last_error",
            "updated_at",
        ]
    )
    return job
