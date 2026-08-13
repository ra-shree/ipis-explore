from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import streamlit as st

from lib.tiers import NO_DATA_TIER, TIER_COLORS

ROOT = Path(__file__).resolve().parent.parent
GEOJSON_DIR = ROOT / "storage" / "processed" / "geojson"

SELECTED_BORDER_COLOR = "#0b0b0b"
DEFAULT_BORDER_COLOR = "#fcfcfb"
MUNICIPALITY_FILL_OPACITY = 0.85
MUTED_FILL_OPACITY = 0.35
PROVINCE_FILL_OPACITY = 0.35


@st.cache_data
def load_province_geojson() -> dict:
    return json.loads((GEOJSON_DIR / "nepal-states.geojson").read_text())


@st.cache_data
def load_municipality_geojson() -> dict:
    return json.loads((GEOJSON_DIR / "nepal-municipalities.geojson").read_text())


def _format_margin(margin: float, tier: str) -> str:
    if tier == NO_DATA_TIER:
        return "No data"
    sign = "+" if margin >= 0 else ""
    return f"{sign}{margin * 100:.1f}%"


def enrich_municipalities(
    geojson: dict,
    head_race: pl.DataFrame,
    muted_pids: set[int],
    selected_pid: int | None,
    include_pids: set[int] | None = None,
) -> dict:
    """New FeatureCollection: one feature per palika_id present in both
    `geojson` and `head_race` (intersected with `include_pids` if given).
    Each feature's properties carry the rendering/tooltip fields main.py
    needs (_fill, _fill_opacity, border, tier, margin_display) so the
    style_function/tooltip do no per-feature lookups. Never mutates
    `geojson` -- builds new feature dicts, reusing `geometry` by reference
    since it's never modified.
    """
    info = {
        row["palika_id"]: row
        for row in head_race.select(
            "palika_id", "palika_name_en", "province_name_en", "tier", "margin"
        ).iter_rows(named=True)
    }

    out_features = []
    for feat in geojson["features"]:
        pid = feat["properties"]["palika_id"]
        if include_pids is not None and pid not in include_pids:
            continue
        row = info.get(pid)
        if row is None:
            continue

        muted = pid in muted_pids
        selected = pid == selected_pid
        tier = row["tier"]

        out_features.append(
            {
                "type": "Feature",
                "geometry": feat["geometry"],
                "properties": {
                    "palika_id": pid,
                    "palika_name_en": row["palika_name_en"],
                    "province_name_en": row["province_name_en"],
                    "tier": tier,
                    "margin_display": _format_margin(row["margin"], tier),
                    "_fill": TIER_COLORS[NO_DATA_TIER] if muted else TIER_COLORS[tier],
                    "_fill_opacity": MUTED_FILL_OPACITY if muted else MUNICIPALITY_FILL_OPACITY,
                    "_border_color": SELECTED_BORDER_COLOR if selected else DEFAULT_BORDER_COLOR,
                    "_border_weight": 3 if selected else 1,
                },
            }
        )
    return {"type": "FeatureCollection", "features": out_features}


def bounds_of_features(geojson: dict) -> tuple[float, float, float, float] | None:
    """(min_lat, min_lon, max_lat, max_lon) across every feature's geometry,
    or None if `geojson` has no features."""
    lats: list[float] = []
    lons: list[float] = []

    def walk(coords):
        if not coords:
            return
        if isinstance(coords[0], (int, float)):
            lon, lat = coords[0], coords[1]
            lons.append(lon)
            lats.append(lat)
        else:
            for c in coords:
                walk(c)

    for feat in geojson["features"]:
        walk(feat["geometry"]["coordinates"])

    if not lats:
        return None
    return min(lats), min(lons), max(lats), max(lons)


def enrich_provinces(geojson: dict, province_tier: pl.DataFrame) -> dict:
    """Always built from the full unfiltered province_tier -- this is a
    geographic backdrop layer, not affected by sidebar filters or demo mode.
    """
    tier_by_province = dict(zip(province_tier["province_id"], province_tier["tier"]))

    out_features = []
    for feat in geojson["features"]:
        province_id = feat["properties"]["province_id"]
        tier = tier_by_province.get(province_id, NO_DATA_TIER)
        out_features.append(
            {
                "type": "Feature",
                "geometry": feat["geometry"],
                "properties": {
                    "_fill": TIER_COLORS[tier],
                    "_fill_opacity": PROVINCE_FILL_OPACITY,
                },
            }
        )
    return {"type": "FeatureCollection", "features": out_features}
