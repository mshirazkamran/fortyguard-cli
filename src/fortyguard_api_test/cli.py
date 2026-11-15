"""Click command line interface for the FortyGuard Temperature API."""

from __future__ import annotations

import copy
import datetime as dt
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from . import __version__
from .client import (
    COMPLETED_STATUSES,
    DEFAULT_BASE_URL,
    FAILED_STATUSES,
    FortyGuardClient,
    FortyGuardError,
    find_env_file,
    load_env_file,
    mask_key,
    resolve_api_key,
)
from .output import (
    Artifacts,
    handle_result,
    print_json,
    summarize_result,
    summarize_usage,
)
from .presets import HEATMAP_EXAMPLE

CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "max_content_width": 110,
}

GRANULARITIES = ["20", "60", "80", "100"]
ANALYTIC_TYPES = ["tcm", "time_of_measure", "exceedance", "persistence"]
HEAT_INTELLIGENCE_CATEGORIES = [
    "geographic",
    "environmental",
    "urban",
    "events",
    "anthropogenic",
]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass
class Settings:
    api_key: str | None
    key_error: str | None
    env_file: Path | None
    base_url: str
    timeout: float
    poll_interval: float
    max_wait: float
    data_dir: Path
    save: bool
    json_output: bool
    verbose: bool


# --------------------------------------------------------------------- validation


def validate_date(value: str, field: str = "--date") -> str:
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        raise click.BadParameter(
            f"expected YYYY-MM-DD, got {value!r}", param_hint=field
        )
    return value


def validate_time(value: str, field: str) -> str:
    if not TIME_RE.match(value):
        raise click.BadParameter(
            f"expected HH:MM in 24-hour time, got {value!r}", param_hint=field
        )
    return value


