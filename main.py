import os
import time
import json
import signal
import logging
from typing import Dict, List, Tuple

import requests
from dotenv import load_dotenv


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("ttv-category-notifier")


class TwitchClient:
    """Minimal Twitch Helix client using app access token."""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._token_expiry: float = 0.0

    def _ensure_token(self):
        # Refresh when missing or within 60s of expiry
        if not self._token or time.time() >= (self._token_expiry - 60):
            logger.debug("Fetching new Twitch app access token")
            resp = requests.post(
                "https://id.twitch.tv/oauth2/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            # expires_in is seconds
            self._token_expiry = time.time() + float(data.get("expires_in", 3600))
            logger.debug("Obtained app token; expires in %ss", data.get("expires_in"))

    def _headers(self) -> Dict[str, str]:
        self._ensure_token()
        assert self._token is not None
        return {
            "Client-Id": self.client_id,
            "Authorization": f"Bearer {self._token}",
        }

    def get_streams_by_login(self, logins: List[str]) -> List[dict]:
        # Twitch supports multiple user_login params
        if not logins:
            return []
        params: List[Tuple[str, str]] = [("user_login", login) for login in logins]
        url = "https://api.twitch.tv/helix/streams"
        resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        if resp.status_code == 429:
            logger.warning("Rate limited by Twitch (429). Backing off 30s.")
            time.sleep(30)
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        return resp.json().get("data", [])

    def get_games_by_ids(self, ids: List[str]) -> Dict[str, str]:
        if not ids:
            return {}
        # Up to 100 ids per request
        out: Dict[str, str] = {}
        for i in range(0, len(ids), 100):
            chunk = ids[i : i + 100]
            params = [("id", gid) for gid in chunk]
            url = "https://api.twitch.tv/helix/games"
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            resp.raise_for_status()
            for item in resp.json().get("data", []):
                out[item["id"]] = item["name"]
        return out


def send_discord(webhook_url: str, content: str):
    try:
        resp = requests.post(
            webhook_url,
            json={"content": content},
            timeout=30,
        )
        if resp.status_code >= 400:
            logger.error("Discord webhook error %s: %s", resp.status_code, resp.text)
    except Exception as e:
        logger.exception("Failed to send Discord webhook: %s", e)


DEFAULT_STATE_FILE = "state.json"


def load_state(path: str) -> Dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning("Could not read state file %s: %s", path, e)
        return {}


def save_state(path: str, state: Dict[str, str]):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def main():
    load_dotenv()
    client_id = os.getenv("TWITCH_CLIENT_ID")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET")
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    streamers_env = os.getenv("STREAMERS", "").strip()
    poll_interval = int(os.getenv("POLL_INTERVAL", "60"))
    state_file = os.getenv("STATE_FILE", DEFAULT_STATE_FILE)

    if not client_id or not client_secret:
        raise SystemExit("Missing TWITCH_CLIENT_ID or TWITCH_CLIENT_SECRET in env")
    if not webhook_url:
        raise SystemExit("Missing DISCORD_WEBHOOK_URL in env")
    if not streamers_env:
        raise SystemExit("Provide STREAMERS env (comma-separated Twitch logins)")

    streamers = [s.strip().lower() for s in streamers_env.split(",") if s.strip()]
    state = load_state(state_file)  # {login: last_game_id}
    twitch = TwitchClient(client_id, client_secret)
    stop = False

    def handle_sigint(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    logger.info("Monitoring %d streamer(s): %s", len(streamers), ", ".join(streamers))

    # simple cache for game id -> name
    game_name_cache: Dict[str, str] = {}

    while not stop:
        try:
            streams = twitch.get_streams_by_login(streamers)
            # Map login -> game_id for those online
            current: Dict[str, str] = {}
            for s in streams:
                login = s.get("user_login", "").lower()
                game_id = s.get("game_id", "")
                if login:
                    current[login] = game_id

            # Determine which game_ids we need names for
            missing_ids = [
                gid
                for gid in set(current.values())
                if gid and gid not in game_name_cache
            ]
            if missing_ids:
                game_name_cache.update(twitch.get_games_by_ids(missing_ids))

            # Detect changes: only notify when online and game_id changed compared to saved state
            changed: List[Tuple[str, str, str]] = []  # (login, old_id, new_id)
            for login, new_gid in current.items():
                old_gid = state.get(login)
                if new_gid and new_gid != old_gid:
                    changed.append((login, old_gid or "", new_gid))

            # Send notifications
            for login, old_gid, new_gid in changed:
                old_name = (
                    game_name_cache.get(old_gid, "Unknown") if old_gid else "Unknown"
                )
                new_name = (
                    game_name_cache.get(new_gid, "Unknown") if new_gid else "Unknown"
                )
                msg = f"{login} changed category: {old_name} -> {new_name}"
                logger.info(msg)
                send_discord(webhook_url, msg)

            # Update state with online streamers' game ids
            for login in streamers:
                if login in current:
                    state[login] = current[login]
            save_state(state_file, state)

        except Exception as e:
            logger.exception("Polling loop error: %s", e)

        # Sleep with early exit
        for _ in range(poll_interval):
            if stop:
                break
            time.sleep(1)

    logger.info("Exiting. State saved to %s", state_file)


if __name__ == "__main__":
    main()
