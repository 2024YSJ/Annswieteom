from __future__ import annotations

from dataclasses import dataclass
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

# Verified live against v3.velog.io/graphql on 2026-09-05 (introspection of
# the Query type + GetPostsInput + Post, and a real call against a live
# account): `posts(input: GetPostsInput!)` returns a page of a user's public
# posts newest-first, `GetPostsInput` takes {username, cursor, limit, tag,
# temp_only}, and `cursor` is the `id` (not url_slug) of the last post from
# the previous page — pass it to fetch the next (older) page, an empty list
# means there is no more. Anonymous (unauthenticated) calls already appear to
# exclude private posts server-side, but `is_private` is still checked
# defensively below rather than trusted blindly.
_LIST_POSTS_QUERY = """
query GetPosts($input: GetPostsInput!) {
  posts(input: $input) {
    id
    title
    url_slug
    released_at
    is_private
  }
}
"""
_LIST_POSTS_PAGE_SIZE = 20
_LIST_POSTS_MAX_PAGES = 25  # safety cap: 500 posts is far beyond any real gap-period import

# velog reserves these single-segment paths under a username for the
# profile's own pages (post listing, about, series index) — they share the
# exact /@username/<segment> shape as a real post, so without this check
# e.g. /@someone/posts gets misread as "a post whose slug is 'posts'", the
# GraphQL API correctly returns no such post, and that used to get reported
# as "private or deleted" — a misleading answer for what's actually just the
# wrong kind of link (production issue, 2026-09-05). Rather than just
# rejecting these, `get_listing_username()` below lets a caller detect one
# and import every post in a date range from it instead.
_RESERVED_PROFILE_PATHS = {"posts", "about", "series"}


@dataclass
class ListedPost:
    url_slug: str
    title: str
    released_at: date


def get_listing_username(url: str) -> str | None:
    """If `url` is a velog listing/profile page (e.g. /@user/posts) rather
    than an individual post, return that user's username; otherwise None.
    """
    path = urlparse(url).path
    parts = [p for p in path.split("/") if p]
    if len(parts) != 2 or not parts[0].startswith("@"):
        return None
    username = unquote(parts[0][1:])
    if not username or unquote(parts[1]) not in _RESERVED_PROFILE_PATHS:
        return None
    return username


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
    if len(parts) == 2 and url_slug in _RESERVED_PROFILE_PATHS:
        raise ValueError(
            f"This is a velog listing/profile page, not an individual post: {url}. "
            "Submit the link to one specific post instead."
        )

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


def build_post_url(username: str, url_slug: str) -> str:
    return f"https://velog.io/@{username}/{url_slug}"


async def list_posts_in_range(username: str, gap_start: date, gap_end: date) -> list[ListedPost]:
    """Return every public post by `username` whose release date falls within
    [gap_start, gap_end], newest-first page by page. Since `posts` already
    returns newest-first, pagination stops as soon as a page's oldest post is
    older than gap_start — every post on any later page would be older still.
    """
    matches: list[ListedPost] = []
    cursor: str | None = None

    async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS) as client:
        for _ in range(_LIST_POSTS_MAX_PAGES):
            variables: dict[str, object] = {"username": username, "limit": _LIST_POSTS_PAGE_SIZE}
            if cursor:
                variables["cursor"] = cursor

            resp = await client.post(
                _GRAPHQL_URL,
                json={"operationName": "GetPosts", "query": _LIST_POSTS_QUERY, "variables": {"input": variables}},
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError as exc:
                raise ValueError(f"Malformed response from velog API listing posts for @{username}") from exc
            if data.get("errors"):
                raise ValueError(f"velog API returned errors listing posts for @{username}: {data['errors']}")

            page = (data.get("data") or {}).get("posts") or []
            if not page:
                break

            page_has_older_than_range = False
            for raw in page:
                if raw.get("is_private"):
                    continue
                released_at = raw.get("released_at")
                if not released_at:
                    continue
                try:
                    released_date = date.fromisoformat(released_at[:10])
                except ValueError:
                    continue

                if released_date < gap_start:
                    page_has_older_than_range = True
                    continue
                if released_date > gap_end:
                    continue  # newer than the range — a later post in this same page may still match
                url_slug = raw.get("url_slug")
                if not url_slug:
                    continue
                matches.append(ListedPost(url_slug=url_slug, title=raw.get("title") or "", released_at=released_date))

            cursor = page[-1].get("id")
            if page_has_older_than_range or not cursor or len(page) < _LIST_POSTS_PAGE_SIZE:
                break

    return matches
