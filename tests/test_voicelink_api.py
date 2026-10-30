"""
tests/test_voicelink_api.py

Unit tests for services/voicelink_api.py — VoiceLink REST API client.
All HTTP calls are mocked; no real network calls are made.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.voicelink_api import (
    login,
    create_websocket_bot,
    create_call_routing,
    get_call_details,
    setup_voicelink_bot,
)


def _mock_response(json_data: dict, status_code: int = 200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status = MagicMock()  # no-op by default
    return mock


class TestLogin:
    def test_login_returns_token(self):
        with patch("services.voicelink_api.requests.post") as mock_post:
            mock_post.return_value = _mock_response({"access_token": "tok123"})
            token = login("user", "pass")
        assert token == "tok123"

    def test_login_alternative_key_names(self):
        """Accept 'token' and 'accessToken' response keys too."""
        with patch("services.voicelink_api.requests.post") as mock_post:
            mock_post.return_value = _mock_response({"token": "tok456"})
            token = login("user", "pass")
        assert token == "tok456"

    def test_login_raises_on_missing_token(self):
        with patch("services.voicelink_api.requests.post") as mock_post:
            mock_post.return_value = _mock_response({"error": "bad credentials"})
            with pytest.raises(ValueError, match="No access_token"):
                login("user", "pass")

    def test_login_raises_on_http_error(self):
        with patch("services.voicelink_api.requests.post") as mock_post:
            resp = _mock_response({}, 401)
            resp.raise_for_status.side_effect = Exception("401 Unauthorized")
            mock_post.return_value = resp
            with pytest.raises(Exception):
                login("user", "pass")


class TestCreateWebsocketBot:
    def test_returns_bot_id(self):
        with patch("services.voicelink_api.requests.post") as mock_post:
            mock_post.return_value = _mock_response({"id": 42})
            bot_id = create_websocket_bot("tok", "My Bot", "wss://example.com/ws")
        assert bot_id == 42

    def test_includes_webhook_url_when_provided(self):
        with patch("services.voicelink_api.requests.post") as mock_post:
            mock_post.return_value = _mock_response({"id": 7})
            create_websocket_bot("tok", "Bot", "wss://x.com/ws", "https://x.com/wh")
            call_kwargs = mock_post.call_args[1]
            assert "webhook_url" in call_kwargs["json"]

    def test_raises_on_missing_id(self):
        with patch("services.voicelink_api.requests.post") as mock_post:
            mock_post.return_value = _mock_response({"name": "ok"})
            with pytest.raises(ValueError, match="No bot id"):
                create_websocket_bot("tok", "Bot", "wss://x.com/ws")


class TestCreateCallRouting:
    def test_returns_routing_id(self):
        with patch("services.voicelink_api.requests.post") as mock_post:
            mock_post.return_value = _mock_response({"id": 99})
            routing_id = create_call_routing("tok", 1, 42)
        assert routing_id == 99

    def test_payload_contains_correct_for_inbound_call(self):
        with patch("services.voicelink_api.requests.post") as mock_post:
            mock_post.return_value = _mock_response({"id": 1})
            create_call_routing("tok", 5, 10)
            payload = mock_post.call_args[1]["json"]
            assert payload["for_inbound_call"] == 3
            assert payload["inbound_websocket_bot_id"] == 10


class TestGetCallDetails:
    def test_returns_call_dict(self):
        with patch("services.voicelink_api.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"call_id": "C1", "status": "completed"})
            result = get_call_details("tok", "C1")
        assert result["call_id"] == "C1"


class TestSetupVoicelinkBot:
    def test_raises_without_credentials(self):
        with patch.dict(os.environ, {"VOICELINK_USERNAME": "", "VOICELINK_PASSWORD": ""}):
            with pytest.raises(EnvironmentError, match="VOICELINK_USERNAME"):
                setup_voicelink_bot(websocket_url="wss://x.com/ws")

    def test_raises_without_websocket_url(self):
        with patch.dict(os.environ, {
            "VOICELINK_USERNAME": "u",
            "VOICELINK_PASSWORD": "p",
            "VOICELINK_BOT_WEBSOCKET_URL": "",
        }):
            with pytest.raises(EnvironmentError, match="websocket_url"):
                setup_voicelink_bot()

    def test_full_flow(self):
        with patch("services.voicelink_api.login", return_value="tok") as mock_login, \
             patch("services.voicelink_api.create_websocket_bot", return_value=5) as mock_bot, \
             patch("services.voicelink_api.create_call_routing", return_value=9) as mock_routing, \
             patch.dict(os.environ, {
                 "VOICELINK_USERNAME": "u",
                 "VOICELINK_PASSWORD": "p",
                 "VOICELINK_PHONE_NUMBER": "123",
             }):
            result = setup_voicelink_bot(websocket_url="wss://x.com/ws")

        assert result["bot_id"] == 5
        assert result["routing_id"] == 9
        mock_login.assert_called_once_with("u", "p")
