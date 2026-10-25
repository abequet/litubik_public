# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import a pre-registered protocol straight from an OSF link.

Accepted links:
- a project or registration page  (https://osf.io/abcde/)
- a direct file link              (https://osf.io/abcde/  when the GUID is a file,
                                   https://osf.io/download/abcde/, .../abcde/download)
- a files page                    (https://osf.io/abcde/files/osfstorage)

For registrations, the registration form itself (registration_responses) is
offered as a candidate alongside attached files — many preregistrations have no
protocol file at all, the form *is* the protocol.
"""
import re
from urllib.parse import urlparse

import httpx

from app.core import polite
from app.core.httpcap import ResponseTooLarge, get_capped
from app.core.ssrf import SSRFError, block_private_redirects, validate_public_url
from app.services.protocol.extract_text import ALLOWED_EXTENSIONS

API = "https://api.osf.io/v2"
TIMEOUT = httpx.Timeout(30.0)
PAGE_SIZE = 100
MAX_FOLDER_DEPTH = 2
MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024


class OsfError(Exception):
    pass


def fetch_protocol(url: str, pick: dict | None = None) -> list[dict] | tuple[str, bytes]:
    """Resolve an OSF url. Returns either the list of candidates (the caller
    should ask the user to pick one) or the chosen/only file as (name, bytes).

    pick: a candidate dict previously returned by this function.
    """
    if pick is not None:
        return _fetch_candidate(pick)
    candidates = _resolve_url(url.strip())
    if not candidates:
        raise OsfError("No protocol found at this OSF link "
                       "(no registration form and no PDF/DOCX/MD/TXT file)")
    if len(candidates) > 1:
        return candidates
    return _fetch_candidate(candidates[0])


def registration_of(url: str) -> dict | None:
    """{"guid", "date_registered"} when the link is an OSF *registration* —
    its GUID is then the registration number (PRISMA 24a). None for a
    project, a file or anything OSF cannot tell us about."""
    guid = _guid_from_url(url.strip())
    if not guid:
        return None
    try:
        data = _get_json(f"{API}/guids/{guid}/")["data"]
    except (OsfError, KeyError):
        return None
    if data.get("type") != "registrations":
        return None
    return {"guid": guid,
            "date_registered": data.get("attributes", {}).get("date_registered")}


# -- resolution ---------------------------------------------------------------

def _guid_from_url(url: str) -> str:
    """GUID of an osf.io page url; '' when the url is not an OSF page."""
    m = re.match(
        r"^https?://(?:www\.)?osf\.io/([a-z0-9]{4,8})(?:/.*)?$", url, re.IGNORECASE)
    return m.group(1).lower() if m and m.group(1).lower() != "download" else ""


def _is_download_url(url: str) -> bool:
    return bool(re.match(
        r"^https?://(?:www\.)?osf\.io/(?:download/[a-z0-9]+|[a-z0-9]+/download)/?",
        url, re.IGNORECASE))


def _resolve_url(url: str) -> list[dict]:
    if _is_download_url(url):
        return [{"kind": "file", "name": "", "download_url": url}]
    guid = _guid_from_url(url)
    if not guid:
        raise OsfError("Not an OSF link — expected something like https://osf.io/abcde/")

    data = _get_json(f"{API}/guids/{guid}/")["data"]
    entity_type = data.get("type", "")

    if entity_type == "files":
        attrs = data.get("attributes", {})
        return [{"kind": "file", "name": attrs.get("name", ""),
                 "download_url": _file_download_url(data)}]

    candidates: list[dict] = []
    if entity_type == "registrations":
        title = data.get("attributes", {}).get("title", "OSF registration")
        if _form_responses(data.get("attributes", {})):
            candidates.append({"kind": "form", "name": f"Registration form — {title}",
                               "guid": guid})
        files_url = f"{API}/registrations/{guid}/files/osfstorage/"
    elif entity_type == "nodes":
        files_url = f"{API}/nodes/{guid}/files/osfstorage/"
    else:
        raise OsfError(f"This OSF link points to a '{entity_type}' — "
                       "use a project, registration or file link")

    candidates += _list_files(files_url, depth=0)
    return candidates


def _list_files(files_url: str, depth: int) -> list[dict]:
    out: list[dict] = []
    payload = _get_json(files_url, params={"page[size]": PAGE_SIZE})
    for item in payload.get("data", []):
        attrs = item.get("attributes", {})
        if attrs.get("kind") == "folder":
            if depth < MAX_FOLDER_DEPTH:
                sub = (item.get("relationships", {}).get("files", {})
                       .get("links", {}).get("related", {}).get("href"))
                if sub:
                    out += _list_files(sub, depth + 1)
            continue
        name = attrs.get("name", "")
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in ALLOWED_EXTENSIONS:
            out.append({"kind": "file", "name": name,
                        "download_url": _file_download_url(item),
                        "size": attrs.get("size")})
    return out


def _file_download_url(item: dict) -> str:
    link = (item.get("links") or {}).get("download")
    if link:
        return link
    guid = (item.get("attributes") or {}).get("guid")
    if guid:
        return f"https://osf.io/download/{guid}/"
    raise OsfError("Could not determine the download link for this OSF file")


# -- fetching -----------------------------------------------------------------

def _fetch_candidate(pick: dict) -> tuple[str, bytes]:
    # `pick` comes back from the client: what it names is checked again here
    if pick.get("kind") == "form":
        guid = str(pick.get("guid") or "")
        if not re.fullmatch(r"[a-z0-9]{4,8}", guid, re.IGNORECASE):
            raise OsfError("Not an OSF registration")
        return _fetch_form(guid.lower())
    return _download_file(pick.get("download_url") or "", pick.get("name", ""))


def _is_osf_host(url: str) -> bool:
    """osf.io or one of its subdomains (files.osf.io, files.de-1.osf.io…): the
    only hosts OSF's own API hands out as download links."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return (parsed.scheme in ("http", "https")
            and (host == "osf.io" or host.endswith(".osf.io")))


def _download_file(download_url: str, name: str) -> tuple[str, bytes]:
    # The link is sent back by the client after a multi-file answer, so it is
    # not trusted: an OSF host only, and neither it nor any redirect (OSF sends
    # files on to its storage) may lead to an internal address.
    if not _is_osf_host(download_url):
        raise OsfError("Not an OSF download link")
    # L3: enforce the size cap DURING the stream, so an oversized/hostile file
    # is aborted before it is fully buffered into memory.
    try:
        validate_public_url(download_url)
        hooks = {"response": [block_private_redirects]}
        with httpx.Client(timeout=TIMEOUT, headers=polite.headers(),
                          follow_redirects=True, event_hooks=hooks) as client:
            status, content, headers, _url = get_capped(
                client, download_url, cap=MAX_DOWNLOAD_BYTES)
    except SSRFError:
        raise OsfError("This download link does not lead to OSF")
    except ResponseTooLarge:
        raise OsfError("File is too large (max 30 MB)")
    except httpx.HTTPError as e:
        raise OsfError(f"Could not download from OSF: {e}") from e
    if status >= 400:
        raise OsfError(f"Could not download from OSF: HTTP {status}")
    if not name:
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)',
                      headers.get("content-disposition", ""))
        name = m.group(1).strip() if m else download_url.rstrip("/").rsplit("/", 1)[-1]
    return name, content


