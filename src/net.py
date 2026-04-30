"""Hardened HTTP client for LSMM. Use instead of urllib directly."""
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
RETRY_STATUSES = {502, 503, 504}
MAX_RETRIES = 3
BACKOFF_BASE = 1.5


def request(
    url: str,
    *,
    headers: dict | None = None,
    data: bytes | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
) -> bytes:
    """HTTP request with timeout and retry on transient errors.

    Raises urllib.error.HTTPError on non-retryable HTTP errors,
    urllib.error.URLError on connection failures after retries exhausted.
    """
    req = urllib.request.Request(url, data=data, headers=headers or {})
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUSES or attempt >= max_retries - 1:
                raise
            wait = BACKOFF_BASE ** attempt
            log.warning("HTTP %d on %s, retry %d/%d in %.1fs", e.code, url, attempt + 1, max_retries, wait)
            time.sleep(wait)
        except urllib.error.URLError as e:
            if attempt >= max_retries - 1:
                raise
            wait = BACKOFF_BASE ** attempt
            log.warning("URL error on %s: %s, retry %d/%d in %.1fs", url, e, attempt + 1, max_retries, wait)
            time.sleep(wait)
