#!/usr/bin/env python3
"""Zendesk OAuth helper for mimik-to-zendesk.

Uses Zendesk's OAuth client credentials flow. The client secret is read from
an untracked local .env file and is never printed or written to output files.
"""

from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv

DEFAULT_SCOPE = "hc:write"
REQUEST_TIMEOUT = 30


class ZendeskAuthError(RuntimeError):
    """Raised when Zendesk OAuth authentication cannot be completed."""


def load_zendesk_config() -> dict[str, str]:
    """Load and validate Zendesk OAuth configuration from .env/environment."""
    load_dotenv()

    config = {
        "subdomain": (os.getenv("ZENDESK_SUBDOMAIN") or "").strip(),
        "client_id": (os.getenv("ZENDESK_OAUTH_CLIENT_ID") or "").strip(),
        "client_secret": (os.getenv("ZENDESK_OAUTH_CLIENT_SECRET") or "").strip(),
        "scope": (os.getenv("ZENDESK_OAUTH_SCOPE") or DEFAULT_SCOPE).strip(),
    }

    missing = []
    if not config["subdomain"]:
        missing.append("ZENDESK_SUBDOMAIN")
    if not config["client_id"]:
        missing.append("ZENDESK_OAUTH_CLIENT_ID")
    if not config["client_secret"]:
        missing.append("ZENDESK_OAUTH_CLIENT_SECRET")

    if missing:
        raise ZendeskAuthError(
            "Zendesk configuration is incomplete. Missing: " + ", ".join(missing)
        )

    subdomain = config["subdomain"]
    subdomain = subdomain.removeprefix("https://").removeprefix("http://")
    subdomain = subdomain.split(".", 1)[0].strip("/")
    config["subdomain"] = subdomain

    return config


def _safe_error_detail(response: requests.Response, client_secret: str) -> str:
    """Return useful Zendesk error text without exposing credentials."""
    detail = ""

    try:
        body = response.json()
        if isinstance(body, dict):
            error = body.get("error")
            description = body.get("error_description")
            if error and description:
                detail = f"{error}: {description}"
            elif description:
                detail = str(description)
            elif error:
                detail = str(error)
            else:
                candidates = [body.get("description"), body.get("message")]
                detail = next((str(value) for value in candidates if value), "")
                if not detail and body:
                    detail = str(body)
    except ValueError:
        detail = (response.text or "").strip()

    if client_secret and detail:
        detail = detail.replace(client_secret, "[REDACTED]")

    detail = " ".join(detail.split())
    return detail[:500]


def _safe_response_diagnostics(response: requests.Response) -> str:
    """Return response metadata useful for diagnosing routing without secrets."""
    header_names = (
        "Server",
        "Content-Type",
        "Location",
        "WWW-Authenticate",
        "x-openapi-route-path",
        "x-zendesk-origin-server",
        "x-request-id",
        "cf-ray",
    )

    parts = [f"URL={response.url}"]
    for name in header_names:
        value = response.headers.get(name)
        if value:
            parts.append(f"{name}={value}")

    return "; ".join(parts)


def get_access_token() -> tuple[str, dict]:
    """Request a short-lived Zendesk OAuth access token.

    Client credentials flow intentionally does not persist access tokens.
    A new token can be requested whenever the script runs or when one expires.
    """
    config = load_zendesk_config()
    token_url = f'https://{config["subdomain"]}.zendesk.com/oauth/tokens'

    payload = {
        "grant_type": "client_credentials",
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "scope": config["scope"],
    }

    try:
        # Zendesk's grant-type token API requires a JSON request body.
        response = requests.post(
            token_url,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise ZendeskAuthError(f"Could not contact Zendesk: {exc}") from exc

    if not response.ok:
        detail = _safe_error_detail(response, config["client_secret"])
        diagnostics = _safe_response_diagnostics(response)
        suffix = f" Response: {detail}" if detail else ""
        raise ZendeskAuthError(
            f"Zendesk OAuth request failed with HTTP {response.status_code}.{suffix} "
            f"Diagnostics: {diagnostics}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise ZendeskAuthError("Zendesk returned an invalid OAuth response.") from exc

    token = data.get("access_token")
    if not token:
        raise ZendeskAuthError("Zendesk OAuth response did not contain an access token.")

    return token, data


def test_authentication() -> bool:
    """Obtain an OAuth token without printing or persisting the token itself."""
    token, data = get_access_token()

    if not token:
        return False

    expires_in = data.get("expires_in")
    granted_scope = data.get("scope") or data.get("scopes") or "not reported"

    print("Zendesk OAuth authentication succeeded.")
    print(f"Granted scope: {granted_scope}")
    if expires_in is not None:
        print(f"Access token lifetime: {expires_in} seconds")
    print("The access token was not displayed or saved.")
    return True


def main() -> int:
    print("Zendesk OAuth Test")
    print("==================\n")

    try:
        return 0 if test_authentication() else 1
    except ZendeskAuthError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
