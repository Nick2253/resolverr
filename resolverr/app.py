import json
import logging
import re
import time
import uuid

from flask import Flask, request, jsonify, render_template_string

from .config import Config
from .db import (init_db, create_job, get_job, get_job_by_issue,
                 update_job_status, update_job_arr_info, get_recent_jobs,
                 get_jobs_by_status, get_other_jobs_for_media, JobStatus)
from .radarr import RadarrClient
from .sonarr import SonarrClient
from .seerr import SeerrClient
from .worker import start_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

ISSUE_TYPE_MAP = {
    1: "video", 2: "audio", 3: "subtitles", 4: "other",
    "1": "video", "2": "audio", "3": "subtitles", "4": "other",
    "VIDEO": "video", "AUDIO": "audio", "SUBTITLES": "subtitles",
    "OTHER": "other",
}


# Reporters often pick the wrong type ("video" for missing subtitles)
SUBTITLE_WORDS = re.compile(r"\b(subtitles?|subs)\b", re.IGNORECASE)


def _issue_label(issue_type):
    if issue_type is None:
        return "unknown"
    return ISSUE_TYPE_MAP.get(issue_type,
           ISSUE_TYPE_MAP.get(str(issue_type).upper(), "unknown"))

APPROVE_PAGE = """<!doctype html>
<title>Resolverr — {{ job.media_title }}</title>
<style>
  :root { --bg: #1a1a2e; --card: #16213e; --accent: #0f3460;
          --green: #2ecc71; --red: #e74c3c; --text: #e0e0e0; }
  body { font-family: system-ui, sans-serif; background: var(--bg);
         color: var(--text); margin: 0; padding: 2rem;
         display: flex; justify-content: center; }
  .card { background: var(--card); border-radius: 12px; padding: 2rem;
          max-width: 500px; width: 100%; }
  h1 { margin: 0 0 0.5rem; font-size: 1.4rem; }
  .meta { color: #888; font-size: 0.9rem; margin-bottom: 1.5rem; }
  .detail { background: var(--accent); border-radius: 8px; padding: 1rem;
            margin-bottom: 1.5rem; font-size: 0.9rem; }
  .detail dt { color: #888; margin-top: 0.5rem; }
  .detail dd { margin: 0.2rem 0 0; }
  .actions { display: flex; gap: 1rem; }
  .btn { flex: 1; padding: 0.8rem; border: none; border-radius: 8px;
         font-size: 1rem; font-weight: 600; cursor: pointer; }
  .btn-approve { background: var(--green); color: #fff; }
  .btn-reject { background: var(--red); color: #fff; }
  .btn:hover { opacity: 0.9; }
  .done { text-align: center; padding: 2rem 0; }
  .done h2 { color: var(--green); }
</style>
{% if acted %}
<div class="card">
  <div class="done">
    <h2>{{ "✅ Approved" if action == "approve" else "❌ Rejected" }}</h2>
    <p>{{ job.media_title }}</p>
  </div>
</div>
{% else %}
<div class="card">
  <h1>{{ job.media_title }}</h1>
  <div class="meta">Reported by {{ job.reporter }} · {{ issue_label }}</div>
  <div class="detail">
    <dl>
      <dt>File</dt>
      <dd>{{ file_name }}</dd>
      <dt>Action</dt>
      <dd>{{ action_desc }}</dd>
    </dl>
  </div>
  <div class="actions">
    <form method="POST" action="/approve/{{ job.id }}">
      <button class="btn btn-approve" type="submit">Approve</button>
    </form>
    <form method="POST" action="/reject/{{ job.id }}">
      <button class="btn btn-reject" type="submit">Reject</button>
    </form>
  </div>
</div>
{% endif %}
"""


