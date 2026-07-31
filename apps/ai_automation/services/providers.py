from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings


class ProviderError(RuntimeError):
    pass


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
            return AIResult(
                data=_json_object(payload["choices"][0]["message"]["content"]),
                provider=self.name,
                model=self.model,
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
                request_id=response.headers.get("x-request-id", ""),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"{self.name} request failed: {exc}") from exc


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
            raise ProviderError(f"Anthropic request failed: {exc}") from exc


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
            raise ProviderError(f"Gemini request failed: {exc}") from exc


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
        data = {
            "strategy": {
                "north_star": context.get("objective") or f"Membangun relevansi seputar {subject}",
                "narrative": f"Mengubah brief menjadi seri konten yang konsisten: {subject}.",
                "pillars": ["education", "trust", "product", "community"],
                "channel_roles": {platform: _channel_role(platform) for platform in platforms},
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
    return "Distribusi pesan utama dengan format yang sesuai kebiasaan audiens."


class ProviderRouter:
    def __init__(self, providers: list[Any] | None = None):
        self.providers = providers if providers is not None else configured_providers()

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


def configured_providers() -> list[Any]:
    providers: list[Any] = []
    for name in getattr(settings, "RUANG_AI_PROVIDERS", ["demo"]):
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
