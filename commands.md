# Sample commands

Copy-paste examples for every endpoint in the CLI, using three US locations:
**Miami, Florida**, **Denver, Colorado** and **San Jose, California**.

All examples assume you run them from the project root and use `uv run fg`:

```bash
uv run fg --help
```

If you activated the virtual environment (`source .venv/bin/activate`), replace
`uv run fg` with `fg`.

> **Option placement:** global options such as `--json`, `--no-save`,
> `--data-dir`, `--poll-interval` and `--max-wait` go **before** the command.
> Command options such as `--no-wait`, `--out` and `--json-file` go **after**
> the command.

> **Before you run paid commands:** `heatmap`, `satellite`, `streetview`,
> `heat-intelligence`, `env-params` and `routing` consume credits when the task
> completes. Check the balance first with `uv run fg credits`.
>
> The API currently covers the **United States only**. The dates below are
> examples; data availability depends on the API catalogue.

## Location reference

| City | Latitude | Longitude | Heatmap bbox (west,south,east,north) |
|---|---:|---:|---|
| Miami, FL | `25.7617` | `-80.1918` | `-80.2100,25.7500,-80.1700,25.7900` |
| Denver, CO | `39.7392` | `-104.9903` | `-105.0100,39.7300,-104.9700,39.7500` |
| San Jose, CA | `37.3382` | `-121.8863` | `-121.9060,37.3280,-121.8660,37.3480` |

These boxes are small enough for the Basic/Startup heatmap limit (10 mi²).

## Free checks

```bash
# Validate .env, key, data directory and authentication
uv run fg doctor

# Local checks only, without calling the API
uv run fg doctor --no-request

# Current billing cycle: plan, remaining credits, usage breakdown
uv run fg credits

# Custom date range
uv run fg credits --start-date 2024-07-01 --end-date 2024-07-31

# Raw JSON
uv run fg --json credits
```

---

## Heatmap

Endpoint: `POST /v1/heatmap`
Cost: 3,500 credits (Basic/Startup), 4,220 (Premium)
Saved: `data/heatmap/<activity_id>/map_data.geojson` and `stats_data.json`

### Miami, Florida

```bash
# Single hour, 100 m tiles
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --start-time 14:00

# Same-day range of hours, 60 m tiles
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --start-time 06:00 --end-time 18:00 \
  --granularity 60

# Single day
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --filter-type 3

# Range of days (up to 31 days)
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-01 --end-date 2024-07-07

# Hours above 35 °C (exceedance)
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --filter-type 3 \
  --analytic-type exceedance --threshold 35 --direction above

# Longest continuous run above 35 °C (persistence)
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-01 --end-date 2024-07-07 \
  --analytic-type persistence --threshold 35 --direction above

# Hour-of-day map
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --start-time 14:00 \
  --analytic-type time_of_measure

# Large-map delivery: signed download links instead of inline data
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --start-time 14:00 --links
```

### Denver, Colorado

```bash
# Single hour
uv run fg heatmap --bbox -105.0100,39.7300,-104.9700,39.7500 \
  --date 2024-07-15 --start-time 14:00

# Single day, 80 m tiles
uv run fg heatmap --bbox -105.0100,39.7300,-104.9700,39.7500 \
  --date 2024-07-15 --filter-type 3 --granularity 80

# Exceedance above 32 °C
uv run fg heatmap --bbox -105.0100,39.7300,-104.9700,39.7500 \
  --date 2024-07-01 --end-date 2024-07-07 \
  --analytic-type exceedance --threshold 32
```

### San Jose, California

```bash
# Single hour
uv run fg heatmap --bbox -121.9060,37.3280,-121.8660,37.3480 \
  --date 2024-07-15 --start-time 14:00

# Same-day range, 20 m tiles
uv run fg heatmap --bbox -121.9060,37.3280,-121.8660,37.3480 \
  --date 2024-07-15 --start-time 10:00 --end-time 16:00 \
  --granularity 20

# Hours below 20 °C
uv run fg heatmap --bbox -121.9060,37.3280,-121.8660,37.3480 \
  --date 2024-07-15 --filter-type 3 \
  --analytic-type exceedance --threshold 20 --direction below
```

### Using a GeoJSON AOI file

