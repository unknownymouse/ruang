from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.ai_automation.models import AIUsageEvent, BrandBrain, Campaign, ContentDraft
from apps.ai_automation.services.orchestration import QuotaExceededError, generate_campaign, materialize_campaign
from apps.ai_automation.services.providers import DemoProvider, ProviderRouter
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


@pytest.fixture
def automation_setup(db):
    user = User.objects.create_user(email="ai@ruang.test", password="test")
    organization = Organization.objects.create(name="Ruang")
    workspace = Workspace.objects.create(
        organization=organization,
        name="Main",
        timezone="Asia/Jakarta",
    )
    account = SocialAccount.objects.create(
        workspace=workspace,
        platform="instagram",
        account_platform_id="ig-1",
        account_name="Ruang",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    campaign = Campaign.objects.create(
        workspace=workspace,
        created_by=user,
        name="Launch",
        brief="Peluncuran produk baru untuk UMKM.",
        objective="Meningkatkan qualified awareness.",
        target_audience="Founder UMKM",
        platforms=["instagram"],
        cadence_per_week=3,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=14),
    )
    return user, workspace, account, campaign


@pytest.mark.django_db
def test_demo_generation_creates_platform_native_drafts_and_usage(automation_setup):
    user, workspace, account, campaign = automation_setup

    generate_campaign(
        campaign,
        actor=user,
        router=ProviderRouter([DemoProvider()]),
    )

    campaign.refresh_from_db()
    drafts = list(campaign.content_drafts.all())
    assert campaign.status == Campaign.Status.PENDING_APPROVAL
    assert campaign.provider == "demo"
    assert campaign.strategy["pillars"]
    assert drafts
    assert all(draft.platform == "instagram" for draft in drafts)
    assert all(draft.social_account_id == account.id for draft in drafts)
    assert all(len(draft.caption_variants) == 3 for draft in drafts)
    assert all(draft.caption not in draft.caption_variants for draft in drafts)
    assert AIUsageEvent.objects.filter(
        workspace=workspace,
        operation="campaign.generate",
        status=AIUsageEvent.Status.SUCCEEDED,
    ).exists()


@pytest.mark.django_db
def test_human_approval_materializes_only_safe_composer_drafts(automation_setup):
    user, _workspace, _account, campaign = automation_setup
    generate_campaign(campaign, actor=user, router=ProviderRouter([DemoProvider()]))

    created, missing = materialize_campaign(campaign, user)

    campaign.refresh_from_db()
    first = campaign.content_drafts.select_related("post").first()
    assert created > 0
    assert missing == 0
    assert campaign.status == Campaign.Status.MATERIALIZED
    assert first is not None
    assert first.status == ContentDraft.Status.MATERIALIZED
    assert first.post is not None
    assert first.post.status == "draft"
    assert first.post.scheduled_at is None
    assert first.post.proposed_publish_at is not None


@pytest.mark.django_db
def test_brand_forbidden_topic_blocks_materialization(automation_setup):
    user, workspace, _account, campaign = automation_setup
    brain = BrandBrain.objects.create(
        workspace=workspace,
        forbidden_topics=["produk baru"],
    )
    generate_campaign(campaign, actor=user, router=ProviderRouter([DemoProvider()]))

    assert campaign.content_drafts.filter(
        moderation_status=ContentDraft.ModerationStatus.FLAGGED,
    ).exists()
    with pytest.raises(ValueError, match="moderation"):
        materialize_campaign(campaign, user)

    brain.delete()


@pytest.mark.django_db
def test_monthly_token_quota_is_enforced_before_provider_call(automation_setup):
    user, workspace, _account, campaign = automation_setup
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
        created_at=timezone.now(),
    )

    with pytest.raises(QuotaExceededError):
        generate_campaign(campaign, actor=user, router=ProviderRouter([DemoProvider()]))
