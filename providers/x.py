"""X API v2 provider using OAuth 2.0 Authorization Code with PKCE."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import time
from pathlib import Path
from urllib.parse import urlencode

from .base import SocialProvider
from .exceptions import OAuthError, PublishError
from .types import (
    AccountMetrics,
    AccountProfile,
    AuthType,
    MediaType,
    OAuthTokens,
    PostMetrics,
    PostType,
    PublishContent,
    PublishResult,
    RateLimitConfig,
)

AUTH_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
REVOKE_URL = "https://api.x.com/2/oauth2/revoke"
API_BASE = "https://api.x.com/2"
MAX_MEDIA_ITEMS = 4
MEDIA_CHUNK_BYTES = 4 * 1024 * 1024
MAX_PROCESSING_POLLS = 30


class XProvider(SocialProvider):
    """Publishing and analytics adapter for X user-context APIs."""

    uses_pkce = True
    account_metrics_supports_date_range = False

    @property
    def platform_name(self) -> str:
        return "X"

    @property
    def auth_type(self) -> AuthType:
        return AuthType.OAUTH2

    @property
    def max_caption_length(self) -> int:
        return 280

    @property
    def supported_post_types(self) -> list[PostType]:
        return [PostType.TEXT, PostType.IMAGE, PostType.VIDEO, PostType.LINK, PostType.POLL]

    @property
    def supported_media_types(self) -> list[MediaType]:
        return [MediaType.JPEG, MediaType.PNG, MediaType.GIF, MediaType.MP4, MediaType.MOV]

    @property
    def required_scopes(self) -> list[str]:
        return ["tweet.read", "tweet.write", "users.read", "offline.access"]

    @property
    def rate_limits(self) -> RateLimitConfig:
        # X products and access tiers vary. Keep Ruang's default conservative;
        # operators can raise the per-account override to their approved tier.
        return RateLimitConfig(
            requests_per_hour=300,
            requests_per_day=5000,
            publish_per_day=50,
            extra={"documented_post_per_user_15_minutes": 100, "tier_dependent": True},
        )

    def get_auth_url(self, redirect_uri: str, state: str, code_verifier: str | None = None) -> str:
        if not code_verifier:
            raise OAuthError("X OAuth requires a PKCE code verifier.", platform=self.platform_name)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
        params = {
            "response_type": "code",
            "client_id": self.credentials["client_id"],
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.required_scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def _client_auth_header(self) -> dict[str, str]:
        raw = f"{self.credentials['client_id']}:{self.credentials['client_secret']}".encode()
        return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> OAuthTokens:
        if not code_verifier:
            raise OAuthError("X token exchange requires the PKCE code verifier.", platform=self.platform_name)
        response = self._request(
            "POST",
            TOKEN_URL,
            headers=self._client_auth_header(),
            data={
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
        )
        return self._tokens_from_response(response.json(), "token exchange")

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        response = self._request(
            "POST",
            TOKEN_URL,
            headers=self._client_auth_header(),
            data={
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "client_id": self.credentials["client_id"],
            },
        )
        return self._tokens_from_response(response.json(), "token refresh")

    def _tokens_from_response(self, data: dict, operation: str) -> OAuthTokens:
        token = data.get("access_token")
        if not token:
            raise OAuthError(
                f"X {operation} failed: {data.get('error_description') or data.get('error') or 'missing access token'}",
                platform=self.platform_name,
                raw_response=data,
            )
        return OAuthTokens(
            access_token=token,
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            scope=data.get("scope"),
            raw_response=data,
        )

    def get_profile(self, access_token: str) -> AccountProfile:
        response = self._request(
            "GET",
            f"{API_BASE}/users/me",
            access_token=access_token,
            params={"user.fields": "id,name,username,profile_image_url,public_metrics"},
        )
        data = response.json().get("data") or {}
        metrics = data.get("public_metrics") or {}
        return AccountProfile(
            platform_id=str(data.get("id") or ""),
            name=data.get("name") or data.get("username") or "X account",
            handle=data.get("username"),
            avatar_url=data.get("profile_image_url"),
            follower_count=int(metrics.get("followers_count") or 0),
            extra={"public_metrics": metrics},
        )

    def publish_post(self, access_token: str, content: PublishContent) -> PublishResult:
        text = (content.text or "").strip()
        if content.link_url and content.link_url not in text:
            text = f"{text}\n{content.link_url}".strip()
        if not text and not content.media_files:
            raise PublishError("An X post requires text or media.", platform=self.platform_name)
        if len(text) > self.max_caption_length:
            raise PublishError(
                f"X post exceeds the {self.max_caption_length}-character limit.",
                platform=self.platform_name,
            )

        media_files = content.media_files[:MAX_MEDIA_ITEMS]
        complex_media = [
            path
            for path in media_files
            if (mimetypes.guess_type(path)[0] or "").startswith("video/")
            or mimetypes.guess_type(path)[0] == "image/gif"
        ]
        if complex_media and len(media_files) > 1:
            raise PublishError(
                "X allows one video or GIF per post; publish it without additional media.",
                platform=self.platform_name,
            )
        media_ids = [self._upload_media(access_token, path) for path in media_files]
        payload: dict = {}
        if text:
            payload["text"] = text
        if media_ids:
            payload["media"] = {"media_ids": media_ids}
        poll = content.extra.get("poll")
        if poll:
            payload["poll"] = poll

        response = self._request("POST", f"{API_BASE}/tweets", access_token=access_token, json=payload)
        body = response.json()
        post_id = str((body.get("data") or {}).get("id") or "")
        if not post_id:
            raise PublishError("X did not return a post ID.", platform=self.platform_name, raw_response=body)
        return PublishResult(
            platform_post_id=post_id,
            url=f"https://x.com/i/web/status/{post_id}",
            extra=body,
        )

    def _upload_media(self, access_token: str, file_path: str) -> str:
        path = Path(file_path)
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        media = path.read_bytes()
        if mime_type == "image/gif" or mime_type.startswith("video/"):
            category = "tweet_gif" if mime_type == "image/gif" else "tweet_video"
            return self._upload_chunked(access_token, media, mime_type, category)
        encoded = base64.b64encode(media).decode()
        response = self._request(
            "POST",
            f"{API_BASE}/media/upload",
            access_token=access_token,
            json={
                "media": encoded,
                "media_category": "tweet_image",
                "media_type": mime_type,
            },
        )
        return self._media_id(response.json())

    def _upload_chunked(self, access_token: str, media: bytes, mime_type: str, category: str) -> str:
        initialize = self._request(
            "POST",
            f"{API_BASE}/media/upload/initialize",
            access_token=access_token,
            json={
                "media_category": category,
                "media_type": mime_type,
                "total_bytes": len(media),
                "shared": False,
            },
        )
        media_id = self._media_id(initialize.json())
        for segment_index, offset in enumerate(range(0, len(media), MEDIA_CHUNK_BYTES)):
            segment = media[offset : offset + MEDIA_CHUNK_BYTES]
            self._request(
                "POST",
                f"{API_BASE}/media/upload/{media_id}/append",
                access_token=access_token,
                json={
                    "media": base64.b64encode(segment).decode(),
                    "segment_index": segment_index,
                },
            )
        finalized = self._request(
            "POST",
            f"{API_BASE}/media/upload/{media_id}/finalize",
            access_token=access_token,
        ).json()
        self._wait_for_media(access_token, media_id, finalized)
        return media_id

    def _wait_for_media(self, access_token: str, media_id: str, payload: dict) -> None:
        processing = (payload.get("data") or {}).get("processing_info")
        for _ in range(MAX_PROCESSING_POLLS):
            if not processing:
                return
            state = str(processing.get("state") or "").lower()
            if state in {"succeeded", "success"}:
                return
            if state == "failed":
                error = processing.get("error") or {}
                raise PublishError(
                    f"X media processing failed: {error.get('message') or error.get('name') or 'unknown error'}",
                    platform=self.platform_name,
                    raw_response=payload,
                )
            delay = min(max(int(processing.get("check_after_secs") or 1), 0), 10)
            if delay:
                time.sleep(delay)
            response = self._request(
                "GET",
                f"{API_BASE}/media/upload",
                access_token=access_token,
                params={"media_id": media_id, "command": "STATUS"},
            )
            payload = response.json()
            processing = (payload.get("data") or {}).get("processing_info")
        raise PublishError(
            "X media processing timed out.",
            platform=self.platform_name,
            raw_response=payload,
        )

    def _media_id(self, payload: dict) -> str:
        data = payload.get("data") or {}
        media_id = str(data.get("id") or data.get("media_id") or payload.get("media_id_string") or "")
        if not media_id:
            raise PublishError(
                "X media upload did not return an ID.", platform=self.platform_name, raw_response=payload
            )
        return media_id

    def get_post_metrics(self, access_token: str, post_id: str) -> PostMetrics:
        response = self._request(
            "GET",
            f"{API_BASE}/tweets/{post_id}",
            access_token=access_token,
            params={
                "tweet.fields": "public_metrics,non_public_metrics,organic_metrics",
            },
        )
        body = response.json()
        data = body.get("data") or {}
        public = data.get("public_metrics") or {}
        private = data.get("non_public_metrics") or {}
        organic = data.get("organic_metrics") or {}

        def metric(name: str) -> int:
            return int(organic.get(name) or private.get(name) or public.get(name) or 0)

        replies = metric("reply_count")
        reposts = metric("retweet_count")
        quotes = metric("quote_count")
        likes = metric("like_count")
        clicks = metric("url_link_clicks")
        impressions = metric("impression_count")
        return PostMetrics(
            impressions=impressions,
            likes=likes,
            comments=replies,
            shares=reposts,
            clicks=clicks,
            engagements=likes + replies + reposts + quotes + clicks,
            extra={"replies": replies, "reposts": reposts, "quotes": quotes, "raw": body},
        )

    def get_account_metrics(self, access_token: str, date_range) -> AccountMetrics:
        del date_range
        profile = self.get_profile(access_token)
        return AccountMetrics(
            followers=profile.follower_count,
            extra={"public_metrics": profile.extra.get("public_metrics", {})},
        )

    def revoke_token(self, access_token: str) -> bool:
        try:
            self._request(
                "POST",
                REVOKE_URL,
                headers=self._client_auth_header(),
                data={"token": access_token, "token_type_hint": "access_token"},
            )
            return True
        except Exception:
            return False
