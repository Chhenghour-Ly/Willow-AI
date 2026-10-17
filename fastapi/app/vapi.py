import logging
import time

import httpx

from app.profile import structured_data

log = logging.getLogger('willow')


def fetch_call(call_id: str, settings) -> dict | None:
    """GET /call/{id} until structured outputs appear, with bounded backoff. None if never available."""
    if not settings.vapi_api_key:
        log.info('call_id=%s no structured output and VAPI_API_KEY unset; skipping Vapi fetch', call_id)
        return None
    call = None
    for attempt, delay in enumerate([0, *settings.retry_delays()], start=1):
        time.sleep(delay)
        try:
            response = httpx.get(f'{settings.vapi_base_url}/call/{call_id}', timeout=15,
                                 headers={'Authorization': f'Bearer {settings.vapi_api_key}'})
            response.raise_for_status()
            call = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Never log the response body: it holds the transcript and personal details.
            log.warning('call_id=%s vapi fetch attempt %d failed: %s', call_id, attempt, type(exc).__name__)
            continue
        if structured_data({'call': call}):
            log.info('call_id=%s structured output found via Vapi API on attempt %d', call_id, attempt)
            return call
    log.info('call_id=%s Vapi API returned no structured output after %d attempts', call_id, attempt)
    return call
