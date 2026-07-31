from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from apps.accounts.models import User
from apps.ai_automation.models import (
    AIUsageEvent,
    AutomationAuditLog,
    BrandBrain,
    Campaign,
    ContentDraft,
    MediaGenerationJob,
)
from apps.ai_automation.services.media import process_media_job
from apps.ai_automation.services.orchestration import (
    QuotaExceededError,
    generate_campaign,
)
from apps.ai_automation.services.providers import (
    AIResult,
    ProviderError,
    ProviderRouter,
)
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


class FailingProvider:
    def generate_json(self, *, system, prompt):
        del system, prompt
        raise ProviderError("primary unavailable")


class WorkingProvider:
    def generate_json(self, *, system, prompt):
        del system, prompt
        return AIResult(
            data={"strategy": {}, "items": []},
            provider="fallback",
            model="fallback-v1",
        )


def test_provider_router_uses_the_next_configured_provider():
    result = ProviderRouter([FailingProvider(), WorkingProvider()]).generate_json(
        system="system",
        prompt="prompt",
    )

    assert result.provider == "fallback"


@pytest.fixture
def operations_setup(db):
    user = User.objects.create_user(email="ops@ruang.test", password="test")
    organization = Organization.objects.create(name="Ruang Ops")
    workspace = Workspace.objects.create(
        organization=organization,
        name="Operations",
        timezone="Asia/Jakarta",
    )
    campaign = Campaign.objects.create(
        workspace=workspace,
        created_by=user,
        name="Quota campaign",
        brief="Uji operasional AI.",
        platforms=["instagram"],
        start_date=date.today(),
        end_date=date.today() + timedelta(days=7),
    )
    return user, workspace, campaign


@pytest.mark.django_db
def test_quota_block_fails_campaign_and_writes_usage_and_audit(operations_setup):
    user, workspace, campaign = operations_setup
    BrandBrain.objects.create(
        workspace=workspace,
        monthly_token_limit=1,
        monthly_cost_limit_usd=Decimal("99"),
    )
    AIUsageEvent.objects.create(
        workspace=workspace,
        actor=user,
        operation="seed",
        provider="demo",
        input_tokens=1,
        status=AIUsageEvent.Status.SUCCEEDED,
    )

    with pytest.raises(QuotaExceededError):
        generate_campaign(campaign, actor=user, router=ProviderRouter([]))

    campaign.refresh_from_db()
    assert campaign.status == Campaign.Status.FAILED
    assert AIUsageEvent.objects.filter(
        workspace=workspace,
        campaign=campaign,
        provider="quota",
        status=AIUsageEvent.Status.BLOCKED,
    ).exists()
    assert AutomationAuditLog.objects.filter(
        workspace=workspace,
        action="campaign.generation_blocked",
        object_id=str(campaign.id),
    ).exists()


@pytest.mark.django_db
def test_media_webhook_result_waits_for_human_review(settings, operations_setup):
    _user, _workspace, campaign = operations_setup
    draft = ContentDraft.objects.create(
        campaign=campaign,
        platform="instagram",
        caption="Caption aman.",
        visual_prompt="Editorial product photo.",
    )
    job = MediaGenerationJob.objects.create(
        content_draft=draft,
        kind=MediaGenerationJob.Kind.IMAGE,
        prompt=draft.visual_prompt,
    )
    settings.RUANG_MEDIA_WEBHOOK_URL = "https://media.example.test/generate"
    settings.RUANG_MEDIA_WEBHOOK_TOKEN = "test-token"
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "status": "completed",
        "provider": "portable-media",
        "output_url": "https://cdn.example.test/image.png",
        "metadata": {"seed": 42},
    }

    with patch(
        "apps.ai_automation.services.media.httpx.post",
        return_value=response,
    ) as post:
        process_media_job(job)

    job.refresh_from_db()
    assert job.status == MediaGenerationJob.Status.READY_FOR_REVIEW
    assert job.output_url == "https://cdn.example.test/image.png"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"
