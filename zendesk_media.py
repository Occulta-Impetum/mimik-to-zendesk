#!/usr/bin/env python3
"""Zendesk Guide Media upload helper for mimik-to-zendesk.

This module implements Zendesk's three-step Guide Media workflow:
1. Request an upload URL.
2. PUT the image bytes to the returned upload URL using the returned headers.
3. Create the Guide Media object from the returned asset_upload_id.

Authentication is handled separately by zendesk_auth.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from zendesk_auth import load_zendesk_config

REQUEST_TIMEOUT = 60
MAX_FILE_SIZE = 20 * 1024 * 1024
DEFAULT_CONTENT_TYPE = "image/png"


class ZendeskMediaError(RuntimeError):
    """Raised when a Zendesk Guide Media operation cannot be completed."""


def _api_headers(access_token: str) -> dict[str, str]:
    if not access_token:
        raise ZendeskMediaError("A Zendesk OAuth access token is required.")

    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _safe_response_detail(response: requests.Response) -> str:
    """Return a concise API error without exposing signed upload URLs or tokens."""
    detail = ""

    try:
        body = response.json()
        if isinstance(body, dict):
            candidates = [
                body.get("error_description"),
                body.get("description"),
                body.get("message"),
                body.get("error"),
            ]
            detail = next((str(value) for value in candidates if value), "")
            if not detail and body:
                detail = str(body)
    except ValueError:
        detail = (response.text or "").strip()

    detail = " ".join(detail.split())
    return detail[:500]


def _raise_for_api_error(response: requests.Response, operation: str) -> None:
    if response.ok:
        return

    detail = _safe_response_detail(response)
    suffix = f" Response: {detail}" if detail else ""
    raise ZendeskMediaError(
        f"Zendesk {operation} failed with HTTP {response.status_code}.{suffix}"
    )


def _resolve_subdomain(subdomain: str | None) -> str:
    if subdomain:
        return subdomain.strip()

    return load_zendesk_config()["subdomain"]


def _normalize_upload_headers(value: Any) -> dict[str, str] | None:
    """Normalize Zendesk upload headers returned as an object or JSON string."""
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}

    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None

        if isinstance(decoded, dict):
            return {str(key): str(item) for key, item in decoded.items()}

    return None


def _safe_structure(value: Any, *, max_depth: int = 2) -> str:
    """Describe JSON response structure without including response values."""
    def describe(item: Any, depth: int) -> Any:
        if isinstance(item, dict):
            if depth >= max_depth:
                return {str(key): type(val).__name__ for key, val in item.items()}
            return {str(key): describe(val, depth + 1) for key, val in item.items()}
        if isinstance(item, list):
            if not item:
                return []
            return [describe(item[0], depth + 1)]
        return type(item).__name__

    return json.dumps(describe(value, 0), sort_keys=True)


def request_upload_url(
    access_token: str,
    *,
    file_size: int,
    content_type: str = DEFAULT_CONTENT_TYPE,
    subdomain: str | None = None,
) -> dict[str, Any]:
    """Request a temporary upload URL from Zendesk Guide Media."""
    if file_size <= 0:
        raise ZendeskMediaError("The image file is empty.")
    if file_size > MAX_FILE_SIZE:
        raise ZendeskMediaError("Zendesk Guide Media files cannot exceed 20 MB.")
    if not content_type:
        raise ZendeskMediaError("A content type is required for Guide Media uploads.")

    zendesk_subdomain = _resolve_subdomain(subdomain)
    url = f"https://{zendesk_subdomain}.zendesk.com/api/v2/guide/medias/upload_url"
    payload = {
        "content_type": content_type,
        "file_size": file_size,
    }

    try:
        response = requests.post(
            url,
            headers=_api_headers(access_token),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ZendeskMediaError(
            "Could not request a Zendesk Guide Media upload URL."
        ) from exc

    _raise_for_api_error(response, "Guide Media upload-URL request")

    try:
        data = response.json()
    except ValueError as exc:
        raise ZendeskMediaError(
            "Zendesk returned an invalid Guide Media upload-URL response."
        ) from exc

    upload_info = data.get("upload_url")
    if not isinstance(upload_info, dict):
        raise ZendeskMediaError(
            "Zendesk Guide Media response did not contain upload_url details."
        )
    if not upload_info.get("url"):
        raise ZendeskMediaError(
            "Zendesk Guide Media response did not contain an upload URL."
        )
    if not upload_info.get("asset_upload_id"):
        raise ZendeskMediaError(
            "Zendesk Guide Media response did not contain asset_upload_id."
        )

    # Zendesk's published example shows upload headers at the response root.
    # Some accounts return them inside upload_url, and some serialize that
    # nested headers object as a JSON string. Accept all observed shapes and
    # normalize to data["headers"] for the upload step.
    headers = _normalize_upload_headers(data.get("headers"))
    if headers is None:
        headers = _normalize_upload_headers(upload_info.get("headers"))

    if headers is None:
        top_level_keys = ", ".join(sorted(str(key) for key in data.keys()))
        upload_keys = ", ".join(sorted(str(key) for key in upload_info.keys()))
        nested_type = type(upload_info.get("headers")).__name__
        raise ZendeskMediaError(
            "Zendesk Guide Media response contained upload headers in an unsupported format. "
            f"Top-level keys: {top_level_keys or '(none)'}. "
            f"upload_url keys: {upload_keys or '(none)'}. "
            f"headers type: {nested_type}."
        )

    data["headers"] = headers
    return data


def upload_file_to_provisioned_url(
    image_path: str | Path,
    upload_response: dict[str, Any],
) -> None:
    """Upload image bytes to the temporary URL returned by Zendesk."""
    path = Path(image_path)
    if not path.is_file():
        raise ZendeskMediaError(f"Image file does not exist: {path}")

    upload_info = upload_response.get("upload_url") or {}
    upload_url = upload_info.get("url")
    upload_headers = upload_response.get("headers")

    if not upload_url or not isinstance(upload_headers, dict):
        raise ZendeskMediaError("The Zendesk upload response is incomplete.")

    try:
        with path.open("rb") as image_file:
            response = requests.put(
                upload_url,
                headers={str(k): str(v) for k, v in upload_headers.items()},
                data=image_file,
                timeout=REQUEST_TIMEOUT,
            )
    except requests.RequestException as exc:
        # Do not include the pre-signed upload URL in exceptions or logs.
        raise ZendeskMediaError(
            "Could not upload image bytes to Zendesk-hosted storage."
        ) from exc

    if not response.ok:
        raise ZendeskMediaError(
            f"Zendesk-hosted image upload failed with HTTP {response.status_code}."
        )


def create_guide_media(
    access_token: str,
    *,
    asset_upload_id: str,
    filename: str,
    subdomain: str | None = None,
) -> dict[str, Any]:
    """Create a Guide Media object from an uploaded asset."""
    if not asset_upload_id:
        raise ZendeskMediaError("asset_upload_id is required.")
    if not filename:
        raise ZendeskMediaError("A filename is required.")

    zendesk_subdomain = _resolve_subdomain(subdomain)
    url = f"https://{zendesk_subdomain}.zendesk.com/api/v2/guide/medias"
    payload = {
        "asset_upload_id": asset_upload_id,
        "filename": filename,
    }

    try:
        response = requests.post(
            url,
            headers=_api_headers(access_token),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ZendeskMediaError("Could not create the Zendesk Guide Media object.") from exc

    _raise_for_api_error(response, "Guide Media creation")

    try:
        data = response.json()
    except ValueError as exc:
        raise ZendeskMediaError(
            "Zendesk returned an invalid Guide Media creation response."
        ) from exc

    if not isinstance(data, dict):
        raise ZendeskMediaError(
            "Zendesk Guide Media creation returned an unexpected JSON type. "
            f"Structure: {_safe_structure(data)}"
        )

    # Zendesk's documentation says this response contains id and url at the
    # top level. If the tenant returns a different shape, report only the JSON
    # structure so we can reconcile it with the documented response without
    # exposing media URLs or other response values.
    if not data.get("url"):
        raise ZendeskMediaError(
            "Zendesk Guide Media response did not contain the documented top-level media URL. "
            f"Response structure: {_safe_structure(data)}"
        )

    return data


def upload_guide_media(
    image_path: str | Path,
    access_token: str,
    *,
    content_type: str = DEFAULT_CONTENT_TYPE,
    subdomain: str | None = None,
) -> dict[str, Any]:
    """Upload one image and return the created Zendesk Guide Media object."""
    path = Path(image_path)
    if not path.is_file():
        raise ZendeskMediaError(f"Image file does not exist: {path}")

    file_size = path.stat().st_size
    if file_size <= 0:
        raise ZendeskMediaError(f"Image file is empty: {path}")
    if file_size > MAX_FILE_SIZE:
        raise ZendeskMediaError(
            f"Image exceeds Zendesk's 20 MB Guide Media limit: {path.name}"
        )

    upload_response = request_upload_url(
        access_token,
        file_size=file_size,
        content_type=content_type,
        subdomain=subdomain,
    )

    upload_file_to_provisioned_url(path, upload_response)

    upload_info = upload_response["upload_url"]
    return create_guide_media(
        access_token,
        asset_upload_id=upload_info["asset_upload_id"],
        filename=path.name,
        subdomain=subdomain,
    )
