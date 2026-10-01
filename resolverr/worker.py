import logging
import time
import threading

from .config import Config
from .db import (get_jobs_by_status, update_job_status, update_job_arr_info,
                 get_job, JobStatus)
from .radarr import RadarrClient
from .sonarr import SonarrClient
from .seerr import SeerrClient
from .notify import send_discord_notification

log = logging.getLogger(__name__)

ISSUE_TYPE_MAP = {1: "video", 2: "audio", 3: "subtitles", 4: "other"}


def process_approved_jobs():
    jobs = get_jobs_by_status(JobStatus.APPROVED)
    for job in jobs:
        try:
            execute_job(job)
        except Exception as e:
            log.exception("Job %s failed: %s", job["id"], e)
            update_job_status(job["id"], JobStatus.FAILED, str(e))
            _comment_failure(job, str(e))


def execute_job(job):
    seerr = SeerrClient()

    if job["media_type"] == "movie":
        _execute_movie_job(job, seerr)
    elif job["media_type"] == "tv":
        _execute_tv_job(job, seerr)
    else:
        raise ValueError(f"Unknown media type: {job['media_type']}")


def _execute_movie_job(job, seerr):
    radarr = RadarrClient()

    update_job_status(job["id"], JobStatus.BLACKLISTING)
    movie = radarr.get_movie(job["arr_id"])
    if not movie:
        raise ValueError(f"Movie {job['arr_id']} not found in Radarr")

    movie_file = radarr.get_movie_file(job["arr_id"])
    if not movie_file:
        raise ValueError(f"No file for movie {job['arr_id']}")

    blacklisted = radarr.add_to_blocklist(job["arr_id"], movie_file["path"])

    update_job_status(job["id"], JobStatus.DELETING)
    radarr.delete_movie_file(movie_file["id"])

    update_job_status(job["id"], JobStatus.SEARCHING)
    radarr.search_movie(job["arr_id"])

    update_job_status(job["id"], JobStatus.COMPLETED)

    bl_msg = "Release blacklisted." if blacklisted else \
        "No grab history found — could not blacklist release."
    seerr.comment_on_issue(
        job["seerr_issue_id"],
        f"✅ **Resolverr** — Replacement initiated.\n\n"
        f"- {bl_msg}\n"
        f"- File deleted: `{movie_file['path'].split('/')[-1]}`\n"
        f"- Search triggered for new release.\n\n"
        f"The issue will remain open until a replacement is imported."
    )

    send_discord_notification(
        f"🔄 **Resolverr** — Replacing **{job['media_title']}**\n"
        f"Issue: {ISSUE_TYPE_MAP.get(int(job['issue_type']), 'unknown')}\n"
        f"Reported by: {job['reporter']}"
    )


def _execute_tv_job(job, seerr):
    sonarr = SonarrClient()
    metadata = _parse_metadata(job)
    episode_id = metadata.get("episode_id")
    episode_file_id = metadata.get("episode_file_id")

    if not episode_id or not episode_file_id:
        raise ValueError("Missing episode/file ID for TV job")

    update_job_status(job["id"], JobStatus.BLACKLISTING)
    blacklisted = sonarr.add_to_blocklist(episode_id)

    update_job_status(job["id"], JobStatus.DELETING)
    sonarr.delete_episode_file(episode_file_id)

    update_job_status(job["id"], JobStatus.SEARCHING)
    sonarr.search_episode(episode_id)

    update_job_status(job["id"], JobStatus.COMPLETED)

    seerr.comment_on_issue(
        job["seerr_issue_id"],
        f"✅ **Resolverr** — Replacement initiated.\n\n"
        f"- {'Release blacklisted.' if blacklisted else 'No grab history — could not blacklist.'}\n"
        f"- File deleted.\n"
        f"- Search triggered for new release.\n\n"
        f"The issue will remain open until a replacement is imported."
    )

    send_discord_notification(
        f"🔄 **Resolverr** — Replacing **{job['media_title']}**\n"
        f"Issue: {ISSUE_TYPE_MAP.get(int(job['issue_type']), 'unknown')}\n"
        f"Reported by: {job['reporter']}"
    )


def _comment_failure(job, error):
    try:
        seerr = SeerrClient()
        seerr.comment_on_issue(
            job["seerr_issue_id"],
            f"❌ **Resolverr** — Failed to process.\n\nError: {error}\n\n"
            f"An admin will need to handle this manually."
        )
    except Exception:
        log.exception("Failed to comment on issue %d", job["seerr_issue_id"])


def _parse_metadata(job):
    import json
    try:
        return json.loads(job.get("metadata", "{}"))
    except (json.JSONDecodeError, TypeError):
        return {}


def start_worker():
    def _loop():
        while True:
            try:
                process_approved_jobs()
            except Exception:
                log.exception("Worker loop error")
            time.sleep(5)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    log.info("Worker started")
