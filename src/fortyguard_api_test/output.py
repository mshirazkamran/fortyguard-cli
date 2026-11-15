"""Result printing and artifact handling for the FortyGuard CLI."""

from __future__ import annotations

import base64
import binascii
import json
import re
from pathlib import Path
from typing import Any

import click

from .client import (
    BASE64_PREFIX_RE,
    FortyGuardClient,
    parse_jsonish,
    pick,
)

B64_ONLY_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


# --------------------------------------------------------------------------- files


def ext_from_bytes(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"%PDF"):
        return ".pdf"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    if content.startswith(b"GIF8"):
        return ".gif"
    if content.startswith(b"PK\x03\x04"):
        return ".zip"
    return None


def _extension_from_mime(mime: str) -> str | None:
    mime = mime.lower()
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "application/pdf": ".pdf",
    }.get(mime)


def _looks_like_base64(value: str) -> bool:
    compact = "".join(value.split())
    if len(compact) < 32 or len(compact) % 4 != 0:
        return False
    return bool(B64_ONLY_RE.match(compact))


def strip_binary(value: Any) -> Any:
    """Replace embedded Base64 blobs so metadata files stay small and readable."""
    if isinstance(value, dict):
        return {key: strip_binary(item) for key, item in value.items()}
    if isinstance(value, list):
        return [strip_binary(item) for item in value]
    if isinstance(value, str) and len(value) > 512 and _looks_like_base64(value):
        return "<base64 data omitted>"
    return value


class Artifacts:
    """Write API results under data/<command>/<activity_id>/."""

    def __init__(
        self,
        base_dir: Path,
        command: str,
        activity_id: str | None = None,
        *,
        enabled: bool = True,
        announce: bool = True,
    ) -> None:
        self.base_dir = base_dir
        self.command = command
        self.activity_id = activity_id
        self.enabled = enabled
        self.announce_enabled = announce
        self.paths: list[Path] = []

    @property
    def directory(self) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", self.activity_id or "result")
        return self.base_dir / self.command / safe_id

    def _announce(self, path: Path) -> None:
        if self.announce_enabled:
            click.echo(f"Saved: {path}", err=True)

    def save_bytes(self, filename: str, content: bytes) -> Path | None:
        if not self.enabled:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / filename
        path.write_bytes(content)
        self.paths.append(path)
        self._announce(path)
        return path

    def save_json(self, filename: str, data: Any) -> Path | None:
        if not self.enabled:
            return None
        text = json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n"
        return self.save_bytes(filename, text.encode("utf-8"))

    def save_base64(self, stem: str, value: Any) -> Path | None:
        if not self.enabled or not isinstance(value, str) or not value.strip():
            return None

        compact = value.strip()
        mime_hint: str | None = None
        prefix = BASE64_PREFIX_RE.match(compact)
        if prefix:
            mime_hint = prefix.group("mime")
            compact = compact[prefix.end() :]

        compact = "".join(compact.split())
        if not compact or not _looks_like_base64(compact):
            return None

        try:
            content = base64.b64decode(compact, validate=False)
        except (binascii.Error, ValueError):
            return None

        extension = ext_from_bytes(content)
        if extension is None and mime_hint:
            extension = _extension_from_mime(mime_hint)
        extension = extension or ".png"
        return self.save_bytes(f"{stem}{extension}", content)


# --------------------------------------------------------------------- result saves


def infer_command(result: Any) -> str:
    if not isinstance(result, dict):
        return "result"
    if pick(result, "map_data", "map_download_url"):
        return "heatmap"
    if pick(result, "download_link"):
        return "heat-intelligence"
    if pick(result, "front", "back"):
        return "streetview"
    if pick(result, "segmentation", "original_image", "orignal_image"):
        return "satellite"
    return "result"


