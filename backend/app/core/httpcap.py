# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""L3: bound the memory an outbound HTTP response can consume.

httpx buffers the whole body into RAM by default, so a hostile or buggy
endpoint (or a redirect to a huge file) could OOM the mono-process server. These
helpers stream the response and abort once a comfortable ceiling is crossed —
generous enough that no legitimate scholarly-API page or protocol file hits it.
"""
MAX_RESPONSE_BYTES = 64 * 1024 * 1024  # 64 MiB — comfortable safety ceiling


class ResponseTooLarge(Exception):
    """A capped GET exceeded its byte ceiling and was aborted mid-stream."""


def get_capped(client, url, *, params=None, headers=None,
               cap=MAX_RESPONSE_BYTES):
    """Stream a GET into memory, raising ResponseTooLarge past `cap` bytes.
    Returns (status_code, content_bytes, headers, final_url_str). Any response
    event hooks on the client (e.g. the SSRF redirect guard) still fire."""
    with client.stream("GET", url, params=params, headers=headers) as r:
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) > cap:
                raise ResponseTooLarge(
                    f"Response from {url} exceeds {cap // (1024 * 1024)} MiB")
        return r.status_code, bytes(buf), r.headers, str(r.url)