def validate_coordinates(latitude: float, longitude: float) -> None:
    if not -90 <= latitude <= 90:
        raise click.BadParameter("latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise click.BadParameter("longitude must be between -180 and 180")


def build_date_time(
    *,
    date: str | None,
    start_time: str | None,
    end_time: str | None,
    end_date: str | None,
    filter_type: int | None,
    allowed: tuple[int, ...] = (1, 2, 3, 4),
) -> dict[str, Any]:
    if not date:
        raise click.UsageError("--date is required (YYYY-MM-DD).")
    validate_date(date)

    if filter_type is None:
        if end_date:
            filter_type = 4
        elif end_time:
            filter_type = 2
        elif start_time:
            filter_type = 1
        else:
            filter_type = 3

    if filter_type not in allowed:
        allowed_text = ", ".join(str(item) for item in allowed)
        raise click.UsageError(
            f"filter type {filter_type} is not supported here (allowed: {allowed_text})."
        )

    if filter_type == 1:
        if not start_time:
            raise click.UsageError("filter type 1 requires --start-time HH:MM.")
        validate_time(start_time, "--start-time")
        if end_time or end_date:
            raise click.UsageError(
                "filter type 1 (single hour) accepts only --date and --start-time."
            )
        return {"start_date": date, "start_time": start_time, "filter_type": 1}

    if filter_type == 2:
        if not start_time or not end_time:
            raise click.UsageError(
                "filter type 2 requires --start-time and --end-time."
            )
        validate_time(start_time, "--start-time")
        validate_time(end_time, "--end-time")
        if end_date:
            raise click.UsageError(
                "filter type 2 (same-day range) does not accept --end-date."
            )
        return {
            "start_date": date,
            "start_time": start_time,
            "end_time": end_time,
            "filter_type": 2,
        }

    if filter_type == 3:
        if start_time or end_time or end_date:
            raise click.UsageError(
                "filter type 3 (single day) accepts only --date."
            )
        return {"start_date": date, "filter_type": 3}

    if not end_date:
        raise click.UsageError("filter type 4 requires --end-date YYYY-MM-DD.")
    validate_date(end_date, "--end-date")
    if end_date < date:
        raise click.UsageError("--end-date must be on or after --date.")
    if start_time or end_time:
        raise click.UsageError(
            "filter type 4 (range of days) does not accept times."
        )
    return {"start_date": date, "end_date": end_date, "filter_type": 4}


def build_aoi(aoi: Path | None, bbox: str | None, *, example: bool) -> Any:
    if aoi and bbox:
        raise click.UsageError("Use either --aoi or --bbox, not both.")
    if example and (aoi or bbox):
        raise click.UsageError("--example cannot be combined with --aoi or --bbox.")

    if aoi:
        try:
            data = json.loads(Path(aoi).read_text(encoding="utf-8"))
        except OSError as exc:
            raise click.BadParameter(f"could not read {aoi}: {exc}", param_hint="--aoi")
        except json.JSONDecodeError as exc:
            raise click.BadParameter(
                f"{aoi} is not valid JSON: {exc}", param_hint="--aoi"
            )
        if not isinstance(data, dict):
            raise click.BadParameter(
                "the AOI must be a GeoJSON object", param_hint="--aoi"
            )
        return data

    if bbox:
        parts = [part for part in re.split(r"[,\s]+", bbox.strip()) if part]
        if len(parts) != 4:
            raise click.BadParameter(
                "expected four numbers: west,south,east,north", param_hint="--bbox"
            )
        try:
            west, south, east, north = (float(part) for part in parts)
        except ValueError:
            raise click.BadParameter(
                "all four bbox values must be numbers", param_hint="--bbox"
            )
        if not (-180 <= west < east <= 180):
            raise click.BadParameter(
                "expected -180 <= west < east <= 180", param_hint="--bbox"
            )
        if not (-90 <= south < north <= 90):
            raise click.BadParameter(
                "expected -90 <= south < north <= 90", param_hint="--bbox"
            )
        return {
            "type": "Polygon",
            "coordinates": [
                [
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]
            ],
        }

    raise click.UsageError("Provide --aoi FILE, --bbox W,S,E,N, or --example.")


def load_json_file(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise click.BadParameter(f"could not read {path}: {exc}", param_hint="--json-file")
    except json.JSONDecodeError as exc:
        raise click.BadParameter(
            f"{path} is not valid JSON: {exc}", param_hint="--json-file"
        )
    if not isinstance(data, dict):
        raise click.BadParameter(
            "the payload must be a JSON object", param_hint="--json-file"
        )
    return data


def split_analysis(values: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if item and item not in result:
                result.append(item)
    return result


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


# ----------------------------------------------------------------------- plumbing


def get_client(settings: Settings) -> FortyGuardClient:
    if not settings.api_key:
        raise click.ClickException(
            settings.key_error
            or "FORTYGUARD_KEY is not set. Add it to .env or pass --api-key."
        )
    return FortyGuardClient(
        settings.api_key,
        base_url=settings.base_url,
        timeout=settings.timeout,
        verbose=settings.verbose,
    )


def build_artifacts(
    settings: Settings,
    command: str,
    activity_id: str | None,
    out: Path | None,
) -> Artifacts:
    base_dir = Path(out).expanduser() if out else settings.data_dir
    return Artifacts(
        base_dir,
        command,
        activity_id,
        enabled=settings.save,
    )


def _poll_message(status: str, elapsed: float) -> None:
    label = status or "processing"
    if label.lower() in COMPLETED_STATUSES:
        return
    click.echo(f"  {label} ({elapsed:.0f}s)", err=True)


def run_submission(
    settings: Settings,
    *,
    command: str,
    path: str,
    payload: dict[str, Any],
    no_wait: bool,
    out: Path | None,
    links: bool = False,
) -> None:
    try:
        with get_client(settings) as client:
            activity_id, submit_body = client.submit(path, payload)
            click.echo(f"Submitted {command}. activity_id: {activity_id}", err=True)

            if no_wait:
                if settings.json_output:
                    print_json(submit_body)
                else:
                    click.echo(activity_id)
                    click.echo(
                        f"Resume with: fg status {activity_id} --wait", err=True
                    )
                return

            data = client.wait_for(
                activity_id,
                poll_interval=settings.poll_interval,
                max_wait=settings.max_wait,
                links=links,
                on_update=_poll_message,
            )

            artifacts = build_artifacts(settings, command, activity_id, out)
            actual_command = handle_result(command, data, artifacts, client)

            if settings.json_output:
                print_json(data)
            else:
                lines = summarize_result(actual_command, data)
                if lines:
                    click.echo("\n".join(lines))
                else:
                    print_json(data)
    except FortyGuardError as exc:
        raise click.ClickException(str(exc)) from exc


def submit_options(func: Callable[..., Any]) -> Callable[..., Any]:
    func = click.option(
        "--json-file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="Send a complete JSON payload from this file instead of using flags.",
    )(func)
    func = click.option(
        "--no-wait",
        is_flag=True,
        help="Return the activity_id immediately instead of polling.",
    )(func)
    func = click.option(
        "--out",
        type=click.Path(file_okay=False, path_type=Path),
        help="Directory for saved artifacts (default: the project data/ directory).",
    )(func)
    return func


def date_options(func: Callable[..., Any]) -> Callable[..., Any]:
    func = click.option(
        "--date", help="Start date in YYYY-MM-DD format (required unless --example)."
    )(func)
    func = click.option(
        "--start-time", help="Start time in HH:MM (24-hour). Used by filter types 1 and 2."
    )(func)
    func = click.option(
        "--end-time", help="End time in HH:MM (24-hour). Used by filter type 2."
    )(func)
    func = click.option(
        "--end-date", help="End date in YYYY-MM-DD. Used by filter type 4."
    )(func)
    func = click.option(
        "--filter-type",
        type=click.IntRange(1, 4),
        help=(
            "1=single hour, 2=same-day range, 3=single day, 4=range of days. "
            "Inferred from the date/time flags when omitted."
        ),
    )(func)
    return func


# ---------------------------------------------------------------------- CLI group


@click.group(context_settings=CONTEXT_SETTINGS, no_args_is_help=True)
@click.version_option(__version__, "-V", "--version", prog_name="fg")
@click.option(
    "--api-key",
    help="API key. Overrides FORTYGUARD_KEY from the environment or .env.",
)
@click.option(
    "--base-url",
    default=DEFAULT_BASE_URL,
    show_default=True,
    help="API base URL.",
)
@click.option(
    "--timeout",
    type=float,
    default=120.0,
    show_default=True,
    help="HTTP timeout in seconds.",
)
@click.option(
    "--poll-interval",
    type=float,
    default=5.0,
    show_default=True,
    help="Seconds between status checks.",
)
@click.option(
    "--max-wait",
    type=float,
    default=900.0,
    show_default=True,
    help="Maximum seconds to wait for a task before giving up.",
)
@click.option(
    "--data-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data"),
    show_default=True,
    help="Where images, GeoJSON and reports are saved.",
)
@click.option(
    "--no-save",
    is_flag=True,
    help="Do not write result artifacts to disk.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Print raw JSON instead of a human-readable summary.",
)
@click.option("--verbose", is_flag=True, help="Show HTTP requests and responses.")
@click.pass_context
def cli(
    ctx: click.Context,
    api_key: str | None,
    base_url: str,
    timeout: float,
    poll_interval: float,
    max_wait: float,
    data_dir: Path,
    no_save: bool,
    json_output: bool,
    verbose: bool,
) -> None:
    """FortyGuard Temperature API CLI.

    Test the FortyGuard Temperature API from your terminal. The CLI signs
    requests with your API key, submits asynchronous activities, polls them
    until they finish, and saves images, GeoJSON and reports under data/.

    \b
    AUTHENTICATION
      Set FORTYGUARD_KEY in .env (project root) or pass --api-key.
      API keys and plans: https://fortyguard.com/api-pricing

    \b
    TYPICAL WORKFLOW
      fg doctor                       check configuration and connectivity
      fg credits                      show plan and remaining credits (free)
      fg heatmap --example            run the documented New York sample
      fg status <activity_id> --wait  resume a task you submitted earlier

    \b
    ASYNC TASKS
      Every analysis command waits for completion by default. Use --no-wait
      to get only the activity_id, then poll it later with fg status.

    \b
    COSTS AND COVERAGE
      Analysis commands spend credits when a task completes. Check the
      balance with fg credits first. The API currently covers the US only.

    \b
    EXAMPLES
      fg heatmap --bbox -74.017,40.705,-74.003,40.718 \\
          --date 2024-07-15 --start-time 14:00
      fg env-params --lat 40.7128 --lon -74.0060 --temperature 32.5 \\
          --date 2024-07-15 --start-time 14:00 \\
          --analysis heat_index_celsius
      fg satellite --lat 40.7128 --lon -74.0060 --date 2024-07-15 \\
          --start-time 14:00
      fg status abc123 --wait --json
    """
    env_file = find_env_file()
    load_env_file(env_file)

    key_error: str | None = None
    resolved_key: str | None = None
    try:
        resolved_key = resolve_api_key(api_key)
    except FortyGuardError as exc:
        key_error = str(exc)

    ctx.obj = Settings(
        api_key=resolved_key,
        key_error=key_error,
        env_file=env_file,
        base_url=base_url,
        timeout=timeout,
        poll_interval=poll_interval,
        max_wait=max_wait,
        data_dir=Path(data_dir).expanduser().resolve(),
        save=not no_save,
        json_output=json_output,
        verbose=verbose,
    )


# ------------------------------------------------------------------------- doctor


@cli.command(
    short_help="Check configuration, API key and connectivity (free).",
)
@click.option(
    "--no-request",
    is_flag=True,
    help="Only inspect local configuration; do not call the API.",
)
@click.pass_context
def doctor(ctx: click.Context, no_request: bool) -> None:
    """Check local configuration and verify your API key.

    Reads .env / FORTYGUARD_KEY, checks that the data directory is writable,
    and calls the free credit-usage endpoint to confirm authentication.

    Nothing is charged. Exits with status 1 if a check fails.

    \b
    Examples:
      fg doctor
      fg doctor --no-request
    """
    settings: Settings = ctx.obj
    exit_code = 0

    click.echo("Configuration")
    click.echo(f"  .env file:      {settings.env_file or 'not found'}")
    if settings.api_key:
        click.echo(f"  FORTYGUARD_KEY: set ({mask_key(settings.api_key)})")
    else:
        click.echo("  FORTYGUARD_KEY: missing")
        exit_code = 1
    click.echo(f"  Base URL:       {settings.base_url}")
    click.echo(f"  Data directory: {settings.data_dir}")

    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.data_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        click.echo("  Data directory: writable")
    except OSError as exc:
        click.echo(f"  Data directory: NOT writable ({exc})")
        exit_code = 1

    click.echo("")
    click.echo("API")
    if no_request:
        click.echo("  Authentication: skipped (--no-request)")
    elif not settings.api_key:
        click.echo(f"  Authentication: skipped ({settings.key_error})")
        exit_code = 1
    else:
        try:
            with get_client(settings) as client:
                data = client.fetch_usage()
            click.echo("  Authentication: OK (free usage endpoint)")
            usage = summarize_usage(data)
            for line in usage[:4]:
                click.echo(f"  {line}")
        except (FortyGuardError, click.ClickException) as exc:
            click.echo(f"  Authentication: FAILED — {exc}")
            exit_code = 1

    if settings.key_error and not settings.api_key:
        click.echo("")
        click.echo(f"Hint: {settings.key_error}")

    if exit_code:
        ctx.exit(exit_code)


# ------------------------------------------------------------------------ credits


@cli.command(short_help="Show plan and credit usage (free).")
@click.option("--start-date", help="Custom range start date YYYY-MM-DD.")
@click.option("--end-date", help="Custom range end date YYYY-MM-DD.")
@click.pass_context
def credits(
    ctx: click.Context, start_date: str | None, end_date: str | None
) -> None:
    """Show subscription details and credit consumption.

    Calls POST /v1/system/fetch-api-key-usage for the current billing cycle,
    or the custom-range endpoint when both dates are supplied. This endpoint
    does not consume credits.

    \b
    Examples:
      fg credits
      fg credits --start-date 2024-07-01 --end-date 2024-07-31
      fg credits --json
    """
    settings: Settings = ctx.obj
    if bool(start_date) != bool(end_date):
        raise click.UsageError("Provide both --start-date and --end-date, or neither.")
    if start_date:
        validate_date(start_date, "--start-date")
        validate_date(end_date, "--end-date")
        if end_date < start_date:
            raise click.UsageError("--end-date must be on or after --start-date.")

    try:
        with get_client(settings) as client:
            data = client.fetch_usage(start_date=start_date, end_date=end_date)
    except FortyGuardError as exc:
        raise click.ClickException(str(exc)) from exc

    if settings.json_output:
        print_json(data)
        return

    lines = summarize_usage(data)
    if lines:
        click.echo("\n".join(lines))
    else:
        print_json(data)


# ------------------------------------------------------------------------ heatmap


@cli.command(short_help="Generate a thermal heatmap (3,500 credits).")
@click.option(
    "--aoi",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="GeoJSON file with the area of interest (Polygon, Feature or FeatureCollection).",
)
@click.option("--bbox", help="Bounding box as west,south,east,north (alternative to --aoi).")
@click.option(
    "--example",
    is_flag=True,
    help="Use the documentation's New York AOI and 2024-07-15 14:00 example.",
)
@date_options
@click.option(
    "--granularity",
    type=click.Choice(GRANULARITIES),
    default="100",
    show_default=True,
    help="Tile size in metres.",
)
@click.option(
    "--analytic-type",
    type=click.Choice(ANALYTIC_TYPES),
    default="tcm",
    show_default=True,
    help="tcm=temperature, time_of_measure=hour, exceedance/persistence=threshold hours.",
)
@click.option("--threshold", type=float, help="Threshold in °C for exceedance/persistence.")
@click.option(
    "--direction",
    type=click.Choice(["above", "below"]),
    help="Count hours above or below --threshold.",
)
@click.option(
    "--links",
    is_flag=True,
    help="Ask for signed download links instead of inline map/stats data.",
)
@submit_options
@click.pass_context
def heatmap(
    ctx: click.Context,
    aoi: Path | None,
    bbox: str | None,
    example: bool,
    date: str | None,
    start_time: str | None,
    end_time: str | None,
    end_date: str | None,
    filter_type: int | None,
    granularity: str,
    analytic_type: str,
    threshold: float | None,
    direction: str | None,
    links: bool,
    json_file: Path | None,
    no_wait: bool,
    out: Path | None,
) -> None:
    """Generate a high-resolution heatmap for a polygon.

    Endpoint: POST /v1/heatmap (async). Returns GeoJSON tiles (map_data) and
    aggregated statistics (stats_data). Basic/Startup cost 3,500 credits,
    Premium 4,220. Heatmaps are limited to 10 mi² (Basic) or 50 mi² (Premium).

    \b
    Filter types:
      1  single hour        --date --start-time
      2  same-day range     --date --start-time --end-time
      3  single day         --date
      4  range of days      --date --end-date (at most 31 days)

    \b
    Examples:
      fg heatmap --example
      fg heatmap --bbox -74.017,40.705,-74.003,40.718 \\
          --date 2024-07-15 --start-time 14:00
      fg heatmap --aoi area.geojson --date 2024-07-15 \\
          --start-time 06:00 --end-time 18:00 --granularity 60
      fg heatmap --example --analytic-type exceedance --threshold 35 \\
          --direction above --no-wait
    """
    settings: Settings = ctx.obj

    def build_payload() -> dict[str, Any]:
        if example:
            if aoi or bbox:
                raise click.UsageError(
                    "--example cannot be combined with --aoi or --bbox."
                )
            payload = copy.deepcopy(HEATMAP_EXAMPLE)
            preset = payload["date_time"]
            effective_date = date or preset["start_date"]
            effective_start = start_time
            if (
                effective_start is None
                and filter_type in (None, 1)
                and not end_time
                and not end_date
            ):
                effective_start = preset.get("start_time")
            payload["date_time"] = build_date_time(
                date=effective_date,
                start_time=effective_start,
                end_time=end_time,
                end_date=end_date,
                filter_type=filter_type,
            )
        else:
            payload = {
                "polygon_aoi": build_aoi(aoi, bbox, example=example),
                "date_time": build_date_time(
                    date=date,
                    start_time=start_time,
                    end_time=end_time,
                    end_date=end_date,
                    filter_type=filter_type,
                ),
            }

        payload["granularity"] = int(granularity)
        payload["analytic_type"] = analytic_type
        if threshold is not None:
            payload["threshold"] = threshold
        if direction is not None:
            payload["direction"] = direction
        return payload

    payload = load_json_file(json_file)
    if payload is None:
        payload = build_payload()
    run_submission(
        settings,
        command="heatmap",
        path="/v1/heatmap",
        payload=payload,
        no_wait=no_wait,
        out=out,
        links=links,
    )


# ---------------------------------------------------------------------- satellite


@cli.command(short_help="Satellite segmentation, saves images (14,400 credits).")
@click.option("--lat", type=float, help="Latitude of the point to analyse.")
@click.option("--lon", type=float, help="Longitude of the point to analyse.")
@date_options
@click.option(
    "--granularity",
    type=click.Choice(GRANULARITIES),
    default="100",
    show_default=True,
    help="Tile size in metres (20 uses an 80×80 pixel crop).",
)
@submit_options
@click.pass_context
def satellite(
    ctx: click.Context,
    lat: float | None,
    lon: float | None,
    date: str | None,
    start_time: str | None,
    end_time: str | None,
    end_date: str | None,
    filter_type: int | None,
    granularity: str,
    json_file: Path | None,
    no_wait: bool,
    out: Path | None,
) -> None:
    """Run satellite-view segmentation for one point.

    Endpoint: POST /v1/satellite (async, Premium only, 14,400 credits).
    Returns Base64 original imagery, a segmentation mask and per-class
    coverage. Images are decoded and saved under data/satellite/.

    \b
    Examples:
      fg satellite --lat 40.7128 --lon -74.0060 \\
          --date 2024-07-15 --start-time 14:00
      fg satellite --lat 34.0522 --lon -118.2437 \\
          --date 2024-07-01 --filter-type 3 --granularity 20
    """
    settings: Settings = ctx.obj

    def build_payload() -> dict[str, Any]:
        if lat is None or lon is None:
            raise click.UsageError("--lat and --lon are required.")
        validate_coordinates(lat, lon)
        return {
            "sat": {"latitude": lat, "longitude": lon},
            "date_time": build_date_time(
                date=date,
                start_time=start_time,
                end_time=end_time,
                end_date=end_date,
                filter_type=filter_type,
                allowed=(1, 2, 3),
            ),
            "granularity": int(granularity),
        }

    payload = load_json_file(json_file)
    if payload is None:
        payload = build_payload()
    run_submission(
        settings,
        command="satellite",
        path="/v1/satellite",
        payload=payload,
        no_wait=no_wait,
        out=out,
    )


# --------------------------------------------------------------------- streetview


@cli.command(short_help="Street-view segmentation, saves images (8,600 credits).")
@click.option("--lat", type=float, help="Latitude of the street-view location.")
@click.option("--lon", type=float, help="Longitude of the street-view location.")
@click.option(
    "--vertical-angle",
    type=float,
    default=10.0,
    show_default=True,
    help="Vertical camera angle in degrees (tilt up/down).",
)
@click.option(
    "--horizontal-angle",
    type=float,
    default=90.0,
    show_default=True,
    help="Horizontal camera angle in degrees (0–360).",
)
@click.option(
    "--back-view/--no-back-view",
    default=False,
    show_default=True,
    help="Also capture the opposite direction.",
)
@submit_options
@click.pass_context
def streetview(
    ctx: click.Context,
    lat: float | None,
    lon: float | None,
    vertical_angle: float,
    horizontal_angle: float,
    back_view: bool,
    json_file: Path | None,
    no_wait: bool,
    out: Path | None,
) -> None:
    """Run street-view segmentation at one location.

    Endpoint: POST /v1/streetview (async, Premium only, 8,600 credits).
    Returns Base64 original and segmented images, class coverage, a colour
    legend and the imagery capture date. Files are saved under data/streetview/.

    \b
    Example:
      fg streetview --lat 40.7128 --lon -74.0060 \\
          --vertical-angle 10 --horizontal-angle 90 --back-view
    """
    settings: Settings = ctx.obj

    def build_payload() -> dict[str, Any]:
        if lat is None or lon is None:
            raise click.UsageError("--lat and --lon are required.")
        validate_coordinates(lat, lon)
        if not 0 <= horizontal_angle <= 360:
            raise click.UsageError("--horizontal-angle must be between 0 and 360.")
        if not -90 <= vertical_angle <= 90:
            raise click.UsageError("--vertical-angle must be between -90 and 90.")
        return {
            "latitude": lat,
            "longitude": lon,
            "vertical_angle": vertical_angle,
            "horizontal_angle": horizontal_angle,
            "back_view": back_view,
        }

    payload = load_json_file(json_file)
    if payload is None:
        payload = build_payload()
    run_submission(
        settings,
        command="streetview",
        path="/v1/streetview",
        payload=payload,
        no_wait=no_wait,
        out=out,
    )


# --------------------------------------------------------------- heat intelligence


@cli.command(
    name="heat-intelligence",
    short_help="Generate a Heat Intelligence PDF report (8,600 credits).",
)
@click.option("--lat", type=float, help="Latitude of the location.")
@click.option("--lon", type=float, help="Longitude of the location.")
@click.option(
    "--temperature",
    type=float,
    help="Temperature for the location. The field is documented as °F; pass the value the API expects.",
)
@click.option("--date", help="Date in YYYY-MM-DD format.")
@click.option(
    "--analysis",
    multiple=True,
    type=click.Choice(HEAT_INTELLIGENCE_CATEGORIES),
    help=(
        "Analysis category (repeatable): geographic, environmental, urban, "
        "events, anthropogenic. Defaults to all five."
    ),
)
@submit_options
@click.pass_context
def heat_intelligence(
    ctx: click.Context,
    lat: float | None,
    lon: float | None,
    temperature: float | None,
    date: str | None,
    analysis: tuple[str, ...],
    json_file: Path | None,
    no_wait: bool,
    out: Path | None,
) -> None:
    """Generate a multi-dimensional Heat Intelligence report.

    Endpoint: POST /v1/heat_intelligence (async, Premium only, 8,600 credits).
    The completed status response contains a temporary PDF download link; the
    CLI downloads it immediately to data/heat-intelligence/ and does not print
    the signed URL.

    \b
    Example:
      fg heat-intelligence --lat 40.7128 --lon -74.0060 \\
          --temperature 96.8 --date 2024-07-15 \\
          --analysis geographic --analysis environmental
    """
    settings: Settings = ctx.obj

    def build_payload() -> dict[str, Any]:
        if lat is None or lon is None:
            raise click.UsageError("--lat and --lon are required.")
        if temperature is None:
            raise click.UsageError("--temperature is required.")
        if not date:
            raise click.UsageError("--date is required.")
        validate_coordinates(lat, lon)
        validate_date(date)
        categories = list(analysis) or list(HEAT_INTELLIGENCE_CATEGORIES)
        return {
            "latitude": lat,
            "longitude": lon,
            "temperature": temperature,
            "date": date,
            "analysis": categories,
        }

    payload = load_json_file(json_file)
    if payload is None:
        payload = build_payload()
    run_submission(
        settings,
        command="heat-intelligence",
        path="/v1/heat_intelligence",
        payload=payload,
        no_wait=no_wait,
        out=out,
    )


# --------------------------------------------------------------------- env-params


@cli.command(name="env-params", short_help="Environmental parameters (2,110–2,900 credits).")
@click.option("--lat", type=float, help="Latitude of the location.")
@click.option("--lon", type=float, help="Longitude of the location.")
@click.option(
    "--temperature",
    type=float,
    help="Temperature in °C for the location (required by the API).",
)
@date_options
@click.option(
    "--analysis",
    multiple=True,
    help=(
        "Parameter to return (repeatable or comma-separated), e.g. "
        "heat_index_celsius, wet_bulb_temperature_celsius, air_quality:idx, "
        "solar_irradiance. Omit for all parameters."
    ),
)
@submit_options
@click.pass_context
def env_params(
    ctx: click.Context,
    lat: float | None,
    lon: float | None,
    temperature: float | None,
    date: str | None,
    start_time: str | None,
    end_time: str | None,
    end_date: str | None,
    filter_type: int | None,
    analysis: tuple[str, ...],
    json_file: Path | None,
    no_wait: bool,
    out: Path | None,
) -> None:
    """Fetch heat index, wet bulb, air quality, solar and other parameters.

    Endpoint: POST /v1/env_params (async). Costs 2,110 credits on Basic and
    Startup, 2,900 on Premium. Basic/Startup plans allow up to 3 parameters
    per request; Premium allows all. Missing values are returned as null.

    \b
    Examples:
      fg env-params --lat 40.7128 --lon -74.0060 --temperature 32.5 \\
          --date 2024-07-15 --start-time 14:00
      fg env-params --lat 40.7128 --lon -74.0060 --temperature 32.5 \\
          --date 2024-07-15 --filter-type 3 \\
          --analysis heat_index_celsius --analysis air_quality:idx
    """
    settings: Settings = ctx.obj

    def build_payload() -> dict[str, Any]:
        if lat is None or lon is None:
            raise click.UsageError("--lat and --lon are required.")
        if temperature is None:
            raise click.UsageError("--temperature is required.")
        validate_coordinates(lat, lon)
        payload: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "temperature": temperature,
            "date_time": build_date_time(
                date=date,
                start_time=start_time,
                end_time=end_time,
                end_date=end_date,
                filter_type=filter_type,
                allowed=(1, 2, 3),
            ),
        }
        selected = split_analysis(analysis)
        if selected:
            payload["analysis"] = selected
        return payload

    payload = load_json_file(json_file)
    if payload is None:
        payload = build_payload()
    run_submission(
        settings,
        command="env-params",
        path="/v1/env_params",
        payload=payload,
        no_wait=no_wait,
        out=out,
    )


# ------------------------------------------------------------------------ routing


@cli.command(short_help="Temperature-aware routing (3,500 credits).")
@click.option("--origin-lat", type=float, help="Origin latitude.")
@click.option("--origin-lon", type=float, help="Origin longitude.")
@click.option("--dest-lat", type=float, help="Destination latitude.")
@click.option("--dest-lon", type=float, help="Destination longitude.")
@click.option(
    "--departure-time",
    help="ISO-8601 departure datetime, e.g. 2026-10-19T12:00:00Z.",
)
@submit_options
@click.pass_context
def routing(
    ctx: click.Context,
    origin_lat: float | None,
    origin_lon: float | None,
    dest_lat: float | None,
    dest_lon: float | None,
    departure_time: str | None,
    json_file: Path | None,
    no_wait: bool,
    out: Path | None,
) -> None:
    """Generate temperature-aware route alternatives.

    Endpoint: POST /v1/routing (async, Premium only, 3,500 credits).
    Origin and destination must be no more than 200 km apart (straight-line).
    The result is retrieved from the normal status endpoint.

    \b
    Example:
      fg routing --origin-lat 40.7812 --origin-lon -73.9665 \\
          --dest-lat 40.7580 --dest-lon -73.9855 \\
          --departure-time 2026-10-19T12:00:00Z
    """
    settings: Settings = ctx.obj

    def build_payload() -> dict[str, Any]:
        required = {
            "--origin-lat": origin_lat,
            "--origin-lon": origin_lon,
            "--dest-lat": dest_lat,
            "--dest-lon": dest_lon,
            "--departure-time": departure_time,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise click.UsageError("Missing required options: " + ", ".join(missing))
        assert origin_lat is not None and origin_lon is not None
        assert dest_lat is not None and dest_lon is not None
        assert departure_time is not None

        validate_coordinates(origin_lat, origin_lon)
        validate_coordinates(dest_lat, dest_lon)
        try:
            dt.datetime.fromisoformat(departure_time.replace("Z", "+00:00"))
        except ValueError:
            raise click.BadParameter(
                "expected an ISO-8601 datetime such as 2026-10-19T12:00:00Z",
                param_hint="--departure-time",
            )

        distance = haversine_km(origin_lat, origin_lon, dest_lat, dest_lon)
        if distance > 200:
            raise click.UsageError(
                f"origin and destination are {distance:.1f} km apart; "
                "the API limit is 200 km straight-line."
            )

        return {
            "origin": {"lat": origin_lat, "lon": origin_lon},
            "destination": {"lat": dest_lat, "lon": dest_lon},
            "departure_time": departure_time,
        }

    payload = load_json_file(json_file)
    if payload is None:
        payload = build_payload()
    run_submission(
        settings,
        command="routing",
        path="/v1/routing",
        payload=payload,
        no_wait=no_wait,
        out=out,
    )


# ------------------------------------------------------------------------- status


@cli.command(short_help="Get the status or result of an activity (free).")
@click.argument("activity_id")
@click.option(
    "--wait",
    is_flag=True,
    help="Keep polling until the activity is Completed or Failed.",
)
@click.option(
    "--links",
    is_flag=True,
    help="Request signed map/stats download links for large heatmaps.",
)
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory for saved artifacts (default: the project data/ directory).",
)
@click.pass_context
def status(
    ctx: click.Context,
    activity_id: str,
    wait: bool,
    links: bool,
    out: Path | None,
) -> None:
    """Check an activity and retrieve its result when it is finished.

    Endpoint: GET /v1/status/{activity_id}. All submit commands return an
    activity_id; use this command later to resume polling after --no-wait,
    a timeout, or Ctrl+C. Completed results are saved like the original
    command would save them.

    \b
    Examples:
      fg status abc123
      fg status abc123 --wait
      fg status abc123 --wait --json
    """
    settings: Settings = ctx.obj

    try:
        with get_client(settings) as client:
            if wait:
                data = client.wait_for(
                    activity_id,
                    poll_interval=settings.poll_interval,
                    max_wait=settings.max_wait,
                    links=links,
                    on_update=_poll_message,
                )
            else:
                data = client.get_status(activity_id, links=links)

            state = str(data.get("status", "")).strip()
            normalized = state.lower()

            if normalized in FAILED_STATUSES:
                message = data.get("message") or data.get("error") or "the activity failed"
                raise FortyGuardError(
                    f"Activity {activity_id} failed: {message}",
                    activity_id=activity_id,
                )

            if normalized not in COMPLETED_STATUSES:
                if settings.json_output:
                    print_json(data)
                else:
                    click.echo(f"Activity: {activity_id}")
                    click.echo(f"Status: {state or 'unknown'}")
                    click.echo(
                        f"Check again with: fg status {activity_id} --wait", err=True
                    )
                return

            artifacts = build_artifacts(settings, "status", activity_id, out)
            actual_command = handle_result("status", data, artifacts, client)

            if settings.json_output:
                print_json(data)
            else:
                lines = summarize_result(actual_command, data)
                if lines:
                    click.echo("\n".join(lines))
                else:
                    print_json(data)
    except FortyGuardError as exc:
        raise click.ClickException(str(exc)) from exc


# ---------------------------------------------------------------------------- raw


@cli.command(short_help="Send an arbitrary authenticated request.")
@click.argument(
    "method",
    type=click.Choice(["GET", "POST", "PUT", "PATCH", "DELETE"], case_sensitive=False),
)
@click.argument("path")
@click.option(
    "--json-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="JSON request body read from a file.",
)
@click.option("--body", help="JSON request body as a string.")
@click.option(
    "--query",
    multiple=True,
    help="Query parameter as key=value (repeatable).",
)
@click.pass_context
def raw(
    ctx: click.Context,
    method: str,
    path: str,
    json_file: Path | None,
    body: str | None,
    query: tuple[str, ...],
) -> None:
    """Send any authenticated request and print the JSON response.

    An escape hatch for exploring endpoints or testing payloads that the
    dedicated commands do not cover. No artifacts are saved and no result
    summarising is performed.

    \b
    Examples:
      fg raw GET /v1/status/abc123
      fg raw POST /v1/heatmap --json-file payload.json
      fg raw GET /v1/monitors --query limit=10
    """
    settings: Settings = ctx.obj

    if json_file and body:
        raise click.UsageError("Use either --json-file or --body, not both.")

    payload: dict[str, Any] | None = None
    if json_file:
        payload = load_json_file(json_file)
    elif body:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise click.BadParameter(f"invalid JSON: {exc}", param_hint="--body")
        if not isinstance(parsed, dict):
            raise click.BadParameter(
                "the body must be a JSON object", param_hint="--body"
            )
        payload = parsed

    params: dict[str, str] = {}
    for item in query:
        if "=" not in item:
            raise click.BadParameter(
                f"expected key=value, got {item!r}", param_hint="--query"
            )
        name, value = item.split("=", 1)
        params[name] = value

    if not path.startswith("/"):
        path = "/" + path

    try:
        with get_client(settings) as client:
            data = client.request(
                method.upper(),
                path,
                json_body=payload,
                params=params or None,
            )
    except FortyGuardError as exc:
        raise click.ClickException(str(exc)) from exc

    print_json(data)


if __name__ == "__main__":
    cli()
