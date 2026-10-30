"""
services/voicelink_api.py

Thin HTTP client for the VoiceLink India REST API.
Base URL: https://app.voicelink.co.in/api/v1

All credentials are read from environment variables:
  VOICELINK_USERNAME  — VoiceLink account username
  VOICELINK_PASSWORD  — VoiceLink account password

Security:
  - Never logs access_token values
  - Never logs caller phone numbers
  - All secrets from env vars only
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://app.voicelink.co.in/api/v1"
_DEFAULT_TIMEOUT = 30  # seconds


def login(username: str, password: str) -> str:
    """
    Authenticate with VoiceLink and return an access token.

    Args:
        username: VoiceLink account username.
        password: VoiceLink account password.

    Returns:
        access_token string.

    Raises:
        requests.HTTPError: if the API returns a non-2xx status.
        ValueError: if the response does not contain a token.
    """
    resp = requests.post(
        f"{API_BASE}/auth/login",
        json={"username": username, "password": password},
        timeout=_DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token") or data.get("token") or data.get("accessToken", "")
    if not token:
        raise ValueError(f"No access_token in login response: {list(data.keys())}")
    # Never log the token value
    logger.info("VoiceLink login: token obtained (key=%s)", list(data.keys())[0])
    return token


def create_websocket_bot(
    access_token: str,
    bot_name: str,
    websocket_url: str,
    webhook_url: str = "",
) -> int:
    """
    Create a VoiceLink WebSocket bot.

    Args:
        access_token: Bearer token from login().
        bot_name: Display name for the bot.
        websocket_url: The wss:// URL VoiceLink will connect to.
        webhook_url: Optional HTTPS URL for lifecycle webhook events.

    Returns:
        Bot ID (integer).

    Raises:
        requests.HTTPError: on API error.
        ValueError: if the response does not contain a bot id.
    """
    payload: dict = {"name": bot_name, "websocket_url": websocket_url}
    if webhook_url:
        payload["webhook_url"] = webhook_url

    resp = requests.post(
        f"{API_BASE}/websocket-bot/create",
        json=payload,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    bot_id = data.get("id") or data.get("bot_id") or data.get("botId", 0)
    if not bot_id:
        raise ValueError(f"No bot id in create response: {list(data.keys())}")
    logger.info("VoiceLink: created websocket bot (id=%s)", bot_id)
    return int(bot_id)


def create_call_routing(
    access_token: str,
    did_id: int,
    inbound_websocket_bot_id: int,
) -> int:
    """
    Configure call routing for a DID to use a WebSocket bot.

    Args:
        access_token: Bearer token from login().
        did_id: The DID (phone number) ID to route.
        inbound_websocket_bot_id: Bot ID from create_websocket_bot().

    Returns:
        Routing ID (integer).

    Raises:
        requests.HTTPError: on API error.
        ValueError: if the response does not contain a routing id.
    """
    payload = {
        "did_id": did_id,
        "for_inbound_call": 3,  # 3 = WebSocket bot (per VoiceLink spec)
        "inbound_websocket_bot_id": inbound_websocket_bot_id,
    }
    resp = requests.post(
        f"{API_BASE}/call-routing/create",
        json=payload,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    routing_id = data.get("id") or data.get("routing_id") or data.get("routingId", 0)
    if not routing_id:
        raise ValueError(f"No routing id in create response: {list(data.keys())}")
    logger.info("VoiceLink: created call routing (id=%s)", routing_id)
    return int(routing_id)


def get_call_details(access_token: str, call_id: str) -> dict:
    """
    Fetch details for a specific call.

    Args:
        access_token: Bearer token from login().
        call_id: Call ID or SID.

    Returns:
        Call details dict from the API.
    """
    resp = requests.get(
        f"{API_BASE}/calls/{call_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def setup_voicelink_bot(
    websocket_url: str = "",
    webhook_url: str = "",
    bot_name: str = "AI Farmer Helpline Bot",
) -> dict:
    """
    Convenience function: run the full VoiceLink provisioning flow.

    Reads credentials from VOICELINK_USERNAME and VOICELINK_PASSWORD env vars.
    Reads DID phone number from VOICELINK_PHONE_NUMBER env var (used as did_id).

    Returns:
        {"access_token": str, "bot_id": int, "routing_id": int}

    Raises:
        EnvironmentError: if required env vars are missing.
        requests.HTTPError / ValueError: on API errors.
    """
    username = os.getenv("VOICELINK_USERNAME", "")
    password = os.getenv("VOICELINK_PASSWORD", "")
    # VOICELINK_DID_ID is the integer DID ID from the VoiceLink portal.
    # (not the telephone number — use GET /reseller/did/purchased to find it)
    # Falls back to VOICELINK_PHONE_NUMBER for backward compatibility.
    did_id_str = os.getenv("VOICELINK_DID_ID", "") or os.getenv("VOICELINK_PHONE_NUMBER", "")

    if not username or not password:
        raise EnvironmentError(
            "VOICELINK_USERNAME and VOICELINK_PASSWORD must be set in environment"
        )

    ws_url = websocket_url or os.getenv("VOICELINK_BOT_WEBSOCKET_URL", "")
    wh_url = webhook_url or os.getenv("VOICELINK_BOT_WEBHOOK_URL", "")

    if not ws_url:
        raise EnvironmentError(
            "websocket_url or VOICELINK_BOT_WEBSOCKET_URL must be set"
        )

    token = login(username, password)
    bot_id = create_websocket_bot(token, bot_name, ws_url, wh_url)

    routing_id = 0
    if did_id_str:
        try:
            routing_id = create_call_routing(token, int(did_id_str), bot_id)
        except Exception as exc:
            logger.warning("VoiceLink: call routing setup failed (non-fatal): %s", exc)

    return {"bot_id": bot_id, "routing_id": routing_id}