def _fetch_form(guid: str) -> tuple[str, bytes]:
    data = _get_json(f"{API}/registrations/{guid}/")["data"]
    attrs = data.get("attributes", {})
    responses = _form_responses(attrs)
    if not responses:
        raise OsfError("This registration has no form content")
    md = render_form_md(attrs.get("title", "OSF registration"), responses,
                        f"https://osf.io/{guid}/")
    return f"osf_registration_{guid}.md", md.encode("utf-8")


def _form_responses(attrs: dict) -> dict:
    responses = attrs.get("registration_responses") or {}
    if not responses:  # older registrations
        meta = attrs.get("registered_meta") or {}
        responses = {k: v.get("value") if isinstance(v, dict) else v
                     for k, v in meta.items()}
    return {k: v for k, v in responses.items() if v not in (None, "", [], {})}


def render_form_md(title: str, responses: dict, url: str) -> str:
    lines = [f"# {title}", "", f"*Imported from OSF registration: {url}*"]
    for key, value in responses.items():
        lines += ["", f"## {_prettify(key)}", ""]
        if isinstance(value, list):
            lines += [f"- {_flatten(v)}" for v in value]
        else:
            lines.append(_flatten(value))
    return "\n".join(lines) + "\n"


def _prettify(key: str) -> str:
    words = re.sub(r"[_\-.]+", " ", key).strip()
    return (words[:1].upper() + words[1:]) if words else key


def _flatten(value) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_flatten(v)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(_flatten(v) for v in value)
    return str(value)


def _get_json(url: str, params: dict | None = None) -> dict:
    try:
        with httpx.Client(timeout=TIMEOUT, headers=polite.headers(),
                          follow_redirects=True) as client:
            r = client.get(url, params=params)
            if r.status_code == 404:
                raise OsfError("OSF returned 404 — is the link correct and public?")
            if r.status_code == 401 or r.status_code == 403:
                raise OsfError("This OSF item is private — make it public or "
                               "upload the file manually")
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise OsfError(f"Could not reach OSF: {e}") from e
