import json
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi


def extract_video_id(url):
    """Extract the YouTube video ID from a URL."""
    parsed = urlparse(url)

    if parsed.hostname in ("youtu.be", "www.youtu.be"):
        return parsed.path.strip("/").split("/")[0]

    if parsed.hostname and parsed.hostname.endswith("youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]

        if parsed.path.startswith(("/embed/", "/shorts/")):
            return parsed.path.split("/")[2]

    # Also allow a raw video ID.
    if "://" not in url and "/" not in url and "?" not in url:
        return url.strip()

    raise ValueError("Could not extract a YouTube video ID from this URL.")


def get_timestamped_transcript(video_url):
    video_id = extract_video_id(video_url)

    api = YouTubeTranscriptApi()

    try:
        transcript = api.fetch(video_id, languages=["en"])
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
            "end": item.start + item.duration
        })

    result = {
        "video_id": video_id,
        "language": transcript.language,
        "segments": segments
    }

    with open(
        f"transcript_{video_id}.json",
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(result, file, indent=2, ensure_ascii=False)

    print(f"Transcript fetched successfully!")
    print(f"Video ID: {video_id}")
    print(f"Language: {transcript.language} ({transcript.language_code})")
    print(f"Total segments: {len(segments)}")
    print(json.dumps(segments[:5], indent=2, ensure_ascii=True))
    print(f"\nSaved to transcript_{video_id}.json")

    return result


if __name__ == "__main__":
    url = input("Enter a YouTube video URL: ").strip()

    try:
        get_timestamped_transcript(url)
    except Exception as error:
        print(f"Error fetching transcript: {error}")