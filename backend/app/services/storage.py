from __future__ import annotations

import httpx

from app.core.config import settings


class SupabaseStorage:
    """Thin wrapper over the Supabase Storage REST API (private bucket).

    Uses httpx directly instead of the `supabase` SDK to avoid adding a new
    dependency — this project already depends on httpx for the LLM adapters.
    """

    def __init__(self) -> None:
        self._base_url = settings.supabase_url.rstrip("/")
        self._bucket = settings.supabase_storage_bucket
        self._headers = {
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "apikey": settings.supabase_service_key,
        }

    async def upload(self, path: str, content: bytes, content_type: str) -> None:
        url = f"{self._base_url}/storage/v1/object/{self._bucket}/{path}"
        headers = {**self._headers, "Content-Type": content_type, "x-upsert": "true"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, content=content)
            resp.raise_for_status()

    async def download(self, path: str) -> bytes:
        url = f"{self._base_url}/storage/v1/object/{self._bucket}/{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=self._headers)
            resp.raise_for_status()
            return resp.content

    async def delete(self, path: str) -> None:
        url = f"{self._base_url}/storage/v1/object/{self._bucket}/{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request("DELETE", url, headers=self._headers)
            resp.raise_for_status()

    async def create_signed_url(self, path: str, expires_in: int = 3600) -> str:
        """Issue a time-limited URL for the frontend to display a private image.

        expires_in is in seconds (default 1 hour, spec 13-4 security note).
        """
        url = f"{self._base_url}/storage/v1/object/sign/{self._bucket}/{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self._headers, json={"expiresIn": expires_in})
            resp.raise_for_status()
            signed_path = resp.json()["signedURL"]
            return f"{self._base_url}/storage/v1{signed_path}"


def get_storage() -> SupabaseStorage:
    """FastAPI DI hook — routes should depend on this (not import SupabaseStorage
    directly) so tests can override it with a fake and avoid real network calls,
    same pattern as get_llm_provider / get_chunk_search.
    """
    return SupabaseStorage()