def _save_heatmap(
    result: Any, artifacts: Artifacts, client: FortyGuardClient
) -> None:
    result = parse_jsonish(result)
    if not isinstance(result, dict):
        artifacts.save_json("result.json", result)
        return

    map_data = parse_jsonish(pick(result, "map_data"))
    stats_data = parse_jsonish(pick(result, "stats_data"))

    if map_data is None:
        map_url = pick(result, "map_download_url")
        if isinstance(map_url, str) and map_url:
            raw = client.download(map_url)
            parsed = parse_jsonish(raw.decode("utf-8", errors="replace"))
            if isinstance(parsed, (dict, list)):
                map_data = parsed
            else:
                artifacts.save_bytes("map_data.raw", raw)

    if stats_data is None:
        stats_url = pick(result, "stats_download_url")
        if isinstance(stats_url, str) and stats_url:
            raw = client.download(stats_url)
            parsed = parse_jsonish(raw.decode("utf-8", errors="replace"))
            if isinstance(parsed, (dict, list)):
                stats_data = parsed
            else:
                artifacts.save_bytes("stats_data.raw", raw)

    if map_data is not None:
        artifacts.save_json("map_data.geojson", map_data)
    if stats_data is not None:
        artifacts.save_json("stats_data.json", stats_data)
    if map_data is None and stats_data is None:
        artifacts.save_json("result.json", strip_binary(result))

    coverage = pick(result, "coverage")
    if coverage is not None:
        artifacts.save_json("coverage.json", coverage)


def _save_satellite(
    result: Any, artifacts: Artifacts, client: FortyGuardClient
) -> None:
    result = parse_jsonish(result)
    if not isinstance(result, dict):
        artifacts.save_json("result.json", result)
        return

    images = pick(result, "original_image", "orignal_image")
    if isinstance(images, str):
        images = [images]
    if isinstance(images, list):
        for index, image in enumerate(images):
            artifacts.save_base64(f"original_{index}", image)

    segmentation = pick(result, "segmentation")
    if isinstance(segmentation, dict):
        artifacts.save_base64("segmentation", pick(segmentation, "image_content"))
        metadata = {
            key: value
            for key, value in segmentation.items()
            if str(key).lower() != "image_content"
        }
        metadata["coordinates"] = pick(result, "coordinates")
        metadata["image_year"] = pick(result, "image_year")
        metadata["image_date"] = pick(result, "image_date")
        artifacts.save_json("segmentation.json", metadata)
    else:
        artifacts.save_json("metadata.json", strip_binary(result))


def _save_streetview(
    result: Any, artifacts: Artifacts, client: FortyGuardClient
) -> None:
    result = parse_jsonish(result)
    if not isinstance(result, dict):
        artifacts.save_json("result.json", result)
        return

    saved_any = False
    for label in ("front", "back"):
        view = pick(result, label)
        if not isinstance(view, dict):
            continue
        saved_any = True
        artifacts.save_base64(f"{label}_original", pick(view, "original_image"))
        artifacts.save_base64(f"{label}_segmented", pick(view, "segmented_image"))
        metadata = {
            key: value
            for key, value in view.items()
            if str(key).lower() not in {"original_image", "segmented_image"}
        }
        artifacts.save_json(f"{label}_metadata.json", metadata)

    if not saved_any:
        # Some responses return a single, unlabelled view.
        artifacts.save_base64("original", pick(result, "original_image"))
        artifacts.save_base64("segmented", pick(result, "segmented_image"))

    artifacts.save_json("metadata.json", strip_binary(result))


def _save_heat_intelligence(
    result: Any, artifacts: Artifacts, client: FortyGuardClient
) -> None:
    result = parse_jsonish(result)
    if isinstance(result, dict):
        link = pick(result, "download_link")
        if isinstance(link, str) and link:
            content = client.download(link)
            extension = ext_from_bytes(content) or ".pdf"
            artifacts.save_bytes(f"report{extension}", content)
            return
    artifacts.save_json("result.json", strip_binary(result))


def _save_plain(
    result: Any, artifacts: Artifacts, client: FortyGuardClient
) -> None:
    artifacts.save_json("result.json", strip_binary(parse_jsonish(result)))


