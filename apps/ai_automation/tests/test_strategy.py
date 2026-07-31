from types import SimpleNamespace

from apps.ai_automation.services.orchestration import _fit_platform_caption
from apps.ai_automation.services.providers import DemoProvider
from apps.ai_automation.services.strategy import (
    TRAFFIC_STRATEGY_SOURCES,
    build_traffic_playbook,
)


def test_playbook_is_auditable_and_platform_native():
    brain = SimpleNamespace(
        traffic_strategy_enabled=True,
        traffic_goals="Qualified website visits",
        topic_seeds=["social automation", "content workflow"],
        conversion_actions="Visit the campaign landing page",
    )
    playbook = build_traffic_playbook(
        brain,
        ["instagram", "linkedin_company", "x"],
        "x impressions=1200, instagram saves=35",
    )
    assert playbook["enabled"] is True
    assert playbook["traffic_goals"] == "Qualified website visits"
    assert playbook["topic_seeds"] == ["social automation", "content workflow"]
    assert playbook["platform_rules"]["x"]["constraints"][0].startswith("Maximum 280")
    assert playbook["platform_rules"]["instagram"]["role"] != playbook["platform_rules"]["x"]["role"]
    assert playbook["analytics_feedback"].startswith("x impressions")
    assert playbook["sources"] == TRAFFIC_STRATEGY_SOURCES
    assert all(source["url"].startswith("https://") for source in playbook["sources"])


def test_playbook_never_claims_live_trend_data():
    brain = SimpleNamespace(
        traffic_strategy_enabled=True,
        traffic_goals="",
        topic_seeds=[],
        conversion_actions="",
    )
    playbook = build_traffic_playbook(brain, ["tiktok"], "No baseline")
    assert any("never fabricate live trend" in step for step in playbook["method"])
    assert any("hypothesis" in guardrail for guardrail in playbook["guardrails"])


def test_x_caption_is_native_and_never_exceeds_limit():
    fitted = _fit_platform_caption("word " * 100, "x")
    assert len(fitted) <= 280
    assert fitted.endswith("...")

    context = {
        "brief": "Automasi konten untuk tim kecil",
        "objective": "Meningkatkan kunjungan berkualitas",
        "platforms": ["x"],
        "suggested_dates": ["2026-08-01"],
        "start_date": "2026-08-01",
        "analytics_feedback": "No baseline",
        "traffic_playbook": {
            "traffic_goals": "Qualified visits",
            "topic_seeds": ["content workflow"],
            "conversion_actions": "Visit landing page",
            "platform_rules": {"x": {"primary_signals": ["impressions", "clicks"]}},
            "sources": [],
        },
    }
    import json

    result = DemoProvider().generate_json(
        system="test",
        prompt=f"<campaign_context>{json.dumps(context)}</campaign_context>",
    )
    assert len(result.data["items"][0]["caption"]) <= 280
    assert result.data["strategy"]["traffic_objective"] == "Qualified visits"
