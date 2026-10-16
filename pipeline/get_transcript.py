import re

from youtube_transcript_api import YouTubeTranscriptApi

# A YouTube video ID is exactly 11 chars from this alphabet. Validating here
# stops malformed/hostile values (e.g. "../../etc") from flowing into cache
# file paths and download routes downstream.
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def get_video_id(url):
    if "youtu.be" in url:
        video_id = url.split("/")[-1].split("?")[0]
    elif "v=" in url:
        video_id = url.split("v=")[1].split("&")[0]
    else:
        raise ValueError("Couldn't parse video ID from URL")

    video_id = video_id.strip()
    if not _VIDEO_ID_RE.match(video_id):
        raise ValueError("Parsed an invalid YouTube video ID from the URL")

    return video_id

def get_transcript(url):
    video_id = get_video_id(url)
    ytt_api = YouTubeTranscriptApi()

    try:
        # First try to get a manual or auto-generated English transcript
        fetched_transcript = ytt_api.fetch(video_id, languages=['en'])
    except Exception:
        # Fallback: get whatever language IS available
        transcript_list = ytt_api.list(video_id)
        try:
            first_available = next(iter(transcript_list))
        except StopIteration:
            raise ValueError("No transcript is available for this video.")

        # If it's not English, ask YouTube to translate it to English for us!
        if first_available.is_translatable:
            fetched_transcript = first_available.translate('en').fetch()
        else:
            fetched_transcript = first_available.fetch()

    full_text = " ".join([snippet.text for snippet in fetched_transcript])
    return full_text


def get_transcript_segments(url):
    """Like get_transcript, but returns timestamped segments:
    [{text, start, duration, end}, ...]. Lets the quiz anchor each question to
    the exact second in the video, for ANY video (not just pre-extracted ones).
    """
    video_id = get_video_id(url)
    ytt_api = YouTubeTranscriptApi()
    try:
        fetched = ytt_api.fetch(video_id, languages=['en'])
    except Exception:
        transcript_list = ytt_api.list(video_id)
        try:
            first = next(iter(transcript_list))
        except StopIteration:
            raise ValueError("No transcript is available for this video.")
        fetched = first.translate('en').fetch() if first.is_translatable else first.fetch()

    segments = []
    for snippet in fetched:
        start = float(getattr(snippet, 'start', 0) or 0)
        dur = float(getattr(snippet, 'duration', 0) or 0)
        segments.append({
            'text': snippet.text,
            'start': start,
            'duration': dur,
            'end': start + dur,
        })
    return segments


if __name__ == "__main__":
    url = input("Paste a YouTube URL: ")
    try:
        text = get_transcript(url)
        print(f"\nTranscript length: {len(text)} characters\n")
        print(text[:1500] + "...")
    except Exception as e:
        print(f"Error: {e}")