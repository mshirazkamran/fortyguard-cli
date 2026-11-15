"""Example payloads used by the --example flag."""

from __future__ import annotations

from typing import Any

# The rectangle used in the official Quickstart documentation (Lower Manhattan).
HEATMAP_EXAMPLE: dict[str, Any] = {
    "polygon_aoi": {
        "type": "Polygon",
        "coordinates": [
            [
                [-74.0170, 40.7050],
                [-74.0030, 40.7050],
                [-74.0030, 40.7180],
                [-74.0170, 40.7180],
                [-74.0170, 40.7050],
            ]
        ],
    },
    "date_time": {
        "start_date": "2024-07-15",
        "start_time": "14:00",
        "filter_type": 1,
    },
    "granularity": 100,
}
