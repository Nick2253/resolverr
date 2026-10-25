import logging
import time
import threading

from .config import Config
from .db import (get_jobs_by_status, update_job_status, update_job_arr_info,
                 get_job, JobStatus)
from .radarr import RadarrClient
from .sonarr import SonarrClient
from .bazarr import BazarrClient
from .seerr import SeerrClient
from .notify import send_discord_notification

log = logging.getLogger(__name__)

ISSUE_TYPE_MAP = {
    1: "video", 2: "audio", 3: "subtitles", 4: "other",
    "1": "video", "2": "audio", "3": "subtitles", "4": "other",
    "VIDEO": "video", "AUDIO": "audio", "SUBTITLES": "subtitles",
    "OTHER": "other",
}


def _issue_type(job):
    return ISSUE_TYPE_MAP.get(job["issue_type"], "unknown")


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
    issue_type = _issue_type(job)

    if issue_type == "subtitles":
        _execute_subtitle_job(job, seerr)
    elif job["media_type"] == "movie":
        _execute_movie_job(job, seerr)
    elif job["media_type"] == "tv":
        _execute_tv_job(job, seerr)
    else:
        raise ValueError(f"Unknown media type: {job['media_type']}")


def _execute_subtitle_job(job, seerr):
    bazarr = BazarrClient()
    metadata = _parse_metadata(job)

    if job["media_type"] == "movie":
        media_ids = {"radarrid": job["arr_id"]}
        movie = bazarr.get_movie(job["arr_id"])
        items = [(media_ids, movie)] if movie else []
        scope = "movie"
    elif job["media_type"] == "tv":
        media_ids = {"seriesid": job["arr_id"]}
        episodes = bazarr.get_series_episodes(job["arr_id"])
        # Seerr reports can name one episode, a whole season, or neither
        if metadata.get("episode_id"):
            episodes = [e for e in episodes
                        if e.get("sonarrEpisodeId") == metadata["episode_id"]]
            scope = f"S{metadata['season']:02d}E{metadata['episode']:02d}"
        elif metadata.get("season"):
            episodes = [e for e in episodes
                        if e.get("season") == metadata["season"]]
            scope = f"season {metadata['season']}"
        else:
            scope = "all episodes"
        items = [({"seriesid": job["arr_id"],
                   "episodeid": e["sonarrEpisodeId"]}, e) for e in episodes]
    else:
        raise ValueError(f"Unknown media type: {job['media_type']}")

    if not items:
        raise ValueError(f"Bazarr has no {scope} for {job['media_title']}")

    update_job_status(job["id"], JobStatus.BLACKLISTING)
    blacklisted, deleted = [], []
    for ids, item in items:
        for sub in item.get("subtitles", []):
            # Embedded subtitles have no path; Bazarr can't remove those
            if sub.get("code2") != "en" or not sub.get("path"):
                continue
            download = bazarr.find_download(ids, sub["path"])
            if download:
                bazarr.blacklist(ids, download)
                blacklisted.append(download)
            else:
                # Not downloaded by Bazarr, so there's nothing to blacklist
                update_job_status(job["id"], JobStatus.DELETING)
                bazarr.delete_subtitle(
                    ids,
                    language="en",
                    forced="True" if sub.get("forced") else "False",
                    hi="True" if sub.get("hi") else "False",
                    path=sub["path"],
                )
                deleted.append(sub["path"])

    # Each blacklist already searches again; search for the rest ourselves
    update_job_status(job["id"], JobStatus.SEARCHING)
    if deleted or not blacklisted:
        bazarr.search_missing(media_ids)

    update_job_status(job["id"], JobStatus.COMPLETED)

    if blacklisted or deleted:
        lines = []
        if blacklisted:
            providers = sorted({d["provider"] for d in blacklisted})
            lines.append(f"Blacklisted {len(blacklisted)} subtitle(s) in "
                         f"Bazarr ({', '.join(providers)}).")
        if deleted:
            lines.append(f"Deleted {len(deleted)} subtitle(s) Bazarr "
                         f"didn't download.")
        summary = "\n".join(lines)
    else:
        summary = "No English subtitles were present."
    seerr.comment_on_issue(
        job["seerr_issue_id"],
        f"Resolverr — Subtitle replacement initiated ({scope}).\n\n"
        f"{summary}\n"
        f"Bazarr is searching for new subtitles.\n\n"
        f"The issue will remain open until replacement subtitles are found."
    )

    send_discord_notification(
        f"Resolverr — Replacing subtitles for {job['media_title']} "
        f"({scope})\n"
        f"Reported by: {job['reporter']}"
    )


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
        f"Resolverr — Replacement initiated.\n\n"
        f"{bl_msg}\n"
        f"File deleted: {movie_file['path'].split('/')[-1]}\n"
        f"Search triggered for new release.\n\n"
        f"The issue will remain open until a replacement is imported."
    )

    send_discord_notification(
        f"Resolverr — Replacing {job['media_title']}\n"
        f"Issue: {_issue_type(job)}\n"
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
        f"Resolverr — Replacement initiated.\n\n"
        f"{'Release blacklisted.' if blacklisted else 'No grab history — could not blacklist.'}\n"
        f"File deleted.\n"
        f"Search triggered for new release.\n\n"
        f"The issue will remain open until a replacement is imported."
    )

    send_discord_notification(
        f"Resolverr — Replacing {job['media_title']}\n"
        f"Issue: {_issue_type(job)}\n"
        f"Reported by: {job['reporter']}"
    )


def _comment_failure(job, error):
    try:
        seerr = SeerrClient()
        seerr.comment_on_issue(
            job["seerr_issue_id"],
            f"Resolverr — Failed to process.\n\nError: {error}\n\n"
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
