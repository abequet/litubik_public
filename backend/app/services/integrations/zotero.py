# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Zotero Web API v3 client and record mapping (roadmap chantier 4).

Only the handful of calls LitUbik needs: key introspection, groups,
collections, top-level items of a collection (JSON, paginated), child PDF
attachments, batch item creation/update, collection creation. The base URL
is fixed (api.zotero.org) so no user-provided address ever reaches httpx;
file downloads follow Zotero's redirect to its storage with the SSRF guard.

Records flow through the same normalized dict as the RIS parser
(`services.ris.parse._record`), so an import from Zotero lands in the pipeline
exactly like an uploaded export file.
"""
import re
import time
import uuid

import httpx

from app.core.httpcap import get_capped
from app.core.ssrf import block_private_redirects
from app.services.ris.parse import _record

API_BASE = "https://api.zotero.org"
API_VERSION = "3"
PAGE = 100          # max page size on reads
WRITE_BATCH = 50    # max objects per write request
TIMEOUT = httpx.Timeout(60.0)
RETRIES_ON_429 = 3
MAX_PDF_BYTES = 80 * 1024 * 1024

# tests swap this for an httpx.MockTransport; None = the real network
_transport = None

KEY_SETTINGS_URL = "https://www.zotero.org/settings/keys/new"


class ZoteroError(Exception):
    pass


def _client(api_key: str | None, *, follow_redirects: bool = False) -> httpx.Client:
    headers = {"Zotero-API-Version": API_VERSION,
               "User-Agent": "LitUbik (systematic-review pipeline)"}
    if api_key:
        headers["Zotero-API-Key"] = api_key
    kwargs = {}
    if follow_redirects:
        kwargs["event_hooks"] = {"response": [block_private_redirects]}
    return httpx.Client(base_url=API_BASE, headers=headers, timeout=TIMEOUT,
                        transport=_transport, follow_redirects=follow_redirects,
                        **kwargs)


def _retry_after(headers, attempt: int) -> float:
    for name in ("Retry-After", "Backoff"):
        value = headers.get(name)
        if value and str(value).isdigit():
            return min(float(value), 60.0)
    return float(2 ** attempt)


def _raise_for(status: int, body: bytes, what: str):
    if status == 403:
        raise ZoteroError(f"Zotero refused the {what}: the API key lacks the "
                          "required permission (check library and write access "
                          "on zotero.org/settings/keys)")
    if status == 404:
        raise ZoteroError(f"Zotero: {what} not found")
    text = body.decode("utf-8", "replace")[:200]
    raise ZoteroError(f"Zotero API error {status} on {what}: {text}")


class ZoteroClient:
    def __init__(self, api_key: str | None):
        self.api_key = api_key

    # -- low level --------------------------------------------------------------
    def _get(self, path: str, params: dict | None = None, *, what: str = "request"):
        """JSON GET with pagination headers; returns (payload, headers)."""
        with _client(self.api_key) as client:
            for attempt in range(RETRIES_ON_429 + 1):
                status, body, headers, _ = get_capped(client, path, params=params)
                if status == 429 and attempt < RETRIES_ON_429:
                    time.sleep(_retry_after(headers, attempt))
                    continue
                if status != 200:
                    _raise_for(status, body, what)
                return httpx.Response(200, content=body).json(), headers

    def _post(self, path: str, payload, *, what: str = "write") -> dict:
        with _client(self.api_key) as client:
            for attempt in range(RETRIES_ON_429 + 1):
                r = client.post(path, json=payload,
                                headers={"Zotero-Write-Token": uuid.uuid4().hex})
                if r.status_code == 429 and attempt < RETRIES_ON_429:
                    time.sleep(_retry_after(r.headers, attempt))
                    continue
                if r.status_code != 200:
                    _raise_for(r.status_code, r.content, what)
                return r.json()

    def _paged(self, path: str, params: dict | None = None, *, what: str,
               progress=None, cap: int | None = None) -> list:
        out: list = []
        start = 0
        while True:
            page, headers = self._get(
                path, {**(params or {}), "limit": PAGE, "start": start}, what=what)
            out.extend(page)
            total = int(headers.get("Total-Results", len(out)) or 0)
            if progress:
                progress(len(out), total)
            start += PAGE
            if not page or start >= total or (cap and len(out) >= cap):
                break
        return out[:cap] if cap else out

    # -- key, libraries, collections ---------------------------------------
    def key_info(self) -> dict:
        """GET /keys/<key>: userID, username and the access map."""
        if not self.api_key:
            raise ZoteroError("No Zotero API key")
        info, _ = self._get(f"/keys/{self.api_key}", what="API key check")
        return info

    def libraries(self) -> dict:
        """The libraries this key can read, with write flags — the personal
        library and every accessible group."""
        info = self.key_info()
        access = info.get("access") or {}
        user_access = access.get("user") or {}
        libs = []
        if user_access.get("library"):
            libs.append({"type": "user", "id": int(info["userID"]),
                         "name": "My library", "write": bool(user_access.get("write"))})
        groups_access = access.get("groups") or {}
        if groups_access:
            groups = self._paged(f"/users/{info['userID']}/groups", what="groups list")
            for g in groups:
                gid = int(g["id"])
                rule = groups_access.get(str(gid)) or groups_access.get("all") or {}
                if not rule.get("library"):
                    continue
                libs.append({"type": "group", "id": gid,
                             "name": (g.get("data") or {}).get("name", f"Group {gid}"),
                             "write": bool(rule.get("write"))})
        return {"user_id": int(info["userID"]), "username": info.get("username", ""),
                "libraries": libs}

    def collections(self, prefix: str) -> list[dict]:
        """Flat list ordered as a tree (parents before children, depth given),
        for an indented dropdown."""
        rows = self._paged(f"/{prefix}/collections", what="collections list")
        by_key = {}
        for c in rows:
            data = c.get("data") or {}
            by_key[c["key"]] = {"key": c["key"], "name": data.get("name", ""),
                                "parent": data.get("parentCollection") or None,
                                "n_items": int((c.get("meta") or {}).get("numItems", 0))}
        children: dict = {}
        for c in by_key.values():
            parent = c["parent"] if c["parent"] in by_key else None
            children.setdefault(parent, []).append(c)
        out: list[dict] = []

        def walk(parent, depth):
            for c in sorted(children.get(parent, []), key=lambda x: x["name"].lower()):
                out.append({"key": c["key"], "name": c["name"], "depth": depth,
                            "n_items": c["n_items"]})
                walk(c["key"], depth + 1)
        walk(None, 0)
        return out

    def create_collection(self, prefix: str, name: str) -> str:
        res = self._post(f"/{prefix}/collections",
                         [{"name": name, "parentCollection": False}],
                         what="collection creation")
        ok = (res.get("successful") or {}).get("0") or {}
        key = ok.get("key") or (res.get("success") or {}).get("0")
        if not key:
            failed = (res.get("failed") or {}).get("0") or {}
            raise ZoteroError(f"Zotero could not create the collection: "
                              f"{failed.get('message', 'unknown error')}")
        return key

    # -- items ----------------------------------------------------------------
    def items(self, prefix: str, collection_key: str | None, *, progress=None,
              cap: int | None = None) -> list[dict]:
        """Top-level items (no child notes/attachments) of a collection, or of
        the whole library when collection_key is None."""
        path = (f"/{prefix}/collections/{collection_key}/items/top"
                if collection_key else f"/{prefix}/items/top")
        rows = self._paged(path, {"format": "json"}, what="items list",
                           progress=progress, cap=cap)
        return [r for r in rows
                if (r.get("data") or {}).get("itemType") not in ("attachment", "note")]

    def items_by_key(self, prefix: str, keys: list[str]) -> dict[str, dict]:
        """Current version/tags/collections of known items, by key — the items
        missing from the answer were deleted in Zotero."""
        found: dict[str, dict] = {}
        for i in range(0, len(keys), WRITE_BATCH):
            chunk = keys[i:i + WRITE_BATCH]
            rows, _ = self._get(f"/{prefix}/items",
                                {"itemKey": ",".join(chunk), "format": "json",
                                 "limit": WRITE_BATCH},
                                what="items lookup")
            for r in rows:
                found[r["key"]] = r
        return found

    def pdf_attachments(self, prefix: str, item_key: str) -> list[dict]:
        rows, _ = self._get(f"/{prefix}/items/{item_key}/children",
                            {"format": "json"}, what="attachments list")
        return [r for r in rows
                if (r.get("data") or {}).get("itemType") == "attachment"
                and (r.get("data") or {}).get("contentType") == "application/pdf"
                and (r.get("data") or {}).get("linkMode") in ("imported_file",
                                                               "imported_url")]

    def download_file(self, prefix: str, attachment_key: str) -> bytes | None:
        """The attachment's file (Zotero answers with a redirect to its
        storage). None when the file is not stored online."""
        with _client(self.api_key, follow_redirects=True) as client:
            status, body, _, _ = get_capped(
                client, f"/{prefix}/items/{attachment_key}/file", cap=MAX_PDF_BYTES)
        if status == 200 and body[:5] == b"%PDF-":
            return body
        return None

    def write_items(self, prefix: str, items: list[dict]) -> dict:
        """POST up to 50 items (new ones without key; updates carry key +
        version). Returns {"keys": {index: key}, "failed": {index: message}}."""
        keys: dict[int, str] = {}
        failed: dict[int, str] = {}
        for i in range(0, len(items), WRITE_BATCH):
            chunk = items[i:i + WRITE_BATCH]
            res = self._post(f"/{prefix}/items", chunk, what="items write")
            for idx, obj in (res.get("successful") or {}).items():
                keys[i + int(idx)] = obj.get("key") or ""
            for idx, key in (res.get("success") or {}).items():
                keys.setdefault(i + int(idx), key)
            for idx, key in (res.get("unchanged") or {}).items():
                keys.setdefault(i + int(idx), key if isinstance(key, str)
                                else chunk[int(idx)].get("key", ""))
            for idx, err in (res.get("failed") or {}).items():
                failed[i + int(idx)] = (err or {}).get("message", "write failed")
        return {"keys": keys, "failed": failed}


# -- mapping ---------------------------------------------------------------------

_YEAR = re.compile(r"\b(1[6-9]\d{2}|20\d{2})\b")
_DOI = re.compile(r"\b(10\.\d{1,9}/\S+)", re.IGNORECASE)
_CONTAINER_FIELDS = ("publicationTitle", "proceedingsTitle", "bookTitle",
                     "conferenceName", "websiteTitle", "university",
                     "institution", "repository", "publisher")


def _creator_name(c: dict) -> str:
    if c.get("name"):
        return str(c["name"]).strip()
    last = str(c.get("lastName") or "").strip()
    first = str(c.get("firstName") or "").strip()
    if last and first:
        return f"{last}, {first}"
    return last or first


def item_to_record(item: dict) -> dict:
    """A Zotero item (API JSON) → LitUbik normalized record."""
    data = item.get("data") or {}
    creators = data.get("creators") or []
    authors = [c for c in creators if c.get("creatorType") == "author"] or creators
    doi = data.get("DOI") or ""
    if not doi:
        m = _DOI.search(data.get("extra") or "") or _DOI.search(data.get("url") or "")
        doi = m.group(1) if m else ""
    year = None
    m = _YEAR.search(str(data.get("date") or ""))
    if m:
        year = int(m.group(1))
    journal = next((data[f] for f in _CONTAINER_FIELDS if data.get(f)), "")
    return _record(doi=doi or None, title=data.get("title") or "",
                   authors=[_creator_name(c) for c in authors],
                   year=year, journal=journal, abstract=data.get("abstractNote") or "")


def _creator(author: str) -> dict:
    name = " ".join(str(author).split())
    if "," in name:
        last, first = name.split(",", 1)
        return {"creatorType": "author", "lastName": last.strip(),
                "firstName": first.strip()}
    parts = name.split(" ")
    if len(parts) >= 2:
        return {"creatorType": "author", "lastName": parts[-1],
                "firstName": " ".join(parts[:-1])}
    return {"creatorType": "author", "name": name}


def record_to_item(record, *, status: str, tags: list[str], collection_key: str | None,
                   existing: dict | None = None) -> dict:
    """A LitUbik record → Zotero journalArticle item data. For an update,
    `existing` is the current item: its version is required, its tags and
    collections are kept (only the litubik:* tags are replaced)."""
    own_tags = [{"tag": f"litubik:{status}"}] + [{"tag": t} for t in tags]
    collections = [collection_key] if collection_key else []
    item = {
        "itemType": "journalArticle",
        "title": record.title or "",
        "creators": [_creator(a) for a in (record.authors or [])],
        "date": str(record.year) if record.year else "",
        "publicationTitle": record.journal or "",
        "DOI": record.doi or "",
        "abstractNote": record.abstract or "",
        "extra": f"LitUbik: {record.uuid}\nLitUbik decision: {status}",
        "tags": own_tags,
        "collections": collections,
    }
    if existing is not None:
        data = existing.get("data") or {}
        kept = [t for t in (data.get("tags") or [])
                if not str(t.get("tag", "")).startswith("litubik:")]
        names = {t["tag"] for t in own_tags}
        item["tags"] = own_tags + [t for t in kept if t.get("tag") not in names]
        item["collections"] = sorted(set((data.get("collections") or []) + collections))
        item["key"] = existing["key"]
        item["version"] = existing.get("version") or data.get("version") or 0
        if data.get("itemType") and data["itemType"] != "journalArticle":
            # keep the user's type and only send the fields every type has
            # (title, creators, date, abstract, extra): the container field and
            # DOI are rejected on types that lack them
            item["itemType"] = data["itemType"]
            item.pop("publicationTitle", None)
            item.pop("DOI", None)
    return item
