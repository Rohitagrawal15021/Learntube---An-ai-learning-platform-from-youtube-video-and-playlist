import os
import time
import random
import threading
from dotenv import load_dotenv
from google import genai
from google.genai import errors

# Load .env file
load_dotenv()

# Create Gemini client
client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

# HTTP status codes that are transient and worth retrying.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# ---- Cooldown between Gemini calls -----------------------------------------
# Gemini free-tier rate-limits aggressively.  A small pause between calls
# avoids back-to-back 503s when the pipeline makes many sequential requests.
_COOLDOWN_SECONDS = float(os.getenv("GEMINI_COOLDOWN", "2"))  # configurable
_last_gemini_call = 0.0
# Flask serves requests on many threads; the cooldown bookkeeping and the lazy
# Groq client must be guarded so two threads don't race on them.
_gemini_lock = threading.Lock()

# Exceptions that indicate a bug in our own code (bad kwargs, typo, wrong type)
# rather than a transient outage. These must propagate instead of being retried
# or quietly masked by the Groq fallback — otherwise a real bug looks like
# "Gemini was slow today" forever.
_FATAL_EXCEPTIONS = (
    TypeError, KeyError, IndexError, AttributeError,
    NameError, ValueError, AssertionError,
)

# ---- Groq fallback ----------------------------------------------------------

_groq_client = None


def _get_groq_client():
    """Lazily build the Groq client. Returns None if key/SDK is unavailable."""
    global _groq_client
    if _groq_client is None:
        with _gemini_lock:
            if _groq_client is None:  # re-check inside the lock
                api_key = os.getenv("GROQ_API_KEY")
                if not api_key:
                    return None
                try:
                    from groq import Groq
                except ModuleNotFoundError:
                    return None
                _groq_client = Groq(api_key=api_key)
    return _groq_client


def _looks_blank(response):
    """True when a 'successful' Gemini response carries no usable text.

    Accessing ``response.text`` can itself raise when the request was blocked
    (no candidates returned), so guard it — a blocked response is "blank" too.
    """
    try:
        text = response.text
    except Exception:
        return True
    return not (text and text.strip())


class _GroqResponse:
    """Minimal stand-in exposing `.text`, so Gemini callers work unchanged."""

    def __init__(self, text):
        self.text = text


# Groq model cascade: ordered by reliability for text generation.
# Non-reasoning models are preferred because reasoning models (gpt-oss) waste
# tokens on hidden "thinking" and often return empty responses.
# NOTE: the free tier caps *input tokens per minute* (qwen ITPM ~7000). ~2.4
# chars/token on this content means a request must stay well under ~16k chars;
# we cap at 10k so a single call fits with margin (back-to-back calls are still
# spaced by the retry/backoff + cooldown).
_GROQ_MODEL_CASCADE = [
    # (model_name, max_input_chars, is_reasoning)
    ("qwen/qwen3.8-27b",     10_000, False),  # Non-reasoning, best for translation/summarisation
    ("openai/gpt-oss-20b",   10_000, True),   # Reasoning — may return empty
    ("openai/gpt-oss-120b",  10_000, True),   # Reasoning — may return empty
]


def _groq_fallback(model=None, contents=None, config=None, **_ignored):
    """Answer the same prompt with Groq, cascading through models on failure."""
    groq = _get_groq_client()
    if groq is None:
        return None

    raw_prompt = contents if isinstance(contents, str) else str(contents)

    temperature = getattr(config, "temperature", None)
    max_tokens = getattr(config, "max_output_tokens", None)
    want_json = getattr(config, "response_mime_type", None) == "application/json"

    # Build the cascade: start with the env-configured model (if set and in
    # the cascade), then fall through the rest in order.
    env_model = os.getenv("GROQ_MODEL", "")
    cascade = list(_GROQ_MODEL_CASCADE)
    # If the user configured a specific model, move it to the front
    if env_model:
        cascade = [
            entry for entry in cascade if entry[0] == env_model
        ] + [
            entry for entry in cascade if entry[0] != env_model
        ]
        # If env model isn't in our list, add it at the front with safe defaults
        if not any(entry[0] == env_model for entry in _GROQ_MODEL_CASCADE):
            is_reasoning = any(tag in env_model.lower() for tag in ("gpt-oss", "o1", "o3", "deepseek-r1"))
            cascade.insert(0, (env_model, 20_000, is_reasoning))

    last_error = None
    for model_name, max_input_chars, is_reasoning in cascade:
        # Truncate prompt to fit this model's TPM budget
        prompt = raw_prompt
        if len(prompt) > max_input_chars:
            print(f"Groq ({model_name}): truncating prompt from {len(prompt)} to {max_input_chars} chars.")
            prompt = prompt[:max_input_chars]

        messages = []
        if want_json:
            messages.append({
                "role": "system",
                "content": "You must respond with valid JSON only. No prose, no markdown.",
            })
        messages.append({"role": "user", "content": prompt})

        call = {
            "model": model_name,
            "messages": messages,
            "temperature": 0 if temperature is None else temperature,
        }
        if is_reasoning:
            # Reasoning models use hidden "thinking tokens" that count against
            # max_completion_tokens.  Always set a generous floor so the model
            # has room for both thinking AND visible output — even when the
            # caller didn't specify max_output_tokens.
            call["max_completion_tokens"] = max(max_tokens or 0, 2048)
        elif max_tokens:
            call["max_completion_tokens"] = max_tokens
        if want_json:
            call["response_format"] = {"type": "json_object"}

        # The one reliable fallback model (qwen) can hit Groq's own per-minute
        # rate limit during a burst. Retry it a couple of times with backoff
        # before giving up — otherwise a momentary Groq 429 drops us all the way
        # through to None and the original Gemini error surfaces.
        text = None
        for groq_attempt in range(3):
            try:
                completion = groq.chat.completions.create(**call)
                text = completion.choices[0].message.content or ""
                break
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                transient = ("429" in msg or "rate" in msg or "resource" in msg
                             or "too many" in msg or "503" in msg)
                if transient and groq_attempt < 2:
                    delay = 2.0 * (groq_attempt + 1) + random.uniform(0, 1)
                    print(f"Groq ({model_name}) rate-limited — retry {groq_attempt + 1}/2 in {delay:.1f}s...")
                    time.sleep(delay)
                    continue
                print(f"Groq ({model_name}) failed: {e}")
                break

        if text and text.strip():
            print(f"Gemini unavailable — fell back to Groq ({model_name}).")
            return _GroqResponse(text)
        if text is not None:
            print(f"Groq ({model_name}) returned empty response, trying next model...")

    if last_error:
        print(f"All Groq models exhausted. Last error: {last_error}")
    return None