```bash
cat > miami-area.geojson <<'EOF'
{
  "type": "Polygon",
  "coordinates": [[
    [-80.2100, 25.7500],
    [-80.1700, 25.7500],
    [-80.1700, 25.7900],
    [-80.2100, 25.7900],
    [-80.2100, 25.7500]
  ]]
}
EOF

uv run fg heatmap --aoi miami-area.geojson \
  --date 2024-07-15 --start-time 14:00
```

### Other heatmap variants

```bash
# The documentation's New York example, with a preset AOI and date
uv run fg heatmap --example

# Submit and return only the activity_id
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --start-time 14:00 --no-wait

# Do not save artifacts
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --filter-type 3 --no-save
```

---

## Satellite view segmentation

Endpoint: `POST /v1/satellite`
Cost: 14,400 credits (Premium only)
Saved: `original_0.png`, `segmentation.png`, `segmentation.json`

```bash
# Miami
uv run fg satellite --lat 25.7617 --lon -80.1918 \
  --date 2024-07-15 --start-time 14:00

# Denver, single day
uv run fg satellite --lat 39.7392 --lon -104.9903 \
  --date 2024-07-15 --filter-type 3

# San Jose, 20 m mode (80×80 pixel crop)
uv run fg satellite --lat 37.3382 --lon -121.8863 \
  --date 2024-07-15 --start-time 14:00 --granularity 20
```

---

## Street view segmentation

Endpoint: `POST /v1/streetview`
Cost: 8,600 credits (Premium only)
Saved: `front_original.png`, `front_segmented.png`, `front_metadata.json`, plus `back_*` when `--back-view` is used.

```bash
# Miami, front view only
uv run fg streetview --lat 25.7617 --lon -80.1918 \
  --vertical-angle 10 --horizontal-angle 90

# Denver, both directions
uv run fg streetview --lat 39.7392 --lon -104.9903 \
  --vertical-angle 10 --horizontal-angle 90 --back-view

# San Jose, angled view
uv run fg streetview --lat 37.3382 --lon -121.8863 \
  --vertical-angle 5 --horizontal-angle 180
```

---

## Heat Intelligence report

Endpoint: `POST /v1/heat_intelligence`
Cost: 8,600 credits (Premium only)
Saved: `data/heat-intelligence/<activity_id>/report.pdf`

```bash
# Miami: all five analysis categories (default)
uv run fg heat-intelligence --lat 25.7617 --lon -80.1918 \
  --temperature 95 --date 2024-07-15

# Denver: selected categories
uv run fg heat-intelligence --lat 39.7392 --lon -104.9903 \
  --temperature 90 --date 2024-07-15 \
  --analysis geographic --analysis environmental

# San Jose: urban and anthropogenic analysis
uv run fg heat-intelligence --lat 37.3382 --lon -121.8863 \
  --temperature 82 --date 2024-07-15 \
  --analysis urban --analysis anthropogenic
```

`--temperature` is documented as °F in the field description. Use the value
the API expects for your report.

---

## Environmental parameters

Endpoint: `POST /v1/env_params`
Cost: 2,110 credits (Basic/Startup), 2,900 (Premium)
Saved: `data/env-params/<activity_id>/result.json`

```bash
# Miami: specific parameters (fits the Basic 3-parameter limit)
uv run fg env-params --lat 25.7617 --lon -80.1918 --temperature 32.5 \
  --date 2024-07-15 --start-time 14:00 \
  --analysis heat_index_celsius,wet_bulb_temperature_celsius,relative_humidity_percent

# Denver: AQI and solar parameters
uv run fg env-params --lat 39.7392 --lon -104.9903 --temperature 30.0 \
  --date 2024-07-15 --filter-type 3 \
  --analysis air_quality:idx,air_quality_pm2p5:idx,solar_irradiance

# San Jose: all available parameters (Premium)
uv run fg env-params --lat 37.3382 --lon -121.8863 --temperature 28.0 \
  --date 2024-07-15 --start-time 06:00 --end-time 18:00
```

Parameter names can be repeated or comma-separated:

```bash
--analysis heat_index_celsius --analysis apparent_temperature_celsius
```

Useful names: `heat_index_celsius`, `apparent_temperature_celsius`,
`wet_bulb_temperature_celsius`, `relative_humidity_percent`,
`precipitation_mm`, `cloud_cover_octas`, `elevation`, `air_quality:idx`,
`air_quality_pm2p5:idx`, `air_quality_pm10:idx`, `air_quality_no2:idx`,
`aqi_us_co`, `air_quality_o3:idx`, `air_quality_so2:idx`, `methane_ppb`,
`co2_ppm`, `solar_irradiance`.

