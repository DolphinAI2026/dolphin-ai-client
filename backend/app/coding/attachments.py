from __future__ import annotations

from typing import Any


def normalize_coding_attachments(raw: Any) -> list[dict[str, str]]:
    """Keep only safe, UI-relevant attachment metadata for coding chat replay."""
    if not isinstance(raw, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue

        kind = str(item.get("kind") or "").strip().lower()
        if kind not in {"image", "file"}:
            continue

        filename = str(item.get("filename") or item.get("name") or "").strip()
        if not filename:
            continue

        attachment: dict[str, str] = {
            "kind": kind,
            "filename": filename,
        }
        url = str(item.get("url") or "").strip()
        if url.startswith("/api/"):
            attachment["url"] = url
        relative_path = str(item.get("relative_path") or "").strip().replace("\\", "/").lstrip("/")
        if relative_path and ".." not in relative_path.split("/"):
            attachment["relative_path"] = relative_path
        content_type = str(item.get("content_type") or item.get("mime") or "").strip()
        if content_type:
            attachment["content_type"] = content_type
        normalized.append(attachment)

    return normalized
