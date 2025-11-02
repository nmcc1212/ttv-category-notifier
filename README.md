# Twitch Category Change Notifier -> Discord

A tiny Python script that polls Twitch for one or more streamers and posts to a Discord webhook whenever a streamer's category (game) changes.

## Features

- Monitors one or many Twitch channels by login name
- Posts a message to a Discord webhook when the category changes
- Persists last seen categories in `state.json` to survive restarts
- Handles offline/online transitions gracefully

## Setup

1. Create a Twitch Application to get Client ID and Secret:

   - Visit <https://dev.twitch.tv/console/apps> and click "Register Your Application".
   - OAuth Redirect URL can be anything for this script (not used); e.g. `http://localhost`.

2. Create a Discord Webhook URL:

   - In your server: Server Settings -> Integrations -> Webhooks -> New Webhook

3. Configure environment variables:
   - Copy `.env.example` to `.env` and fill in values.

```dotenv
TWITCH_CLIENT_ID=your_twitch_client_id
TWITCH_CLIENT_SECRET=your_twitch_client_secret
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
STREAMERS=streamer1,streamer2
POLL_INTERVAL=60
```

## Install & Run

- Requires Python 3.9+

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

The script will run continuously and poll at the configured interval.

## Docker usage

You can run this in Docker; `STATE_FILE` defaults to `/data/state.json`, so bind-mount a host directory for persistence.

### Build

```bash
docker build -t ttv-category-notifier:latest .
```

### Run

```bash
# assumes you have .env in the project root
docker run --name ttv-category-notifier \
   --env-file .env \
   -v $(pwd)/data:/data \
   -d ttv-category-notifier:latest
```

### Docker Compose

```bash
docker compose up -d --build
```

Logs:

```bash
docker compose logs -f
```

## Notes

- This script uses the Twitch Helix API with an app access token (no user auth required).
- If you revoke your app, regenerate the Client Secret.
- State is saved in `state.json` in the project directory.

## Systemd/launchd

On macOS, consider using `launchd` or a process manager like `pm2` or `forever` (via a wrapper) to keep it running. For dev, running in a terminal is fine.
