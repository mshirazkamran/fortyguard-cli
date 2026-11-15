"""HTTP client and environment handling for the FortyGuard Temperature API."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx

DEFAULT_BASE_URL = "https://api.fortyguard.com"
API_KEY_ENV = "FORTYGUARD_KEY"
LEGACY_API_KEY_ENV = "FOTYGUARD_KEY"

COMPLETED_STATUSES = {"completed", "succeeded", "success"}
FAILED_STATUSES = {"failed", "error"}
ACTIVE_STATUSES = {"processing", "pending", "queued", "running", "submitted", "in_progress"}


class FortyGuardError(Exception):
    """A readable error raised for API, network, or configuration problems."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        activity_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.activity_id = activity_id


def find_env_file(start: Path | None = None) -> Path | None:
    """Return the nearest .env file, walking up from the current directory."""
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_env_file(path: Path | None = None) -> Path | None:
    """Load a .env file without overriding variables already in the environment."""
    env_path = path or find_env_file()
    if env_path is None or not env_path.is_file():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name:
            os.environ.setdefault(name, value)

    return env_path


def resolve_api_key(explicit: str | None = None) -> str:
    """Return the API key from the CLI flag or FORTYGUARD_KEY."""
    if explicit and explicit.strip():
        return explicit.strip()

    key = os.environ.get(API_KEY_ENV, "").strip()
    if key:
        return key

    if os.environ.get(LEGACY_API_KEY_ENV, "").strip():
        raise FortyGuardError(
            f"Found {LEGACY_API_KEY_ENV} in your environment, but this CLI reads "
            f"{API_KEY_ENV}. Rename the variable to {API_KEY_ENV} "
            "(for example: FORTYGUARD_KEY=your_key)."
        )

    raise FortyGuardError(
        f"{API_KEY_ENV} is not set. Add it to .env in the project root or pass --api-key."
    )


def mask_key(key: str) -> str:
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


