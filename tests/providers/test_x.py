"""Tests for the X OAuth, publishing, media, and analytics adapter."""

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest

from providers.exceptions import OAuthError, PublishError
from providers.types import PostType, PublishContent
from providers.x import XProvider


def _response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    return response


@pytest.fixture
def provider() -> XProvider:
    return XProvider({"client_id": "client-id", "client_secret": "client-secret"})


def test_auth_url_uses_pkce_and_offline_scope(provider):
    url = provider.get_auth_url("https://ruang.test/callback", "state-123", "verifier-123")
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == ["client-id"]
    assert query["state"] == ["state-123"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0] != "verifier-123"
    assert "offline.access" in query["scope"][0]


def test_auth_url_requires_pkce(provider):
    with pytest.raises(OAuthError, match="PKCE"):
        provider.get_auth_url("https://ruang.test/callback", "state")


@patch.object(XProvider, "_request")
def test_exchange_code(mock_request, provider):
    mock_request.return_value = _response(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 7200,
            "scope": "tweet.read tweet.write users.read offline.access",
        }
    )
    tokens = provider.exchange_code("code", "https://ruang.test/callback", "verifier")
    assert tokens.access_token == "access"
    assert tokens.refresh_token == "refresh"
    kwargs = mock_request.call_args.kwargs
    assert kwargs["data"]["code_verifier"] == "verifier"
    assert kwargs["headers"]["Authorization"].startswith("Basic ")


@patch.object(XProvider, "_request")
def test_publish_text_post(mock_request, provider):
    mock_request.return_value = _response({"data": {"id": "12345", "text": "hello"}})
    result = provider.publish_post("token", PublishContent(text="hello", post_type=PostType.TEXT))
    assert result.platform_post_id == "12345"
    assert result.url == "https://x.com/i/web/status/12345"
    assert mock_request.call_args.kwargs["json"] == {"text": "hello"}


def test_publish_rejects_over_limit(provider):
    with pytest.raises(PublishError, match="280"):
        provider.publish_post("token", PublishContent(text="x" * 281))


@patch.object(XProvider, "_request")
def test_publish_uploads_media(mock_request, provider):
    mock_request.side_effect = [
        _response({"data": {"id": "media-1"}}),
        _response({"data": {"id": "post-1"}}),
    ]
    with patch("providers.x.Path.read_bytes", return_value=b"png-bytes"):
        result = provider.publish_post(
            "token",
            PublishContent(text="visual", media_files=["image.png"], post_type=PostType.IMAGE),
        )
    assert result.platform_post_id == "post-1"
    upload = mock_request.call_args_list[0]
    assert upload.args[1] == "https://api.x.com/2/media/upload"
    assert upload.kwargs["json"]["media_type"] == "image/png"
    publish = mock_request.call_args_list[1]
    assert publish.kwargs["json"]["media"] == {"media_ids": ["media-1"]}


@patch.object(XProvider, "_request")
def test_publish_video_uses_chunked_upload(mock_request, provider):
    mock_request.side_effect = [
        _response({"data": {"id": "video-1"}}),
        _response({"data": {"expires_at": 123}}),
        _response({"data": {"id": "video-1", "processing_info": {"state": "pending", "check_after_secs": 0}}}),
        _response({"data": {"id": "video-1", "processing_info": {"state": "succeeded"}}}),
        _response({"data": {"id": "post-video"}}),
    ]
    with patch("providers.x.Path.read_bytes", return_value=b"video-bytes"):
        result = provider.publish_post(
            "token",
            PublishContent(text="watch", media_files=["clip.mp4"], post_type=PostType.VIDEO),
        )
    assert result.platform_post_id == "post-video"
    assert [call.args[1] for call in mock_request.call_args_list[:4]] == [
        "https://api.x.com/2/media/upload/initialize",
        "https://api.x.com/2/media/upload/video-1/append",
        "https://api.x.com/2/media/upload/video-1/finalize",
        "https://api.x.com/2/media/upload",
    ]
    assert mock_request.call_args_list[1].kwargs["json"]["segment_index"] == 0
    assert mock_request.call_args_list[3].kwargs["params"]["command"] == "STATUS"


def test_publish_rejects_video_with_additional_media(provider):
    with pytest.raises(PublishError, match="one video or GIF"):
        provider.publish_post(
            "token",
            PublishContent(text="watch", media_files=["clip.mp4", "cover.png"], post_type=PostType.VIDEO),
        )


@patch.object(XProvider, "_request")
def test_post_metrics_mapping(mock_request, provider):
    mock_request.return_value = _response(
        {
            "data": {
                "public_metrics": {
                    "impression_count": 1000,
                    "like_count": 20,
                    "reply_count": 4,
                    "retweet_count": 3,
                    "quote_count": 2,
                },
                "non_public_metrics": {"url_link_clicks": 11},
            }
        }
    )
    metrics = provider.get_post_metrics("token", "post-1")
    assert metrics.impressions == 1000
    assert metrics.likes == 20
    assert metrics.comments == 4
    assert metrics.shares == 3
    assert metrics.clicks == 11
    assert metrics.engagements == 40
    assert metrics.extra["replies"] == 4
    assert metrics.extra["reposts"] == 3