def generate_with_retry(max_retries=2, base_delay=1.0, max_delay=8.0, **kwargs):
    """
    Wrapper around client.models.generate_content that retries on transient
    errors (e.g. 503 UNAVAILABLE "high demand") using exponential backoff with
    jitter, then falls back to Groq if Gemini is still unavailable.

    Defaults are kept deliberately short (2 quick retries, ~3s total) because
    we have a capable Groq fallback: when Gemini is broadly overloaded it's far
    better to fail over to Groq in a few seconds than to sleep ~60s per call.
    A real run makes many LLM calls, so slow per-call backoff stacks into
    multi-minute hangs behind the synchronous /process request.

    Pass the same arguments you would pass to client.models.generate_content,
    e.g. model=..., contents=..., config=...

    Raises the last Gemini error if retries are exhausted and Groq is not
    configured / also fails.
    """
    last_error = None
    global _last_gemini_call
    for attempt in range(max_retries + 1):
        try:
            # Respect a global cooldown between calls to avoid 503 rate-limits.
            # Guarded by a lock because Flask serves requests on many threads;
            # without it two threads read the same stale timestamp and both skip
            # the pause.
            with _gemini_lock:
                elapsed = time.time() - _last_gemini_call
                if elapsed < _COOLDOWN_SECONDS:
                    time.sleep(_COOLDOWN_SECONDS - elapsed)
                _last_gemini_call = time.time()

            response = client.models.generate_content(**kwargs)

            # A 200 with empty / blocked content is a failure, not a success.
            # Previously it slipped through and crashed callers that do
            # `response.text.strip()`; now it fails over to Groq like any outage.
            if _looks_blank(response):
                last_error = RuntimeError("Gemini returned an empty or blocked response")
                print("Gemini returned an empty/blocked response — trying Groq fallback.")
                break

            return response

        except _FATAL_EXCEPTIONS:
            # A genuine programming error (bad kwargs, wrong type, ...). Do NOT
            # retry or silently fall back to Groq — that only hides the real bug.
            raise

        except errors.APIError as e:
            last_error = e
            status = getattr(e, "code", None) or getattr(e, "status_code", None)
            # Non-retryable status, or last attempt used: stop hitting Gemini.
            if status not in _RETRYABLE_STATUS or attempt == max_retries:
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay += random.uniform(0, delay * 0.25)
            print(
                f"Gemini returned {status}. Retry {attempt + 1}/{max_retries} "
                f"in {delay:.1f}s..."
            )
            time.sleep(delay)

        except Exception as e:
            # Transient network / SSL errors (httpx.ConnectError, SSL
            # UNEXPECTED_EOF, socket timeouts) that aren't APIError subclasses.
            # Genuine code bugs were already filtered out above.
            last_error = e
            if attempt == max_retries:
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay += random.uniform(0, delay * 0.25)
            print(
                f"Gemini connection error: {type(e).__name__}. "
                f"Retry {attempt + 1}/{max_retries} in {delay:.1f}s..."
            )
            time.sleep(delay)

    # Gemini exhausted (or returned empty) — try Groq before giving up.
    fallback = _groq_fallback(**kwargs)
    if fallback is not None:
        return fallback

    raise last_error