def handle_result(
    command: str,
    data: dict[str, Any],
    artifacts: Artifacts,
    client: FortyGuardClient,
) -> str:
    """Save the result for a command. Returns the command actually used."""
    result = data.get("result")
    if result is None:
        result = data

    if command in {"status", "result"}:
        command = infer_command(result)
        artifacts.command = command

    handlers = {
        "heatmap": _save_heatmap,
        "satellite": _save_satellite,
        "streetview": _save_streetview,
        "heat-intelligence": _save_heat_intelligence,
        "env-params": _save_plain,
        "routing": _save_plain,
        "result": _save_plain,
    }
    handler = handlers.get(command, _save_plain)
    handler(result, artifacts, client)
    return command


# ------------------------------------------------------------------------ summaries


def format_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    text_rows = [[str(cell) for cell in row] for row in rows]
    widths = [
        max(len(str(headers[index])), *(len(row[index]) for row in text_rows))
        for index in range(len(headers))
    ]
    lines = [
        "  ".join(str(headers[index]).ljust(widths[index]) for index in range(len(headers))),
        "  ".join("-" * widths[index] for index in range(len(headers))),
    ]
    for row in text_rows:
        lines.append(
            "  ".join(row[index].ljust(widths[index]) for index in range(len(headers)))
        )
    return "\n".join(lines)


def _number(value: Any, digits: int = 2) -> str:
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


def _format_segments(segments: Any) -> list[str]:
    if not isinstance(segments, dict):
        return []
    return [f"    {name}: {_number(value)}%" for name, value in segments.items()]


def summarize_result(command: str, data: dict[str, Any]) -> list[str]:
    result = data.get("result")
    if result is None:
        result = data
    result = parse_jsonish(result)

    lines: list[str] = []
    activity_id = data.get("activity_id") or (result.get("activity_id") if isinstance(result, dict) else None)
    status = data.get("status")
    if activity_id or status:
        header = "  ".join(
            part
            for part in (
                f"Activity: {activity_id}" if activity_id else "",
                f"Status: {status}" if status else "",
            )
            if part
        )
        lines.append(header)

    if not isinstance(result, dict):
        return lines

    if command == "heatmap":
        stats = parse_jsonish(pick(result, "stats_data")) or {}
        temperature = pick(stats, "Temperature_stats") or {}
        map_data = parse_jsonish(pick(result, "map_data"))
        features = pick(map_data, "features") if isinstance(map_data, dict) else None
        if isinstance(features, list):
            lines.append(f"Map tiles: {len(features):,}")
        units = pick(stats, "units")
        unit_label = f" {units}" if isinstance(units, str) and units else ""
        minimum = pick(temperature, "Minimum")
        maximum = pick(temperature, "Maximum")
        mean = pick(temperature, "Mean")
        deviation = pick(temperature, "Standard_deviation", "Standard_Deviation")
        if any(value is not None for value in (minimum, maximum, mean)):
            lines.append(
                "Temperature: "
                f"min {_number(minimum)}{unit_label}, "
                f"max {_number(maximum)}{unit_label}, "
                f"mean {_number(mean)}{unit_label}"
            )
        if deviation is not None:
            lines.append(f"Standard deviation: {_number(deviation)}{unit_label}")

    elif command == "satellite":
        coordinates = pick(result, "coordinates")
        if isinstance(coordinates, dict):
            lines.append(
                "Location: "
                f"{pick(coordinates, 'latitude')}, {pick(coordinates, 'longitude')}"
            )
        image_year = pick(result, "image_year")
        if image_year is not None:
            lines.append(f"Imagery year: {image_year}")
        segmentation = pick(result, "segmentation") or {}
        segments = pick(segmentation, "segments")
        if isinstance(segments, dict):
            lines.append("Class coverage:")
            lines.extend(_format_segments(segments))
        dimensions = pick(segmentation, "image_dimensions")
        if isinstance(dimensions, dict):
            lines.append(
                "Image size: "
                f"{pick(dimensions, 'width')}×{pick(dimensions, 'height')}"
            )

    elif command == "streetview":
        coordinates = pick(result, "coordinates")
        if isinstance(coordinates, dict):
            lines.append(
                "Location: "
                f"{pick(coordinates, 'latitude')}, {pick(coordinates, 'longitude')}"
            )
        for label in ("front", "back"):
            view = pick(result, label)
            if not isinstance(view, dict):
                continue
            lines.append(f"{label.capitalize()} view:")
            image_date = pick(view, "image_date")
            if image_date:
                lines.append(f"  Image date: {image_date}")
            segments = pick(view, "segments")
            if isinstance(segments, dict):
                lines.append("  Class coverage:")
                lines.extend(_format_segments(segments))

    elif command == "env-params":
        metadata = pick(result, "metadata") or {}
        timezone = pick(metadata, "timezone")
        if timezone:
            lines.append(f"Timezone: {timezone}")
        parameters = pick(result, "parameters")
        if isinstance(parameters, dict):
            names = list(parameters)
            lines.append(f"Parameters returned: {len(names)}")
            if names:
                lines.append("  " + ", ".join(names))
        solar = pick(result, "solar_irradiance")
        if isinstance(solar, dict):
            lines.append("Solar irradiance: " + ", ".join(solar))

    elif command == "routing":
        routes = pick(result, "routes", "route_alternatives", "alternatives")
        if isinstance(routes, list):
            lines.append(f"Routes returned: {len(routes)}")
            for index, route in enumerate(routes, start=1):
                if not isinstance(route, dict):
                    continue
                distance = pick(route, "distance_km", "distance")
                duration = pick(route, "duration_minutes", "duration")
                details = []
                if distance is not None:
                    details.append(f"{_number(distance)} km")
                if duration is not None:
                    details.append(f"{_number(duration)} min")
                if details:
                    lines.append(f"  Route {index}: " + ", ".join(details))
        else:
            lines.append("Result keys: " + ", ".join(result))

    elif command == "heat-intelligence":
        if pick(result, "download_link"):
            lines.append("PDF report downloaded.")
        else:
            lines.append("Result keys: " + ", ".join(result))

    return lines