---

## Temperature-aware routing

Endpoint: `POST /v1/routing`
Cost: 3,500 credits (Premium only)
Origin and destination must be within 200 km straight-line.
Saved: `data/routing/<activity_id>/result.json`

```bash
# Miami: downtown to Miami Beach
uv run fg routing \
  --origin-lat 25.7617 --origin-lon -80.1918 \
  --dest-lat 25.7907 --dest-lon -80.1300 \
  --departure-time 2026-07-15T08:00:00-04:00

# Denver: downtown to Denver International Airport
uv run fg routing \
  --origin-lat 39.7392 --origin-lon -104.9903 \
  --dest-lat 39.8561 --dest-lon -104.6737 \
  --departure-time 2026-07-15T08:00:00-06:00

# San Jose: downtown to Santa Clara
uv run fg routing \
  --origin-lat 37.3382 --origin-lon -121.8863 \
  --dest-lat 37.3541 --dest-lon -121.9552 \
  --departure-time 2026-07-15T08:00:00-07:00
```

---

## Status and resuming tasks

Endpoint: `GET /v1/status/{activity_id}` (free)

```bash
# One status check
uv run fg status ACTIVITY_ID

# Poll until Completed or Failed
uv run fg status ACTIVITY_ID --wait

# Request signed links for a large heatmap result
uv run fg status ACTIVITY_ID --wait --links

# Machine-readable result
uv run fg --json status ACTIVITY_ID --wait > result.json
```

If a submit command was run with `--no-wait`, timed out, or was interrupted
with Ctrl+C, use `fg status` with the printed activity ID. The CLI detects the
result type and saves it the same way the original command would.

---

## Raw requests

Escape hatch for endpoints or payloads not covered by the dedicated commands.
Responses are printed as JSON and no artifacts are saved.

```bash
# Any status response
uv run fg raw GET /v1/status/ACTIVITY_ID

# Request signed result links
uv run fg raw GET /v1/status/ACTIVITY_ID --query result_delivery=links

# Submit a hand-written heatmap payload
cat > heatmap-payload.json <<'EOF'
{
  "polygon_aoi": {
    "type": "Polygon",
    "coordinates": [[
      [-80.2100, 25.7500],
      [-80.1700, 25.7500],
      [-80.1700, 25.7900],
      [-80.2100, 25.7900],
      [-80.2100, 25.7500]
    ]]
  },
  "date_time": {
    "start_date": "2024-07-15",
    "start_time": "14:00",
    "filter_type": 1
  },
  "granularity": 100
}
EOF

uv run fg raw POST /v1/heatmap --json-file heatmap-payload.json

# See how an unknown activity is reported
uv run fg raw GET /v1/status/does-not-exist
```

The `api-key` header is added automatically by the CLI. For the credit-usage
endpoints, use `fg credits` instead of `raw`: it also puts the key in the
request body, which those endpoints expect.

---

## Global options and output control

Global options go **before** the command name:

```bash
# Raw JSON on stdout, progress on stderr
uv run fg --json heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --filter-type 3

# Keep all artifacts for this run in a separate directory
uv run fg --data-dir ./runs/2024-07-15 heatmap \
  --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --filter-type 3

# Faster polling and a 30-minute ceiling
uv run fg --poll-interval 2 --max-wait 1800 satellite \
  --lat 25.7617 --lon -80.1918 --date 2024-07-15 --start-time 14:00

# Show the exact HTTP requests and responses
uv run fg --verbose heatmap --example --no-wait

# Do not write files
uv run fg --no-save status ACTIVITY_ID
```

Per-command artifact directory:

```bash
uv run fg heatmap --bbox -80.2100,25.7500,-80.1700,25.7900 \
  --date 2024-07-15 --filter-type 3 --out ./runs/miami
```

## Cost summary

| Command | Credits |
|---|---:|
| `doctor`, `credits`, `status` | 0 |
| `heatmap` | 3,500 Basic/Startup · 4,220 Premium |
| `env-params` | 2,110 Basic/Startup · 2,900 Premium |
| `satellite` | 14,400 Premium |
| `streetview` | 8,600 Premium |
| `heat-intelligence` | 8,600 Premium |
| `routing` | 3,500 Premium |

Credits are charged only when a task completes successfully.
