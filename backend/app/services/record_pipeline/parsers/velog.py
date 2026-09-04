from __future__ import annotations

from datetime import date
from urllib.parse import unquote, urlparse

import httpx

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

_GRAPHQL_URL = "https://v3.velog.io/graphql"

# Verified live against v3.velog.io/graphql on 2026-09-04 (introspection +
# a real public post): the `post` field takes a single `input: ReadPostInput!`
# argument (username/url_slug), not separate top-level args as older
# community write-ups describe. A non-existent or private post resolves to
# `{"data": {"post": null}}` with no `errors` entry.
_READ_POST_QUERY = """
query ReadPost($input: ReadPostInput!) {
  post(input: $input) {
    title
    body
    released_at
    is_private
  }
}
"""


def _parse_username_and_slug(url: str) -> tuple[str, str]:
    """Extract (username, url_slug) from a https://velog.io/@username/url-slug URL."""
    path = urlparse(url).path
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or not parts[0].startswith("@"):
        raise ValueError(f"Unrecognized velog URL shape (expected /@username/slug): {url}")

    username = unquote(parts[0][1:])
    url_slug = unquote(parts[1])
    if not username or not url_slug:
        raise ValueError(f"Unrecognized velog URL shape (expected /@username/slug): {url}")

    return username, url_slug


async def parse(url: str) -> tuple[str, date | None]:
    """Fetch a velog post's text via velog's public GraphQL API.

    velog.io (v3) is a Next.js app whose post body is hydrated client-side —
    the raw server HTML has no extractable article text, so the generic
    scraper (httpx + trafilatura) always fails for velog URLs. Query the
    public GraphQL API directly instead; no auth is required for public posts.
    """
    username, url_slug = _parse_username_and_slug(url)

    payload = {
        "operationName": "ReadPost",
        "query": _READ_POST_QUERY,
        "variables": {"input": {"username": username, "url_slug": url_slug}},
    }

    async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS) as client:
        resp = await client.post(_GRAPHQL_URL, json=payload)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError as exc:
            raise ValueError(f"Malformed response from velog API for {url}") from exc

    if data.get("errors"):
        raise ValueError(f"velog API returned errors for {url}: {data['errors']}")

    post = (data.get("data") or {}).get("post")
    if not post:
        raise ValueError(f"velog post not found (private or deleted): {url}")

    body = (post.get("body") or "").strip()
    if not body:
        raise ValueError(f"Empty content in velog post {url}")

    title = (post.get("title") or "").strip()
    text = f"{title}\n\n{body}".strip() if title else body

    pub_date: date | None = None
    released_at = post.get("released_at")
    if released_at:
        try:
            pub_date = date.fromisoformat(released_at[:10])
        except ValueError:
            pass

    return text, pub_date
