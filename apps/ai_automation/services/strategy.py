"""Evidence-aware traffic strategy context for AI campaign generation.

The references in this module are intentionally curated and versioned in code.
Generation never invents live trend numbers: operators may add current trend
signals to the Brand Brain, while this playbook supplies durable principles and
an explicit experiment loop.
"""

from __future__ import annotations

from typing import Any

TRAFFIC_STRATEGY_SOURCES: list[dict[str, str]] = [
    {
        "key": "google-people-first",
        "title": "Google Search Central — Creating helpful, reliable, people-first content",
        "url": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
        "principle": "Prioritize original, useful, trustworthy content made for people; document who, how, and why.",
    },
    {
        "key": "google-trends-method",
        "title": "Google Trends — FAQ about Trends data",
        "url": "https://support.google.com/trends/answer/4365533?hl=en",
        "principle": "Treat Trends as normalized relative interest, compare terms, and avoid interpreting it as polling.",
    },
    {
        "key": "google-trends-related",
        "title": "Google Trends — Find related searches",
        "url": "https://support.google.com/trends/answer/4355000?hl=en",
        "principle": "Use top and rising related searches to form demand hypotheses, then validate before claiming a trend.",
    },
    {
        "key": "tiktok-trends",
        "title": "TikTok Creative Center — How to use Trends",
        "url": "https://ads.tiktok.com/help/article/how-to-use-trends",
        "principle": "Inspect regional trendlines, related videos, hashtags, industries, and audience insights.",
    },
    {
        "key": "linkedin-thought-leadership",
        "title": "LinkedIn — Thought leadership",
        "url": "https://business.linkedin.com/advertise/resources/marketing-terms/thought-leadership",
        "principle": "Lead with an original point of view, audience relevance, expertise, and reusable core ideas.",
    },
    {
        "key": "x-organic",
        "title": "X Business — Organic best practices",
        "url": "https://business.x.com/en/basics/organic-best-practices",
        "principle": "Write concise conversational posts, use a clear CTA and media, and continuously test and learn.",
    },
    {
        "key": "x-analytics",
        "title": "X Business — Post activity dashboard",
        "url": "https://business.x.com/en/help/campaign-measurement-and-analytics/tweet-activity-dashboard",
        "principle": "Learn from impressions, engagement rate, clicks, replies, reposts, and profile actions.",
    },
]


PLATFORM_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "instagram": {
        "role": "Visual discovery, saves, shares, and community trust.",
        "formats": ["carousel how-to", "short-form video", "proof/story", "single visual"],
        "hook": "Make the first frame understandable without audio; earn the swipe or watch in one sentence.",
        "cta": ["save", "share", "comment", "visit profile"],
        "primary_signals": ["reach", "views", "saves", "shares", "comments"],
    },
    "tiktok": {
        "role": "Fast discovery through native short-form video and cultural relevance.",
        "formats": ["problem-solution video", "demonstration", "myth-versus-fact", "response to a real question"],
        "hook": "State a recognizable tension or promised outcome in the first three seconds.",
        "cta": ["watch through", "comment", "share", "follow"],
        "primary_signals": ["views", "engagement", "shares", "comments"],
    },
    "linkedin_personal": {
        "role": "Expert-led thought leadership and professional conversation.",
        "formats": ["original point of view", "operator lesson", "framework", "case evidence"],
        "hook": "Open with a specific observation, consequence, or counterintuitive lesson.",
        "cta": ["reply with experience", "save", "share with team", "visit link"],
        "primary_signals": ["likes", "comments", "shares"],
    },
    "linkedin_company": {
        "role": "Organizational authority, proof, and demand creation.",
        "formats": ["research insight", "customer proof", "product education", "industry perspective"],
        "hook": "Connect an audience problem to an evidence-backed organizational point of view.",
        "cta": ["click", "comment", "follow", "request information"],
        "primary_signals": ["impressions", "clicks", "reposts", "comments", "engagement"],
    },
    "x": {
        "role": "Real-time conversation, concise insight, distribution, and rapid message testing.",
        "formats": ["single insight", "short thread", "visual proof", "question", "timely response"],
        "hook": "Lead with the useful point; keep the language concise, clear, and conversational.",
        "cta": ["reply", "repost", "click", "follow"],
        "primary_signals": ["impressions", "engagement", "clicks", "replies", "reposts"],
        "constraints": ["Maximum 280 characters for a standard post.", "Do not overload the creative with text."],
    },
}

DEFAULT_PLAYBOOK: dict[str, Any] = {
    "role": "Distribute the campaign's core idea in a platform-native format.",
    "formats": ["education", "proof", "conversation", "product relevance"],
    "hook": "Lead with the audience problem or useful outcome.",
    "cta": ["save", "share", "reply", "click"],
    "primary_signals": ["views", "reach", "engagement", "clicks"],
}


def build_traffic_playbook(brain, platforms: list[str], analytics_feedback: str) -> dict[str, Any]:
    """Build deterministic, auditable instructions injected into the AI prompt."""

    source_snapshot = [dict(source) for source in TRAFFIC_STRATEGY_SOURCES]
    platform_rules = {platform: dict(PLATFORM_PLAYBOOKS.get(platform, DEFAULT_PLAYBOOK)) for platform in platforms}
    enabled = bool(getattr(brain, "traffic_strategy_enabled", True))
    return {
        "enabled": enabled,
        "traffic_goals": getattr(brain, "traffic_goals", "") or "Grow qualified discovery and meaningful action.",
        "topic_seeds": list(getattr(brain, "topic_seeds", []) or []),
        "conversion_actions": getattr(brain, "conversion_actions", "") or "Define one measurable next action per item.",
        "method": [
            "Start from a real audience problem, search intent, or question—not an empty volume target.",
            "Propose demand hypotheses from supplied topic seeds; never fabricate live trend volume or popularity.",
            "Create an original answer with evidence from the Brand Brain and clearly separate facts from hypotheses.",
            "Turn one strong core idea into native platform variants instead of copying one caption everywhere.",
            "Use one primary CTA and one measurable success signal for each content item.",
            "Run hook, format, and CTA experiments; use the 30-day analytics feedback to choose the next iteration.",
        ],
        "content_mix": {
            "discovery": 40,
            "trust_and_proof": 30,
            "conversion": 20,
            "community_and_retention": 10,
        },
        "platform_rules": platform_rules,
        "analytics_feedback": analytics_feedback,
        "measurement_loop": {
            "discover": "Track reach, impressions, or views.",
            "resonate": "Track saves, shares/reposts, replies/comments, and watch signals where available.",
            "convert": "Track clicks and the configured conversion action.",
            "iterate": "Keep winners, diagnose weak hooks/formats/CTAs, and change one major variable per experiment.",
        },
        "guardrails": [
            "No fabricated statistics, testimonials, trend rankings, or search-volume claims.",
            "Google Trends values are relative 0–100 interest, not absolute demand or polling.",
            "A rising topic is a hypothesis until verified with current source data.",
            "AI output remains a draft and requires human approval before publishing.",
        ],
        "sources": source_snapshot,
    }
