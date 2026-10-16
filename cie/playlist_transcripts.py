
import json
import random
import re
import time
from pathlib import Path

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi


OUTPUT_DIR = Path("data/transcripts")
LANGUAGES = ["en"]

# Rate-limiting settings to avoid YouTube IP bans
BASE_DELAY = (3, 6)          # Random delay range (seconds) between videos
COOLDOWN_EVERY = 10         # Take a long break after every N videos
COOLDOWN_SECONDS = 30       # Duration of the long break
MAX_RETRIES = 3             # Retry count per video on transient errors
RETRY_BACKOFF = [15, 30, 60]  # Exponential backoff wait (seconds) per retry


def safe_filename(value):
    """Make a string safe to use as a filename."""
    return re.sub(r'[<>:"/\\|?*]', "_", str(value))


def get_playlist_videos(playlist_url):
    """Get video IDs and titles without downloading video files."""

    options = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "ignoreerrors": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        playlist = ydl.extract_info(
            playlist_url,
            download=False
        )

    if not playlist:
        raise ValueError("Could not read this playlist.")

    videos = []

    for item in playlist.get("entries") or []:
        if not item or not item.get("id"):
            continue

        videos.append({
            "video_id": item["id"],
            "title": item.get("title") or item["id"],
            "url": (
                item.get("url")
                if str(item.get("url", "")).startswith("http")
                else f"https://www.youtube.com/watch?v={item['id']}"
            ),
        })

    return playlist, videos


def _fetch_transcript_once(video_id):
    """Single attempt to fetch caption segments with timestamps."""

    api = YouTubeTranscriptApi()

    try:
        transcript = api.fetch(video_id, languages=LANGUAGES)
    except Exception:
        # English not available — pick the first available language
        transcript_list = api.list(video_id)
        first = next(iter(transcript_list))
        transcript = api.fetch(video_id, languages=[first.language_code])

    segments = []

    for item in transcript:
        segments.append({
            "text": item.text,
            "start": item.start,
            "duration": item.duration,
            "end": item.start + item.duration,
        })

    return {
        "video_id": video_id,
        "language": getattr(transcript, "language", "unknown"),
        "language_code": getattr(transcript, "language_code", "unknown"),
        "segments": segments,
    }


def fetch_transcript(video_id):
    """Fetch transcript with automatic retry and exponential backoff."""

    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            return _fetch_transcript_once(video_id)
        except Exception as error:
            last_error = error
            error_str = str(error).lower()

            # Only retry on rate-limit / IP-block errors
            is_block = any(kw in error_str for kw in [
                "blocking", "blocked", "too many", "ip",
                "request", "429", "403",
            ])

            if not is_block or attempt >= MAX_RETRIES:
                raise

            wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
            print(
                f"  ⏳ YouTube rate-limited (attempt {attempt + 1}/{MAX_RETRIES}). "
                f"Waiting {wait}s before retry..."
            )
            time.sleep(wait)

    raise last_error


def safe_print(text):
    """Print text safely on Windows consoles that can't handle Unicode."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def process_playlist(playlist_url):
    playlist, videos = get_playlist_videos(playlist_url)

    playlist_id = safe_filename(
        playlist.get("id") or "unknown_playlist"
    )
    playlist_title = playlist.get("title") or "YouTube Playlist"

    output_folder = OUTPUT_DIR / playlist_id
    output_folder.mkdir(parents=True, exist_ok=True)

    manifest = {
        "playlist_id": playlist_id,
        "playlist_title": playlist_title,
        "total_videos": len(videos),
        "videos": [],
    }

    safe_print(f"Playlist: {playlist_title}")
    print(f"Videos found: {len(videos)}")

    for position, video in enumerate(videos, start=1):
        video_id = video["video_id"]
        title = video["title"]

        transcript_path = (
            output_folder / f"{safe_filename(video_id)}.json"
        )

        record = {
            "position": position,
            "video_id": video_id,
            "title": title,
            "url": video["url"],
            "status": "failed",
            "transcript_file": str(transcript_path),
            "error": None,
        }

        safe_print(f"\n[{position}/{len(videos)}] {title}")

        # Reuse a transcript already saved successfully.
        if transcript_path.exists():
            try:
                with open(transcript_path, encoding="utf-8") as file:
                    existing = json.load(file)

                if existing.get("segments"):
                    record["status"] = "cached"
                    record["segment_count"] = len(existing["segments"])
                    manifest["videos"].append(record)
                    print("Transcript already exists; skipping.")
                    continue

            except (OSError, json.JSONDecodeError):
                pass

        try:
            transcript_data = fetch_transcript(video_id)

            transcript_data["title"] = title
            transcript_data["url"] = video["url"]
            transcript_data["position"] = position

            with open(
                transcript_path,
                "w",
                encoding="utf-8"
            ) as file:
                json.dump(
                    transcript_data,
                    file,
                    indent=2,
                    ensure_ascii=False
                )

            record["status"] = "success"
            record["language"] = transcript_data.get("language", "unknown")
            record["segment_count"] = len(
                transcript_data["segments"]
            )

            print(
                f"Saved {record['segment_count']} segments "
                f"(language: {record['language']})"
            )

        except Exception as error:
            record["error"] = str(error)
            safe_print(f"Transcript unavailable: {error}")

        manifest["videos"].append(record)

        # Smart rate-limiting to avoid YouTube IP bans
        if position % COOLDOWN_EVERY == 0 and position < len(videos):
            print(
                f"\n  🧊 Cooldown: pausing {COOLDOWN_SECONDS}s after "
                f"{position} videos to avoid IP blocking..."
            )
            time.sleep(COOLDOWN_SECONDS)
        else:
            delay = random.uniform(*BASE_DELAY)
            time.sleep(delay)

        # Save progress after every video, including failures.
        manifest_path = output_folder / "manifest.json"

        with open(
            manifest_path,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                manifest,
                file,
                indent=2,
                ensure_ascii=False
            )

    # Save the final report.
    manifest_path = output_folder / "manifest.json"

    with open(
        manifest_path,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            manifest,
            file,
            indent=2,
            ensure_ascii=False
        )

    successful = sum(
        v["status"] in ("success", "cached")
        for v in manifest["videos"]
    )

    failed = sum(
        v["status"] == "failed"
        for v in manifest["videos"]
    )

    print("\n--- Playlist processing complete ---")
    print(f"Total videos: {len(videos)}")
    print(f"Transcripts available: {successful}")
    print(f"Failed transcripts: {failed}")
    print(f"Output folder: {output_folder}")
    print(f"Manifest: {manifest_path}")

    return playlist_id


if __name__ == "__main__":
    url = input("Paste the YouTube playlist URL: ").strip()

    try:
        process_playlist(url)
    except Exception as error:
        safe_print(f"Playlist processing failed: {error}")