def summarize_usage(data: dict[str, Any]) -> list[str]:
    plan = data.get("plan_details") or {}
    key_details = data.get("api_key_details") or {}
    credits = data.get("credit_summary") or {}
    cycle = data.get("billing_cycle") or {}

    lines: list[str] = []
    if plan:
        plan_type = plan.get("plan_type") or "unknown"
        cycle_type = plan.get("cycle_type") or ""
        active = "active" if plan.get("active") else "inactive"
        lines.append(f"Plan: {plan_type}{f' ({cycle_type})' if cycle_type else ''} — {active}")
        if plan.get("subscription_start_date"):
            lines.append(f"Subscription start: {plan['subscription_start_date']}")
        if plan.get("credits_reset_date"):
            lines.append(f"Credits reset on: {plan['credits_reset_date']}")

    if key_details:
        status = key_details.get("status") or "unknown"
        access = "available" if key_details.get("api_access_available") else "unavailable"
        lines.append(f"API key: {status} — API access {access}")
        if key_details.get("expiry_date"):
            lines.append(f"Key expiry: {key_details['expiry_date']}")

    if cycle.get("start_date") and cycle.get("end_date"):
        lines.append(f"Billing cycle: {cycle['start_date']} → {cycle['end_date']}")

    if credits:
        if credits.get("cycle_remaining_credits") is not None:
            lines.append(
                "Credits remaining this cycle: "
                f"{_number(credits['cycle_remaining_credits'], 0)}"
            )
        if credits.get("total_available_credits") is not None:
            lines.append(
                "Total available credits: "
                f"{_number(credits['total_available_credits'], 0)}"
            )

    if data.get("total_credits_used") is not None:
        lines.append(f"Credits used: {_number(data['total_credits_used'], 0)}")

    breakdown = data.get("activity_breakdown")
    if isinstance(breakdown, list) and breakdown:
        rows = [
            [
                item.get("name", "Unknown"),
                _number(item.get("credits"), 0),
                f"{_number(item.get('percentage'), 1)}%",
            ]
            for item in breakdown
            if isinstance(item, dict)
        ]
        lines.append("")
        lines.append("Usage breakdown:")
        lines.append(format_table(["Activity", "Credits", "Share"], rows))

    return lines


def print_json(data: Any) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