@app.before_request
def _check_webhook_secret():
    if request.path == "/webhook" and Config.WEBHOOK_SECRET:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {Config.WEBHOOK_SECRET}":
            return jsonify({"error": "unauthorized"}), 401


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "no payload"}), 400

    notification_type = payload.get("notification_type", "")
    if notification_type not in ("ISSUE_CREATED", "ISSUE_REOPENED"):
        log.info("Ignoring notification type: %s", notification_type)
        return jsonify({"status": "ignored"})

    issue = payload.get("issue", {})
    media = payload.get("media", {})
    extra = payload.get("extra", [])

    issue_id = issue.get("issue_id")
    if not issue_id:
        return jsonify({"error": "missing issue_id"}), 400
    issue_id = int(issue_id)

    if get_job_by_issue(issue_id):
        log.info("Duplicate webhook for issue %s — ignoring", issue_id)
        return jsonify({"status": "duplicate"})

    media_type = media.get("media_type", "")
    media_title = media.get("tmdbId") or media.get("tvdbId") or "Unknown"
    if "title" in payload.get("subject", ""):
        media_title = payload.get("subject", media_title)

    job_id = str(uuid.uuid4())[:8]
    issue_type = issue.get("issue_type", 4)
    reporter = issue.get("reportedBy_username") or \
        issue.get("reportedBy_email") or "unknown"

    reclassified = False
    if _issue_label(issue_type) != "subtitles" and \
            _mentions_subtitles(issue_id, payload):
        log.info("Issue #%d is filed as %s but mentions subtitles — "
                 "treating it as a subtitle issue", issue_id,
                 _issue_label(issue_type))
        issue_type = "SUBTITLES"
        reclassified = True

    title = _resolve_title(media, payload)

    log.info("New issue #%d: %s — %s (reported by %s)",
             issue_id, title, ISSUE_TYPE_MAP.get(issue_type, "unknown"),
             reporter)

    arr_id, file_id, file_path, release_name, metadata = \
        _lookup_arr_info(media_type, media, issue, extra)

    create_job(job_id, issue_id, media_type, title, issue_type, reporter,
               arr_id, file_id, file_path, release_name)

    if metadata:
        from .db import get_db
        with get_db() as db:
            db.execute("UPDATE jobs SET metadata = ?, updated_at = ? "
                       "WHERE id = ?",
                       (json.dumps(metadata), time.time(), job_id))
            db.commit()

    # Repeat reports on the same media suggest the automatic fix didn't
    # work (or something bigger is wrong), so a person has to look
    hold_reason = None
    since = time.time() - Config.AUTO_APPROVE_REPEAT_DAYS * 86400
    recent = get_other_jobs_for_media(job_id, media_type, arr_id, title,
                                      since) if Config.AUTO_APPROVE else []
    if recent:
        others = ", ".join(f"#{j['seerr_issue_id']}" for j in recent)
        hold_reason = (f"Not auto-approved: {title} already had issue "
                       f"{others} in the last "
                       f"{Config.AUTO_APPROVE_REPEAT_DAYS} days.")

    if Config.AUTO_APPROVE and not hold_reason:
        update_job_status(job_id, JobStatus.APPROVED)
        log.info("Auto-approved job %s", job_id)
    else:
        if hold_reason:
            log.info("Holding job %s for review: %s", job_id, hold_reason)
        approve_url = f"{Config.BASE_URL}/review/{job_id}"
        nl = "\n"
        try:
            seerr = SeerrClient()
            file_display = file_path.split("/")[-1] if file_path else \
                "Unknown file"
            issue_label = _issue_label(issue_type)
            if issue_label == "subtitles":
                action_desc = "Blacklist current subtitles in Bazarr, search for new ones"
            else:
                action_desc = "Blacklist release, delete file, search replacement"
            seerr.comment_on_issue(
                issue_id,
                f"Resolverr — Issue received.\n\n"
                f"Media: {title}\n"
                f"File: {file_display}\n"
                f"Issue type: {issue_label}"
                f"{' (the report mentions subtitles)' if reclassified else ''}\n"
                f"Action: {action_desc}\n\n"
                f"{hold_reason + nl if hold_reason else ''}"
                f"Review & Approve: {approve_url}"
            )
        except Exception:
            log.exception("Failed to comment on issue %d", issue_id)

    return jsonify({"status": "created", "job_id": job_id})


@app.route("/review/<job_id>")
def review(job_id):
    job = get_job(job_id)
    if not job:
        return "Job not found", 404
    if job["status"] != JobStatus.PENDING:
        return render_template_string(APPROVE_PAGE, job=job, acted=True,
                                      action=job["status"])

    file_name = job["file_path"].split("/")[-1] if job["file_path"] else \
        "Unknown"
    issue_label = _issue_label(job["issue_type"])
    if issue_label == "subtitles":
        action_desc = "Blacklist current subtitles in Bazarr, search for new ones"
    else:
        action_desc = "Blacklist release, delete file, search for replacement"
    return render_template_string(APPROVE_PAGE, job=job, acted=False,
                                  file_name=file_name,
                                  issue_label=issue_label,
                                  action_desc=action_desc)


