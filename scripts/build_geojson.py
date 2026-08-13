from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "storage" / "data" / "geojson"
PROCESSED_DIR = ROOT / "storage" / "processed"
OUT_DIR = PROCESSED_DIR / "geojson"

COORD_PRECISION = 6

ADMIN_LEVELS = {"Nagarpalika", "Mahanagarpalika", "Gaunpalika", "Upamahanagarpalika"}
LEVEL_TYPO_MAP = {
    "maha Nagarpalika": "Mahanagarpalika",
    "gaupaika": "Gaunpalika",
}

# Longest first so e.g. "upamahanagarpalika" doesn't get cut short by a
# "nagarpalika" match. Palika-parquet names use the English suffixes; geojson
# NAME values are inconsistent -- some carry no suffix at all (e.g.
# "Bhaktapur"), others carry the Nepali-transliterated one baked in (e.g.
# "Aathbis Nagarpalika") -- so both suffix families need stripping from
# either side.
TYPE_SUFFIXES = sorted(
    [
        "sub-metropolitian city",
        "upamahanagarpalika",
        "metropolitian city",
        "mahanagarpalika",
        "nagarpalika",
        "rural municipality",
        "gaunpalika",
        "municipality",
    ],
    key=len,
    reverse=True,
)

DISTRICT_ALIAS = {
    "kapilbastu": "kapilvastu",
    "terathum": "tehrathum",
    "manag": "manang",
    "sindhupalchowk": "sindhupalchok",
}

# Districts that were split into east/west after this geojson's vintage --
# a geojson feature in the old undivided district could belong to either half.
SPLIT_DISTRICTS = {
    "nawalparasi": ["nawalparasi east", "nawalparasi west"],
    "rukum": ["rukum east", "rukum west"],
}

# geojson F_ID -> palika_id, for matches the automated passes can't resolve
# (renames, historic/alternate spellings, or a name too different for the
# 0.8 fuzzy cutoff). Filled in by hand while reviewing this script's
# unmatched-features report -- each entry below was confirmed either by
# direct name similarity or by district-scoped elimination (the feature and
# the palika were each the sole unmatched member of their district after
# every other feature/palika in that district had already resolved).
MANUAL_OVERRIDES: dict[int, int] = {
    339: 5408,  # "Pokhara Lekhnath" (pre-rename) -> Pokhara Metropolitan City
    267: 5617,  # "Tribeni Nalagad" (former name) -> Nalgad Municipality
    598: 5560,  # "Kumakh Malika" -> Kumakh Rural Municipality
    434: 5504,  # "Dalome" -> Lo Ghekar Damodarkunda Rural Municipality (elimination)
    31: 5522,  # "Woreng" -> Bareng Rural Municipality
    408: 5398,  # "Neshang" (Nesyang valley) -> Manang Ngisyang Rural Municipality
    409: 5396,  # "Narphu" (Nar-Phu valley) -> Narpa Bhumi Rural Municipality
    458: 5463,  # "Tribenisusta" (former name) -> Susta Rural Municipality
    460: 5472,  # "Binayee" -> Binayi Tribeni Rural Municipality
    232: 5391,  # "Bhimsen" -> Bhimsenthapa Rural Municipality
    234: 5394,  # "Sulikot" -> Barpak Sulikot Rural Municipality
    168: 5261,  # "Netrawati" -> Netrawati Dabjong Rural Municipality
    538: 5251,  # "Parwatikunda" -> Aamachhodingmo Rural Municipality (elimination)
    462: 5272,  # "Meghang" (spelling variant) -> Myagang Rural Municipality
    662: 5315,  # "Balefi" (spelling variant) -> Balephi Rural Municipality
    530: 5187,  # "Likhu" -> Likhu Tamakoshi Rural Municipality
    575: 5535,  # "Bhume" (spelling variant) -> Bhoome Rural Municipality
    62: 5658,  # "Chhededaha" -> Khaptad Chhededaha Rural Municipality
    66: 5660,  # "Pandav Ghupa" -> Jagannath Rural Municipality (elimination)
    67: 5664,  # "Swami Kartik" -> Swamikartik Khapar Rural Municipality
    299: 5709,  # "Karnali" -> Lamki Chuha Municipality (elimination)
    320: 5741,  # "Mahakali" -> Dodhara Chandani Municipality (elimination)
    219: 5694,  # "Bogtan" (spelling variant) -> Bogatan Phudsil Rural Municipality
    61: 5676,  # "Kanda" -> Saipal Rural Municipality (elimination)
    239: 5442,  # "Ruru" -> Ruruchhetra Rural Municipality
    737: 5007,  # "Yangwarak" -> Pathivara Yangwarak Rural Municipality
    691: 5099,  # "Barah" -> Barahachhetra Municipality
    700: 5101,  # "Bhokraha" -> Bhokraha Narsingh Rural Municipality
    178: 5068,  # "Khalsa Chhintang Shahidbhumi" -> Shahidbhumi Rural Municipality
    4: 5119,  # "Lamidanda" -> Rawa Besi Rural Municipality (elimination)
    6: 5116,  # "Diprung" -> Diprung Chuichumma Rural Municipality
    115: 5061,  # "Tyamkemaiyung" (spelling variant) -> Temkemaiyum Rural Municipality
    753: 5137,  # "Sunkoshi" -> Limchunbung Rural Municipality (elimination)
    620: 5801,  # "Krishna Sawaran" -> Agnisair Krishna Sabaran Rural Municipality
    184: 5821,  # "Kamala Siddhidatri" -> Kamala Municipality
    192: 5837,  # "Hansapur Kathapulla" -> Hansapur Municipality
    387: 5844,  # "Manra" (spelling variant) -> Manara Shisawa Municipality
    548: 5869,  # "Baudhimal" (spelling variant) -> Boudhimai Municipality
    633: 5849,  # "Gaudeta" (spelling variant) -> Godaita Municipality
}

