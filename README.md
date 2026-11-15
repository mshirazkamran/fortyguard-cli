# FortyGuard API Test CLI

A command-line tool for testing the [FortyGuard Temperature API®](https://docs-api.fortyguard.com). It handles API-key authentication, submits asynchronous analysis tasks, polls them until they finish, prints a readable summary, and saves images, GeoJSON and reports under `data/`.

Built with [Click](https://click.palletsprojects.com/) and [httpx](https://www.python-httpx.org/).

> **API coverage:** the FortyGuard API currently returns data for locations inside the United States only. Dates are subject to server-side availability validation (the default earliest date is 2019-01-01).

---

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A FortyGuard API key. Plans and keys: <https://fortyguard.com/api-pricing>

## Setup

```bash
# 1. Install dependencies and the CLI
uv sync

# 2. Configure your key
cp .env.example .env
# edit .env and set:
# FORTYGUARD_KEY=your_api_key_here

# 3. Verify everything (free — does not consume credits)
uv run fg doctor
```

The CLI reads `FORTYGUARD_KEY` from the nearest `.env` file (walking up from the current directory) or from the process environment. `--api-key` overrides both.

You can also run the CLI without `uv run` after activating the virtual environment:

```bash
source .venv/bin/activate
fg --help
```

`fortyguard` is installed as an alias for `fg`.

---

## Quick start

```bash
# Check configuration and authentication
uv run fg doctor

# Show your plan and remaining credits (free)
uv run fg credits

# Run the documented New York heatmap example (costs 3,500 credits on Basic/Startup)
uv run fg heatmap --example

# Fetch environmental parameters for one point
uv run fg env-params --lat 40.7128 --lon -74.0060 --temperature 32.5 \
  --date 2024-07-15 --start-time 14:00 \
  --analysis heat_index_celsius --analysis wet_bulb_temperature_celsius

# Resume or inspect a task later
uv run fg status <activity_id> --wait
```

---

## Sample commands

[`commands.md`](commands.md) is a ready-to-run cookbook: open it, copy a
command, and run it. It contains examples for **every endpoint** using three
US locations — **Miami, Denver and San Jose** — including location
coordinates, heatmap bounding boxes, filter types, analysis options, routing
pairs and request payloads.

Start with the free examples (`doctor`, `credits`), then copy a paid command
such as:

```bash
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --start-time 14:00
```

See [`commands.md`](commands.md) for the full set.

---

## Command reference

Every command also has copy-paste examples in
[`commands.md`](commands.md).

| Command | Endpoint | Credits | Returns |
|---|---|---|---|
| `fg doctor` | free usage call | 0 | Configuration, key and connectivity check |
| `fg credits` | `POST /v1/system/fetch-api-key-usage` | 0 | Plan, key status, remaining credits, usage breakdown |
| `fg heatmap` | `POST /v1/heatmap` | 3,500 Basic/Startup · 4,220 Premium | GeoJSON tiles + temperature statistics |
| `fg satellite` | `POST /v1/satellite` | 14,400 (Premium) | Base64 imagery, segmentation mask, class coverage |
| `fg streetview` | `POST /v1/streetview` | 8,600 (Premium) | Front/back imagery, masks, class coverage, capture date |
| `fg heat-intelligence` | `POST /v1/heat_intelligence` | 8,600 (Premium) | PDF Heat Intelligence report |
| `fg env-params` | `POST /v1/env_params` | 2,110 Basic/Startup · 2,900 Premium | Heat index, wet bulb, AQI, solar and other parameters |
| `fg routing` | `POST /v1/routing` | 3,500 (Premium) | Temperature-aware route alternatives |
| `fg status` | `GET /v1/status/{activity_id}` | 0 | Status, and the saved result when completed |
| `fg raw` | any path | varies | Raw JSON response from any authenticated request |

Credits are deducted only when a task reaches `Completed`. Failed tasks and `400`/`422` validation errors are not charged.

### Global options

These go **before** the command name:

```bash
uv run fg [OPTIONS] COMMAND [ARGS]
```

| Option | Default | Purpose |
|---|---|---|
| `--api-key TEXT` | `FORTYGUARD_KEY` | Override the API key |
| `--base-url TEXT` | `https://api.fortyguard.com` | API base URL |
| `--timeout FLOAT` | `120` | HTTP timeout in seconds |
| `--poll-interval FLOAT` | `5` | Seconds between status checks |
| `--max-wait FLOAT` | `900` | Maximum seconds to wait for a task |
| `--data-dir DIRECTORY` | `data` | Where artifacts are saved |
| `--no-save` | off | Do not write artifacts |
| `--json` | off | Print raw JSON instead of a summary |
| `--verbose` | off | Show HTTP requests and responses |
| `-V, --version` | | Show the version |
| `-h, --help` | | Show help |

Per-command options include `--no-wait`, `--out DIRECTORY` and `--json-file FILE` (send a complete hand-written payload instead of flags).

---

## Async workflow

Every analysis command is asynchronous:

1. The CLI submits the payload and receives an `activity_id`.
2. By default it polls `GET /v1/status/{activity_id}` every `--poll-interval` seconds until `Completed` or `Failed`.
3. On completion it prints a summary and saves the result.
4. On failure, timeout, or `Ctrl+C`, the `activity_id` is shown so you can resume with `fg status <id> --wait`.

Use `--no-wait` to return immediately:

```bash
uv run fg heatmap --example --no-wait
# heatmap_abc123

uv run fg status heatmap_abc123 --wait
```

Add `--json` for machine-readable output. Progress messages and saved-file paths go to stderr, so stdout stays valid JSON:

```bash
uv run fg --json status heatmap_abc123 --wait > result.json
```

---

## Commands in detail

### `fg doctor`

Checks the `.env` file, key presence, data-directory permissions, and authentication. Uses the free credit-usage endpoint, so nothing is charged.

```bash
uv run fg doctor
uv run fg doctor --no-request   # local checks only
```

### `fg credits`

```bash
uv run fg credits
uv run fg credits --start-date 2024-07-01 --end-date 2024-07-31
uv run fg credits --json
```

### `fg heatmap`

Endpoint: `POST /v1/heatmap`

```bash
# Documentation example (New York, 2024-07-15 14:00)
uv run fg heatmap --example

# Bounding box: west,south,east,north
uv run fg heatmap --bbox -74.017,40.705,-74.003,40.718 \
  --date 2024-07-15 --start-time 14:00

# Full GeoJSON area of interest, 60 m tiles
uv run fg heatmap --aoi area.geojson --date 2024-07-15 \
  --start-time 06:00 --end-time 18:00 --granularity 60

# Exceedance analysis: hours above 35 °C
uv run fg heatmap --example --analytic-type exceedance \
  --threshold 35 --direction above
```

Filter types:

| Type | Meaning | Required options |
|---|---|---|
| `1` | Single hour | `--date --start-time` |
| `2` | Same-day range of hours | `--date --start-time --end-time` |
| `3` | Single day | `--date` |
| `4` | Range of days (≤ 31 days) | `--date --end-date` |

If `--filter-type` is omitted, it is inferred from the date/time options. Granularity is `20`, `60`, `80` or `100` metres (default `100`). Analytic types are `tcm` (temperature), `time_of_measure`, `exceedance` and `persistence`.

Saved files: `map_data.geojson`, `stats_data.json`, plus `coverage.json` when the API returns coverage metadata. For large maps, `--links` requests signed download URLs, which the CLI downloads and saves.

### `fg satellite`

Endpoint: `POST /v1/satellite` — Premium only.

```bash
uv run fg satellite --lat 40.7128 --lon -74.0060 \
  --date 2024-07-15 --start-time 14:00

uv run fg satellite --lat 34.0522 --lon -118.2437 \
  --date 2024-07-01 --filter-type 3 --granularity 20
```

Saved files: `original_0.png` (one per image), `segmentation.png` and `segmentation.json` (class percentages, legend, dimensions).

### `fg streetview`

Endpoint: `POST /v1/streetview` — Premium only.

```bash
uv run fg streetview --lat 40.7128 --lon -74.0060 \
  --vertical-angle 10 --horizontal-angle 90 --back-view
```

Saved files: `front_original.png`, `front_segmented.png`, `front_metadata.json`, and the same `back_*` files when `--back-view` is used.

### `fg heat-intelligence`

Endpoint: `POST /v1/heat_intelligence` — Premium only.

```bash
uv run fg heat-intelligence --lat 40.7128 --lon -74.0060 \
  --temperature 96.8 --date 2024-07-15 \
  --analysis geographic --analysis environmental
```

`--analysis` accepts `geographic`, `environmental`, `urban`, `events` and `anthropogenic`; it defaults to all five. The completed response contains a temporary signed URL. The CLI downloads the PDF to `data/heat-intelligence/<activity_id>/report.pdf` and deliberately does not print the URL.

### `fg env-params`

Endpoint: `POST /v1/env_params`

```bash
# All available parameters
uv run fg env-params --lat 40.7128 --lon -74.0060 --temperature 32.5 \
  --date 2024-07-15 --start-time 14:00

# Specific parameters (Basic/Startup allow up to 3 per request)
uv run fg env-params --lat 40.7128 --lon -74.0060 --temperature 32.5 \
  --date 2024-07-15 --filter-type 3 \
  --analysis heat_index_celsius,wet_bulb_temperature_celsius,relative_humidity_percent
```

Useful parameter names include `heat_index_celsius`, `apparent_temperature_celsius`, `wet_bulb_temperature_celsius`, `relative_humidity_percent`, `precipitation_mm`, `cloud_cover_octas`, `elevation`, `air_quality:idx`, `air_quality_pm2p5:idx`, `air_quality_pm10:idx`, `air_quality_no2:idx`, `aqi_us_co`, `air_quality_o3:idx`, `air_quality_so2:idx`, `methane_ppb`, `co2_ppm` and `solar_irradiance`.

Missing numeric values are returned as `null` by the API.

### `fg routing`

Endpoint: `POST /v1/routing` — Premium only.

```bash
uv run fg routing --origin-lat 40.7812 --origin-lon -73.9665 \
  --dest-lat 40.7580 --dest-lon -73.9855 \
  --departure-time 2026-10-19T12:00:00Z
```

The origin and destination must be no more than 200 km apart (straight-line distance). The CLI checks this before submitting.

### `fg status`

Endpoint: `GET /v1/status/{activity_id}`

```bash
uv run fg status abc123
uv run fg status abc123 --wait
uv run fg status abc123 --wait --links --json
```

When the activity is complete, the CLI detects the result type (heatmap, satellite, streetview, Heat Intelligence, JSON) and saves it using the same rules as the original command.

### `fg raw`

Escape hatch for endpoints and payloads not covered by the dedicated commands.

```bash
uv run fg raw GET /v1/status/abc123
uv run fg raw POST /v1/heatmap --json-file payload.json
uv run fg raw GET /v1/monitors --query limit=10
```

The response is printed as JSON; no artifacts are saved.

---

## Saved files

By default results are written under the project's `data/` directory:

```text
data/
├── heatmap/
│   └── <activity_id>/
│       ├── map_data.geojson
│       ├── stats_data.json
│       └── coverage.json            # only when returned
├── satellite/
│   └── <activity_id>/
│       ├── original_0.png
│       ├── segmentation.png
│       └── segmentation.json
├── streetview/
│   └── <activity_id>/
│       ├── front_original.png
│       ├── front_segmented.png
│       ├── front_metadata.json
│       └── back_*                   # with --back-view
├── heat-intelligence/
│   └── <activity_id>/
│       └── report.pdf
├── env-params/
│   └── <activity_id>/
│       └── result.json
└── routing/
    └── <activity_id>/
        └── result.json
```

Use `--data-dir PATH` globally or `--out PATH` on a submit command to change the location, or `--no-save` to skip writing files.

Base64 images are decoded automatically. Both raw Base64 and `data:image/png;base64,...` values are handled. Embedded Base64 is stripped from metadata JSON files to keep them readable.

---

## Errors and troubleshooting

| Symptom | Meaning / fix |
|---|---|
| `FORTYGUARD_KEY is not set` | Add it to `.env` in the project root or pass `--api-key` |
| `API error 401` | Key is missing, invalid, expired, or revoked |
| `API error 403` | Your plan does not include the endpoint (Premium-only commands) |
| `API error 400` / `422` | Invalid request; no credits charged — check the message |
| `API error 429` | Rate limit exceeded; wait and retry |
| `Activity ... failed` | Processing failed; no credits charged. The activity ID is printed |
| Timeout | Run `uv run fg status <activity_id> --wait` to continue polling |
| `Ctrl+C` | The task keeps running server-side; resume with `fg status` |

Common input constraints:

- Coordinates: latitude `[-90, 90]`, longitude `[-180, 180]`, inside the United States.
- AOI polygons must be closed (first and last coordinates identical).
- Dates use `YYYY-MM-DD`; times use 24-hour `HH:MM`.
- Heatmap area limits: 10 mi² (Basic/Startup) and 50 mi² (Premium).
- Heat Intelligence `temperature` is documented as °F in the field description, while the date note mentions Celsius. Pass the value the API expects for your use case.

Use `--verbose` to see the exact request path, payload and HTTP status:

```bash
uv run fg --verbose heatmap --example --no-wait
```

---

## Project structure

```text
src/fortyguard_api_test/
├── __init__.py    package version
├── __main__.py    python -m fortyguard_api_test
├── cli.py         Click commands and validation
├── client.py      httpx client, auth, polling, usage endpoint
├── output.py      summaries, Base64 decoding, artifact saving
└── presets.py     --example payload

data/              saved results (git-ignored contents are yours to manage)
.env               FORTYGUARD_KEY=...
```

Run without installing the entry point:

```bash
uv run python -m fortyguard_api_test --help
```

---

## API documentation

- Docs: <https://docs-api.fortyguard.com>
- Plans and pricing: <https://fortyguard.com/api-pricing>
- Base URL: `https://api.fortyguard.com`
- Authentication header: `api-key: YOUR_API_KEY`

---

## License

This project is licensed under the **GNU General Public License v3.0**
(`GPL-3.0-only`). See [`LICENSE`](LICENSE) for the full text.

You may redistribute and/or modify this software under the terms of the GPL
as published by the Free Software Foundation, version 3. It comes with
**absolutely no warranty**, to the extent permitted by law.
