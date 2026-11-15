"""Pause and resume a TV through Home Assistant (optional)."""

import json
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger("azan")

_NOT_PLAYING = ("off", "idle", "standby", "unavailable", "unknown", "paused")


def _request(ha_url, token, path, body=None, timeout=8):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{ha_url}{path}", data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "null")


def configured(settings):
    return bool(settings.get("ha_url") and settings.get("ha_token")
                and settings.get("tv_entity_id"))


def _state(settings):
    try:
        data = _request(settings["ha_url"], settings["ha_token"],
                        f"/api/states/{settings['tv_entity_id']}")
        return (data or {}).get("state")
    except (OSError, ValueError) as exc:
        log.warning("Home Assistant: could not read the TV state (%s)", exc)
        return None


def _call(settings, service):
    try:
        _request(settings["ha_url"], settings["ha_token"],
                 f"/api/services/media_player/{service}",
                 {"entity_id": settings["tv_entity_id"]})
        return True
    except (OSError, ValueError) as exc:
        log.warning("Home Assistant: media_player.%s failed (%s)", service, exc)
        return False


def pause_tv(settings):
    """Pause the TV if it is playing. Returns True if we paused it."""
    if not configured(settings):
        return False
    state = _state(settings)
    if state and state not in _NOT_PLAYING:
        log.info("TV is '%s' — pausing it.", state)
        return _call(settings, "media_pause")
    return False


def resume_tv(settings, sleep=time.sleep):
    if not configured(settings):
        return
    log.info("Resuming the TV.")
    _call(settings, "media_play")
    sleep(3)
    if _state(settings) == "playing":
        return
    _call(settings, "turn_on")
    sleep(5)
    _call(settings, "media_play")


def media_players(ha_url, token):
    """List Home Assistant media_player entities as [{id, name}]."""
    try:
        states = _request(ha_url.rstrip("/"), token, "/api/states")
    except urllib.error.HTTPError as exc:
        hint = " — check the token" if exc.code in (401, 403) else ""
        raise RuntimeError(f"Home Assistant returned HTTP {exc.code}{hint}") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not reach Home Assistant: {exc}") from exc
    players = []
    for entity in states or []:
        entity_id = entity.get("entity_id", "")
        if entity_id.startswith("media_player."):
            name = (entity.get("attributes") or {}).get("friendly_name") or entity_id
            players.append({"id": entity_id, "name": name})
    return sorted(players, key=lambda p: p["name"].lower())