class FortyGuardClient:
    """Small, explicit wrapper around the FortyGuard REST API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        verbose: bool = False,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verbose = verbose
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={
                "api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "FortyGuardClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ requests

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.verbose:
            print(f"→ {method} {path}", file=sys.stderr)
            if params:
                print(f"  query: {json.dumps(params)}", file=sys.stderr)
            if json_body is not None:
                print(
                    "  body: "
                    + json.dumps(json_body, ensure_ascii=False, default=str),
                    file=sys.stderr,
                )

        try:
            response = self._http.request(
                method,
                path,
                json=json_body,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise FortyGuardError(f"Network request failed: {exc}") from exc

        if self.verbose:
            print(f"← {response.status_code} {response.reason_phrase}", file=sys.stderr)

        body: Any
        try:
            body = response.json()
        except ValueError:
            body = None

        if response.status_code >= 400:
            message = self._error_message(body, response)
            raise FortyGuardError(
                f"API error {response.status_code}: {message}",
                status_code=response.status_code,
            )

        if not isinstance(body, dict):
            snippet = response.text[:500].strip()
            raise FortyGuardError(
                "The API returned a non-JSON response"
                + (f": {snippet}" if snippet else ".")
            )

        return body

    @staticmethod
    def _error_message(body: Any, response: httpx.Response) -> str:
        if isinstance(body, dict):
            for field in ("message", "detail", "error_description", "error"):
                value = body.get(field)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            data = body.get("data")
            if isinstance(data, dict):
                for field in ("message", "detail", "error"):
                    value = data.get(field)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        text = response.text.strip()
        if text:
            return text[:500]
        return response.reason_phrase or "Unknown error"

    # ------------------------------------------------------------- async activities

    def submit(self, path: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Submit an asynchronous task and return (activity_id, raw_response)."""
        body = self.request("POST", path, json_body=payload)
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        activity_id = data.get("activity_id") or body.get("activity_id")
        if not activity_id:
            raise FortyGuardError(
                "The API accepted the request but did not return an activity_id. "
                f"Response: {json.dumps(body, ensure_ascii=False)[:500]}"
            )
        return str(activity_id), body

    def get_status(self, activity_id: str, *, links: bool = False) -> dict[str, Any]:
        """Return the data object for an activity status response."""
        params = {"result_delivery": "links"} if links else None
        body = self.request("GET", f"/v1/status/{activity_id}", params=params)
        data = body.get("data")
        if not isinstance(data, dict):
            raise FortyGuardError(
                f"Unexpected status response for {activity_id}: "
                f"{json.dumps(body, ensure_ascii=False)[:500]}"
            )
        return data

    def wait_for(
        self,
        activity_id: str,
        *,
        poll_interval: float = 5.0,
        max_wait: float = 900.0,
        links: bool = False,
        on_update: Callable[[str, float], None] | None = None,
    ) -> dict[str, Any]:
        """Poll an activity until it completes, fails, or times out."""
        started = time.monotonic()
        not_found_attempts = 0
        last_status = ""

        while True:
            elapsed = time.monotonic() - started
            try:
                data = self.get_status(activity_id, links=links)
            except FortyGuardError as exc:
                # The docs note that a freshly submitted activity can briefly 404.
                if exc.status_code == 404 and elapsed < 60 and not_found_attempts < 6:
                    not_found_attempts += 1
                    if on_update:
                        on_update("not found yet", elapsed)
                else:
                    exc.activity_id = activity_id
                    raise
            else:
                not_found_attempts = 0
                status = str(data.get("status", "")).strip()
                last_status = status or last_status
                if on_update:
                    on_update(status, elapsed)

                normalized = status.lower()
                if normalized in COMPLETED_STATUSES:
                    return data
                if normalized in FAILED_STATUSES:
                    message = (
                        data.get("message")
                        or data.get("error")
                        or "the activity failed"
                    )
                    raise FortyGuardError(
                        f"Activity {activity_id} failed: {message}",
                        activity_id=activity_id,
                    )

            if elapsed >= max_wait:
                suffix = f" (last status: {last_status})" if last_status else ""
                raise FortyGuardError(
                    f"Timed out after {max_wait:.0f}s waiting for {activity_id}{suffix}. "
                    f"Check later with: fg status {activity_id} --wait",
                    activity_id=activity_id,
                )

            time.sleep(poll_interval)

    # ------------------------------------------------------------------- downloads

    def download(self, url: str) -> bytes:
        """Download a signed result URL without sending the API key to it."""
        try:
            with httpx.Client(follow_redirects=True, timeout=self.timeout) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.content
        except httpx.HTTPError as exc:
            raise FortyGuardError(f"Could not download result file: {exc}") from exc

    # ---------------------------------------------------------------- account usage

    def fetch_usage(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Fetch billing-cycle or custom-range credit usage. Free of charge."""
        if start_date or end_date:
            if not start_date or not end_date:
                raise FortyGuardError("Both start_date and end_date are required.")
            return self.request(
                "POST",
                "/v1/system/fetch-api-key-custom-usage",
                json_body={
                    "api_key": self.api_key,
                    "start_date": f"{start_date}T00:00:00Z",
                    "end_date": f"{end_date}T23:59:59Z",
                },
            )

        return self.request(
            "POST",
            "/v1/system/fetch-api-key-usage",
            json_body={"api_key": self.api_key},
        )


def parse_jsonish(value: Any, *, attempts: int = 2) -> Any:
    """Decode strings that contain JSON, including double-encoded JSON."""
    result = value
    for _ in range(attempts):
        if not isinstance(result, str):
            break
        try:
            result = json.loads(result)
        except (TypeError, ValueError):
            break
    return result


def pick(mapping: Any, *names: str, default: Any = None) -> Any:
    """Case-insensitive lookup for the inconsistent API field names."""
    if not isinstance(mapping, dict):
        return default
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return default


BASE64_PREFIX_RE = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,", re.IGNORECASE)