# geojson F_IDs left genuinely ambiguous after elimination (multiple
# similarly-plausible remaining palika candidates in the same district, no
# name similarity strong enough to pick one) -- dropped rather than guessed,
# so the palika(s) they might have matched fall into the unmatched-palikas
# gap report instead of risking a wrong tier color on the map.
KNOWN_UNRESOLVABLE: set[int] = {
    597,  # "Dhorchaur" (Salyan)
    509,  # "Belwa" (Parsa)
    507,  # "Subarnapur" (Parsa)
    558,  # "Duikholi" (Rolpa)
    561,  # "Sukidaha" (Rolpa)
    566,  # "Suwarnabati" (Rolpa)
    630,  # "Belhi Chapena" (Saptari)
    684,  # "Dudhkaushika" (Solukhumbu)
    686,  # "Dudhkoshi" (Solukhumbu)
}


def normalize(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def strip_type_suffix(name_en: str) -> str:
    n = name_en.lower().strip()
    for suffix in TYPE_SUFFIXES:
        if n.endswith(suffix):
            return n[: -len(suffix)].strip()
    return n


def normalize_district(d: str) -> str:
    d = d.lower().strip()
    return DISTRICT_ALIAS.get(d, d)


def load_admin_features() -> list[dict]:
    raw = json.loads((DATA_DIR / "nepal-municipalities.geojson").read_text())
    feats = []
    for f in raw["features"]:
        level = f["properties"].get("LEVEL")
        level = LEVEL_TYPO_MAP.get(level, level)
        if level in ADMIN_LEVELS:
            feats.append(f)
    return feats


def build_pool(palikas: pl.DataFrame) -> dict[str, list[tuple[str, int]]]:
    """district_name_en (parquet, lowercase) -> [(normalized base_name, palika_id), ...]"""
    pool: dict[str, list[tuple[str, int]]] = {}
    for row in palikas.iter_rows(named=True):
        key = normalize(strip_type_suffix(row["palika_name_en"]))
        pool.setdefault(row["district_name_en"], []).append((key, row["palika_id"]))
    return pool


def candidate_districts(geo_district: str, parquet_districts: set[str]) -> list[str]:
    norm = normalize_district(geo_district)
    if norm in SPLIT_DISTRICTS:
        return [d for d in SPLIT_DISTRICTS[norm] if d in parquet_districts]
    return [norm] if norm in parquet_districts else []


def match_municipalities(
    admin_feats: list[dict], palikas: pl.DataFrame
) -> tuple[dict[int, int], list[dict]]:
    """Returns (F_ID -> palika_id, list of unmatched feature property dicts)."""
    pool = build_pool(palikas)
    parquet_districts = set(pool.keys())

    matched: dict[int, int] = {}
    unmatched: list[dict] = []

    for feat in admin_feats:
        props = feat["properties"]
        f_id = props["F_ID"]

        if f_id in MANUAL_OVERRIDES:
            matched[f_id] = MANUAL_OVERRIDES[f_id]
            continue
        if f_id in KNOWN_UNRESOLVABLE:
            continue

        districts = candidate_districts(props.get("DISTRICT", ""), parquet_districts)
        candidates: list[tuple[str, int]] = []
        for d in districts:
            candidates.extend(pool.get(d, []))

        target = normalize(strip_type_suffix(props.get("NAME", "")))

        # Pass 1: exact normalized match within candidate district(s).
        exact = [pid for key, pid in candidates if key == target]
        if len(exact) == 1:
            matched[f_id] = exact[0]
            continue

        # Pass 2: fuzzy match within the same candidate pool.
        keys = [key for key, _ in candidates]
        close = difflib.get_close_matches(target, keys, n=1, cutoff=0.8)
        if close:
            for key, pid in candidates:
                if key == close[0]:
                    matched[f_id] = pid
                    break
            continue

        unmatched.append(props)

    return matched, unmatched


def round_coords(geom: dict, precision: int = COORD_PRECISION) -> dict:
    def walk(coords):
        if not coords:
            return coords
        if isinstance(coords[0], (int, float)):
            return [round(c, precision) for c in coords]
        return [walk(c) for c in coords]

    return {**geom, "coordinates": walk(geom["coordinates"])}


def build_provinces() -> dict:
    raw = json.loads((DATA_DIR / "nepal-states.geojson").read_text())
    out_features = []
    for feat in raw["features"]:
        province_id = int(feat["properties"]["ADM1_PCODE"][-2:])
        out_features.append(
            {
                "type": "Feature",
                "geometry": round_coords(feat["geometry"]),
                "properties": {"province_id": province_id},
            }
        )
    return {"type": "FeatureCollection", "features": out_features}


def build_municipalities(palikas: pl.DataFrame) -> tuple[dict, list[dict], set[int]]:
    admin_feats = load_admin_features()
    matched, unmatched = match_municipalities(admin_feats, palikas)

    unresolved = [p for p in unmatched if p["F_ID"] not in KNOWN_UNRESOLVABLE]
    if unresolved:
        names = ", ".join(f"{p['NAME']!r} ({p['DISTRICT']}, F_ID={p['F_ID']})" for p in unresolved)
        raise AssertionError(
            f"{len(unresolved)} municipality feature(s) unresolved after overrides: {names}\n"
            "Add a MANUAL_OVERRIDES entry (F_ID -> palika_id) or a KNOWN_UNRESOLVABLE "
            "entry for each."
        )

    palika_to_province = dict(zip(palikas["palika_id"], palikas["province_id"]))

    out_features = []
    matched_palika_ids: set[int] = set()
    for feat in admin_feats:
        f_id = feat["properties"]["F_ID"]
        palika_id = matched.get(f_id)
        if palika_id is None:
            continue
        matched_palika_ids.add(palika_id)
        out_features.append(
            {
                "type": "Feature",
                "geometry": round_coords(feat["geometry"]),
                "properties": {
                    "palika_id": palika_id,
                    "province_id": palika_to_province[palika_id],
                },
            }
        )

    gap_palikas = sorted(set(palikas["palika_id"]) - matched_palika_ids)
    name_by_id = dict(zip(palikas["palika_id"], palikas["palika_name_en"]))
    gap_report = {name_by_id[pid]: None for pid in gap_palikas}

    return {"type": "FeatureCollection", "features": out_features}, gap_report, matched_palika_ids


def main() -> None:
    palikas = pl.read_parquet(PROCESSED_DIR / "palikas.parquet").join(
        pl.read_parquet(PROCESSED_DIR / "districts.parquet"), on="district_id", how="left"
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    provinces_geojson = build_provinces()
    provinces_path = OUT_DIR / "nepal-states.geojson"
    provinces_path.write_text(json.dumps(provinces_geojson))
    print(f"wrote {provinces_path} ({len(provinces_geojson['features'])} features)")

    municipalities_geojson, gap_report, matched_ids = build_municipalities(palikas)
    municipalities_path = OUT_DIR / "nepal-municipalities.geojson"
    municipalities_path.write_text(json.dumps(municipalities_geojson))
    print(
        f"wrote {municipalities_path} ({len(municipalities_geojson['features'])} features, "
        f"{len(matched_ids)}/{palikas.height} palikas matched)"
    )

    gap_path = OUT_DIR / "unmatched_palikas.json"
    gap_path.write_text(json.dumps(gap_report, indent=2, ensure_ascii=False, sort_keys=True))
    print(f"wrote {gap_path} ({len(gap_report)} palikas with no matched geometry)")


if __name__ == "__main__":
    main()
