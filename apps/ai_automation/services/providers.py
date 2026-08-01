from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings


class ProviderError(RuntimeError):
    pass


def _safe_request_error(provider: str, exc: Exception) -> ProviderError:
    """Return a useful error without leaking auth headers or query parameters."""

    if isinstance(exc, httpx.HTTPStatusError):
        return ProviderError(f"{provider} request failed (HTTP {exc.response.status_code}).")
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(f"{provider} request timed out.")
    if isinstance(exc, httpx.RequestError):
        return ProviderError(f"{provider} request failed because of a network error.")
    if isinstance(exc, json.JSONDecodeError):
        return ProviderError(f"{provider} endpoint returned non-JSON data.")
    return ProviderError(f"{provider} returned an invalid response.")


@dataclass(frozen=True)
class AIResult:
    data: dict[str, Any]
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str = ""


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("Provider did not return a JSON object.") from None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Provider returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ProviderError("Provider response must be a JSON object.")
    return value


def _content_text(content: Any) -> str:
    """Extract text from common OpenAI-compatible content block variants."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_content_text(part) for part in content)
    if not isinstance(content, dict):
        return ""
    text = content.get("text")
    if isinstance(text, dict):
        text = text.get("value")
    if isinstance(text, str):
        return text
    value = content.get("value")
    if isinstance(value, str):
        return value
    nested = content.get("content")
    if nested is not content:
        return _content_text(nested)
    return ""


def _openai_response_content(payload: Any) -> str | dict[str, Any]:
    """Read Chat Completions, Responses API, and common gateway envelopes."""

    if not isinstance(payload, dict):
        raise ProviderError("OpenAI-compatible endpoint returned a non-object response.")

    error = payload.get("error")
    if error:
        details = []
        if isinstance(error, dict):
            for key in ("type", "code"):
                value = error.get(key)
                if isinstance(value, str) and value:
                    details.append(f"{key}={value[:80]}")
        suffix = f" ({', '.join(details)})" if details else ""
        raise ProviderError(f"OpenAI-compatible endpoint returned an error object{suffix}.")

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            message = choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, dict):
                    text = _content_text(content)
                    return text or content
                text = _content_text(content)
                if text:
                    return text
                for tool_call in message.get("tool_calls") or []:
                    if isinstance(tool_call, dict):
                        function = tool_call.get("function") or {}
                        arguments = function.get("arguments") if isinstance(function, dict) else None
                        if isinstance(arguments, str) and arguments:
                            return arguments
            text = _content_text(choice.get("text"))
            if text:
                return text

    for key in ("output_text", "response", "text"):
        text = _content_text(payload.get(key))
        if text:
            return text

    for key in ("data", "result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return _openai_response_content(nested)
        text = _content_text(nested)
        if text:
            return text

    output = payload.get("output")
    if isinstance(output, list):
        text = "".join(_content_text(item.get("content")) for item in output if isinstance(item, dict))
        if text:
            return text

    if "ok" in payload or "strategy" in payload or "items" in payload:
        return payload

    received_fields = ", ".join(sorted(str(key)[:40] for key in payload)) or "none"
    raise ProviderError(
        "OpenAI-compatible response is missing generated content "
        "(expected choices[0].message.content or output_text). "
        f"Received fields: {received_fields}."
    )


class OpenAICompatibleProvider:
    def __init__(self, *, name: str, api_key: str, base_url: str, model: str):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate_json(self, *, system: str, prompt: str) -> AIResult:
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=90,
            )
            response.raise_for_status()
            payload = response.json()
            usage = payload.get("usage") or {}
            content = _openai_response_content(payload)
            return AIResult(
                data=content if isinstance(content, dict) else _json_object(content),
                provider=self.name,
                model=self.model,
                input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
                request_id=response.headers.get("x-request-id", ""),
            )
        except ProviderError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise _safe_request_error(self.name, exc) from exc


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, *, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def generate_json(self, *, system: str, prompt: str) -> AIResult:
        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model,
                    "max_tokens": 8192,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=90,
            )
            response.raise_for_status()
            payload = response.json()
            usage = payload.get("usage") or {}
            text = "".join(part.get("text", "") for part in payload.get("content", []) if part.get("type") == "text")
            return AIResult(
                data=_json_object(text),
                provider=self.name,
                model=self.model,
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                request_id=response.headers.get("request-id", ""),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise _safe_request_error("Anthropic", exc) from exc


class GeminiProvider:
    name = "gemini"

    def __init__(self, *, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def generate_json(self, *, system: str, prompt: str) -> AIResult:
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                params={"key": self.api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                    },
                },
                timeout=90,
            )
            response.raise_for_status()
            payload = response.json()
            usage = payload.get("usageMetadata") or {}
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
            return AIResult(
                data=_json_object(text),
                provider=self.name,
                model=self.model,
                input_tokens=int(usage.get("promptTokenCount") or 0),
                output_tokens=int(usage.get("candidatesTokenCount") or 0),
                request_id=response.headers.get("x-request-id", ""),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise _safe_request_error("Gemini", exc) from exc


class DemoProvider:
    """Deterministic local provider so the workflow can be evaluated without keys."""

    name = "demo"
    model = "ruang-demo-planner-v1"

    def generate_json(self, *, system: str, prompt: str) -> AIResult:
        del system
        match = re.search(r"<campaign_context>(.*?)</campaign_context>", prompt, re.DOTALL)
        if not match:
            raise ProviderError("Demo provider could not find campaign context.")
        context = json.loads(match.group(1))
        brief = str(context.get("brief") or "Campaign").strip()
        subject = brief.splitlines()[0][:100].rstrip(" .!?")
        platforms = context.get("platforms") or ["instagram"]
        dates = context.get("suggested_dates") or [context["start_date"]]
        items = []
        hooks = [
            "Masalah yang sering dianggap biasa, padahal bisa diubah",
            "Tiga langkah praktis yang bisa dicoba hari ini",
            "Di balik proses: bagaimana kami mengambil keputusan",
            "Mitos versus fakta yang perlu audiens tahu",
            "Checklist singkat sebelum mengambil langkah berikutnya",
        ]
        for index, scheduled_date in enumerate(dates):
            platform = platforms[index % len(platforms)]
            hook = hooks[index % len(hooks)]
            caption = _demo_caption(platform, hook, subject, context.get("objective", ""))
            items.append(
                {
                    "platform": platform,
                    "scheduled_for": f"{scheduled_date}T09:00:00",
                    "title": f"{hook} · {platform}",
                    "caption": caption,
                    "caption_variants": [
                        f"{hook}.\n\n{subject}\n\nApa pengalamanmu? Bagikan di komentar.",
                        f"{subject}: mulai dari satu langkah kecil hari ini. Simpan postingan ini untuk nanti.",
                        f"Sudut pandang lain tentang {subject}: apa yang bisa timmu uji minggu ini?",
                    ],
                    "visual_prompt": (
                        f"Editorial social media image about {subject}, clean geometric composition, "
                        "warm human atmosphere, generous negative space, no text, brand-safe"
                    ),
                    "video_script": (
                        f"Hook (0-3s): {hook}. Visual: close-up yang dinamis. "
                        f"Body (3-20s): jelaskan {subject} dalam tiga poin singkat. "
                        "CTA (20-25s): ajak audiens menyimpan dan berbagi."
                    ),
                    "content_pillar": ["education", "trust", "product", "community"][index % 4],
                    "call_to_action": "Simpan, bagikan, atau beri pendapat di komentar.",
                }
            )
        playbook = context.get("traffic_playbook") or {}
        data = {
            "strategy": {
                "north_star": context.get("objective") or f"Membangun relevansi seputar {subject}",
                "narrative": f"Mengubah brief menjadi seri konten yang konsisten: {subject}.",
                "pillars": ["education", "trust", "product", "community"],
                "channel_roles": {platform: _channel_role(platform) for platform in platforms},
                "traffic_objective": playbook.get("traffic_goals") or context.get("objective"),
                "demand_hypotheses": playbook.get("topic_seeds") or [subject],
                "search_intents": ["learn", "compare", "act"],
                "hook_angles": ["problem", "practical outcome", "evidence", "counterintuitive lesson"],
                "distribution_plan": [
                    f"Adapt the core idea for {platform}: {_channel_role(platform)}" for platform in platforms
                ],
                "conversion_path": playbook.get("conversion_actions") or "One measurable next action per item.",
                "experiments": ["Test two hook angles", "Test proof versus how-to format", "Test CTA wording"],
                "success_metrics": [
                    signal
                    for rules in (playbook.get("platform_rules") or {}).values()
                    for signal in rules.get("primary_signals", [])
                ][:10],
                "evidence_plan": ["Use Brand Brain knowledge", "Verify current trend hypotheses before approval"],
                "source_alignment": [source.get("key") for source in playbook.get("sources", [])],
                "optimization_note": context.get("analytics_feedback") or "Gunakan baseline 30 hari setelah publikasi.",
            },
            "items": items,
        }
        raw_size = len(prompt) + len(json.dumps(data))
        return AIResult(
            data=data,
            provider=self.name,
            model=self.model,
            input_tokens=max(len(prompt) // 4, 1),
            output_tokens=max(raw_size // 5, 1),
        )


def _demo_caption(platform: str, hook: str, subject: str, objective: str) -> str:
    if platform == "tiktok":
        return f"{hook} 👀\n{subject}\nCoba ini, lalu ceritakan hasilnya. #BelajarBareng #Tips"
    if platform.startswith("linkedin"):
        return (
            f"{hook}.\n\n{subject}\n\n"
            f"Konteksnya sederhana: {objective or 'keputusan yang baik dimulai dari pemahaman yang jernih'}.\n\n"
            "Apa pelajaran yang paling relevan untuk tim Anda?"
        )
    if platform == "x":
        base = f"{hook}: {subject}. {objective or 'Mulai dari insight yang bisa diuji.'}"
        return base[:280]
    if platform == "instagram":
        return (
            f"{hook} ✨\n\n{subject}\n\n"
            "Geser perspektifnya, mulai dari satu langkah kecil, lalu ukur hasilnya.\n\n"
            "Simpan untuk dipraktikkan dan kirim ke teman yang membutuhkannya."
        )
    return f"{hook}\n\n{subject}\n\nMulai dari satu langkah kecil. Simpan dan bagikan jika bermanfaat."


def _channel_role(platform: str) -> str:
    if platform == "tiktok":
        return "Discovery melalui video pendek, hook kuat, dan bahasa native."
    if platform.startswith("linkedin"):
        return "Thought leadership, bukti, dan percakapan profesional."
    if platform == "instagram":
        return "Visual storytelling, saves, shares, dan community building."
    if platform == "x":
        return "Real-time conversation, concise insight, distribution, and rapid message testing."
    return "Distribusi pesan utama dengan format yang sesuai kebiasaan audiens."


class ProviderRouter:
    def __init__(self, providers: list[Any] | None = None, *, organization=None):
        self.providers = providers if providers is not None else configured_providers(organization=organization)

    def generate_json(self, *, system: str, prompt: str) -> AIResult:
        errors = []
        for provider in self.providers:
            try:
                return provider.generate_json(system=system, prompt=prompt)
            except ProviderError as exc:
                errors.append(str(exc))
        if not self.providers:
            raise ProviderError("No AI provider is configured.")
        raise ProviderError("All configured AI providers failed: " + " | ".join(errors))


def provider_from_connection(connection):
    if connection.provider in {"openai", "openai_compatible"}:
        return OpenAICompatibleProvider(
            name=connection.provider,
            api_key=connection.api_key,
            base_url=connection.base_url,
            model=connection.model_name,
        )
    if connection.provider == "anthropic":
        return AnthropicProvider(api_key=connection.api_key, model=connection.model_name)
    if connection.provider == "gemini":
        return GeminiProvider(api_key=connection.api_key, model=connection.model_name)
    raise ProviderError("Unsupported AI provider configuration.")


def test_provider_connection(connection) -> AIResult:
    """Make a minimal explicit request without exposing the stored credential."""

    return provider_from_connection(connection).generate_json(
        system="Return only a valid JSON object. Do not add markdown.",
        prompt='Connection check. Return exactly {"ok": true}.',
    )


def _environment_providers(*, excluded_names: set[str] | None = None) -> list[Any]:
    providers: list[Any] = []
    excluded = excluded_names or set()
    for name in getattr(settings, "RUANG_AI_PROVIDERS", ["demo"]):
        if name in excluded:
            continue
        if name == "openai" and settings.RUANG_OPENAI_API_KEY:
            providers.append(
                OpenAICompatibleProvider(
                    name="openai",
                    api_key=settings.RUANG_OPENAI_API_KEY,
                    base_url=settings.RUANG_OPENAI_BASE_URL,
                    model=settings.RUANG_OPENAI_MODEL,
                )
            )
        elif name == "openai_compatible" and settings.RUANG_COMPATIBLE_API_KEY:
            providers.append(
                OpenAICompatibleProvider(
                    name="openai_compatible",
                    api_key=settings.RUANG_COMPATIBLE_API_KEY,
                    base_url=settings.RUANG_COMPATIBLE_BASE_URL,
                    model=settings.RUANG_COMPATIBLE_MODEL,
                )
            )
        elif name == "anthropic" and settings.RUANG_ANTHROPIC_API_KEY:
            providers.append(
                AnthropicProvider(
                    api_key=settings.RUANG_ANTHROPIC_API_KEY,
                    model=settings.RUANG_ANTHROPIC_MODEL,
                )
            )
        elif name == "gemini" and settings.RUANG_GEMINI_API_KEY:
            providers.append(
                GeminiProvider(
                    api_key=settings.RUANG_GEMINI_API_KEY,
                    model=settings.RUANG_GEMINI_MODEL,
                )
            )
        elif name == "demo":
            providers.append(DemoProvider())
    return providers


def configured_providers(organization=None) -> list[Any]:
    """Return organization connections first, followed by environment fallbacks."""

    providers: list[Any] = []
    configured_names: set[str] = set()
    if organization is not None:
        from apps.ai_automation.models import AIProviderConnection

        connections = AIProviderConnection.objects.filter(
            organization=organization,
            is_active=True,
        ).order_by("priority", "provider")
        for connection in connections:
            providers.append(provider_from_connection(connection))
            configured_names.add(connection.provider)

    providers.extend(_environment_providers(excluded_names=configured_names))
    return providers
