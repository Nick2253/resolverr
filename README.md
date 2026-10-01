# Resolverr

Automatically resolve [Seerr](https://github.com/seerr-team/seerr) / [Overseerr](https://github.com/sctx/overseerr) media issues by blacklisting bad releases and triggering replacement searches in [Radarr](https://radarr.video) and [Sonarr](https://sonarr.tv).

## What It Does

When a user reports a media issue in Seerr (bad audio, wrong file, quality problems), Resolverr:

1. **Receives** the Seerr webhook
2. **Identifies** the file in Radarr/Sonarr
3. **Posts a comment** on the Seerr issue with the proposed action and an approval link
4. **Waits for admin approval** (one-click via web UI)
5. **Blacklists** the current release (prevents re-downloading the same bad file)
6. **Deletes** the current file
7. **Triggers** a search for a replacement
8. **Updates** the Seerr issue with status

## Quick Start

```yaml
services:
  resolverr:
    image: ghcr.io/nick2253/resolverr:latest
    container_name: resolverr
    restart: unless-stopped
    environment:
      - RADARR_URL=http://radarr:7878
      - RADARR_API_KEY=your-radarr-api-key
      - SONARR_URL=http://sonarr:8989
      - SONARR_API_KEY=your-sonarr-api-key
      - SEERR_URL=http://seerr:5055
      - SEERR_API_KEY=your-seerr-api-key
      - RESOLVERR_WEBHOOK_SECRET=your-secret
      - BASE_URL=https://resolverr.yourdomain.com
      - AUTO_APPROVE=false
    volumes:
      - resolverr-data:/data
    ports:
      - 8787:8787

volumes:
  resolverr-data:
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RADARR_URL` | Yes | `http://radarr:7878` | Radarr instance URL |
| `RADARR_API_KEY` | Yes | | Radarr API key |
| `SONARR_URL` | Yes | `http://sonarr:8989` | Sonarr instance URL |
| `SONARR_API_KEY` | Yes | | Sonarr API key |
| `SEERR_URL` | Yes | `http://seerr:5055` | Seerr/Overseerr instance URL |
| `SEERR_API_KEY` | Yes | | Seerr API key |
| `RESOLVERR_WEBHOOK_SECRET` | No | | Secret for authenticating Seerr webhooks |
| `BASE_URL` | Yes | `http://resolverr:8787` | Public URL for approval links |
| `AUTO_APPROVE` | No | `false` | Skip approval and act immediately |
| `DISCORD_WEBHOOK_URL` | No | | Discord webhook for notifications |
| `DATABASE_PATH` | No | `/data/resolverr.db` | SQLite database location |

## Seerr Webhook Setup

1. In Seerr, go to **Settings → Notifications → Webhook**
2. Set the webhook URL to `http://resolverr:8787/webhook`
3. Set the Authorization header to `Bearer your-secret` (matching `RESOLVERR_WEBHOOK_SECRET`)
4. Enable the **Issue Created** notification type
5. Use the default JSON payload

## How It Works

### Approval Mode (default)

```
User reports issue in Seerr
  → Resolverr receives webhook
  → Posts comment on Seerr issue with [Approve] link
  → Admin clicks link → one-click approval page
  → Resolverr blacklists release, deletes file, searches for replacement
  → Posts result comment on Seerr issue
```

### Auto Mode

Set `AUTO_APPROVE=true` to skip the approval step. Resolverr will immediately blacklist, delete, and search when an issue is reported.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/webhook` | POST | Seerr webhook receiver |
| `/review/<job_id>` | GET | Approval page for a job |
| `/approve/<job_id>` | POST | Approve a job |
| `/reject/<job_id>` | POST | Reject a job |
| `/jobs` | GET | List recent jobs (JSON) |

## Supported Media

- **Movies** — full support (blacklist + delete + search)
- **TV Episodes** — individual episode support via Seerr's `problemSeason`/`problemEpisode` fields

## License

MIT