@app.route("/approve/<job_id>", methods=["POST"])
def approve(job_id):
    job = get_job(job_id)
    if not job:
        return "Job not found", 404
    if job["status"] != JobStatus.PENDING:
        return render_template_string(APPROVE_PAGE, job=job, acted=True,
                                      action="approve")

    update_job_status(job_id, JobStatus.APPROVED)
    log.info("Job %s approved", job_id)
    job["status"] = JobStatus.APPROVED
    return render_template_string(APPROVE_PAGE, job=job, acted=True,
                                  action="approve")


@app.route("/reject/<job_id>", methods=["POST"])
def reject(job_id):
    job = get_job(job_id)
    if not job:
        return "Job not found", 404

    update_job_status(job_id, JobStatus.REJECTED)
    log.info("Job %s rejected", job_id)

    try:
        seerr = SeerrClient()
        seerr.comment_on_issue(
            job["seerr_issue_id"],
            "Resolverr — Admin declined automatic replacement. "
            "This issue will be handled manually."
        )
    except Exception:
        log.exception("Failed to comment rejection")

    job["status"] = JobStatus.REJECTED
    return render_template_string(APPROVE_PAGE, job=job, acted=True,
                                  action="reject")


@app.route("/jobs")
def list_jobs():
    jobs = get_recent_jobs()
    return jsonify(jobs)


def _mentions_subtitles(issue_id, payload):
    """Whether the reporter's description talks about subtitles."""
    text = payload.get("message") or ""
    if not SUBTITLE_WORDS.search(text):
        # The webhook template may not carry the description; ask Seerr
        try:
            comments = SeerrClient().get_issue(issue_id).get("comments") or []
            text = comments[0].get("message", "") if comments else ""
        except Exception:
            log.exception("Failed to fetch issue %d from Seerr", issue_id)
    return bool(SUBTITLE_WORDS.search(text))


def _resolve_title(media, payload):
    if "subject" in payload and payload["subject"]:
        return payload["subject"]
    return media.get("title", media.get("name", "Unknown"))


def _lookup_arr_info(media_type, media, issue, extra):
    metadata = {}
    try:
        if media_type == "movie":
            radarr = RadarrClient()
            tmdb_id = media.get("tmdbId")
            if not tmdb_id:
                return None, None, None, None, metadata
            movie = radarr.find_movie_by_tmdb(tmdb_id)
            if not movie:
                return None, None, None, None, metadata
            movie_file = radarr.get_movie_file(movie["id"])
            if not movie_file:
                return movie["id"], None, None, None, metadata
            return (movie["id"], movie_file["id"], movie_file.get("path"),
                    movie_file.get("sceneName") or
                    movie_file.get("relativePath"), metadata)

        elif media_type == "tv":
            sonarr = SonarrClient()
            tvdb_id = media.get("tvdbId")
            if not tvdb_id:
                return None, None, None, None, metadata
            series = sonarr.find_series_by_tvdb(tvdb_id)
            if not series:
                return None, None, None, None, metadata

            # Seerr puts these in "extra" and omits them when 0 (all)
            affected = {e.get("name"): e.get("value") for e in extra or []}
            problem_season = int(affected.get("Affected Season") or 0)
            problem_episode = int(affected.get("Affected Episode") or 0)
            if problem_season:
                metadata["season"] = problem_season

            if problem_season and problem_episode:
                episodes = sonarr.get_episodes(series["id"], problem_season)
                target = next(
                    (e for e in episodes
                     if e.get("episodeNumber") == problem_episode),
                    None
                )
                if target and target.get("episodeFileId"):
                    ep_file = sonarr.get_episode_file(
                        target["episodeFileId"])
                    metadata["episode_id"] = target["id"]
                    metadata["episode_file_id"] = target["episodeFileId"]
                    metadata["season"] = problem_season
                    metadata["episode"] = problem_episode
                    return (series["id"], target["episodeFileId"],
                            ep_file.get("path"),
                            ep_file.get("sceneName") or
                            ep_file.get("relativePath"), metadata)

            return series["id"], None, None, None, metadata

    except Exception:
        log.exception("Failed to look up %s in *arr", media_type)
    return None, None, None, None, metadata


def create_app():
    init_db()
    start_worker()
    return app
