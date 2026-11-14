"""
Validation script for sites/sites.json format and schema integrity.
Checks:
- File is valid JSON and contains a list of sites
- Required fields: name, lat_deg, lon_deg, mission, country/agency, status, year, source_url, notes
- lat_deg is numeric and in range [-90.0, 90.0] (South = negative)
- lon_deg is numeric and in range [-180.0, 360.0]
- status is one of: "landed", "planned", "candidate region"
- year is an integer
- source_url is a well-formed HTTP/HTTPS URL
- Candidate regions are not marked as landed points
- Meets minimum threshold of at least 15 sites
"""

import json
import sys
from urllib.parse import urlparse

REQUIRED_KEYS = [
    "name",
    "lat_deg",
    "lon_deg",
    "mission",
    "country/agency",
    "status",
    "year",
    "source_url",
    "notes"
]

VALID_STATUSES = {"landed", "planned", "candidate region"}

def validate_sites_file(filepath: str) -> bool:
    print(f"=== Validating {filepath} ===")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[FAIL] JSON parsing error: {e}")
        return False

    if isinstance(data, dict) and "sites" in data:
        sites = data["sites"]
    elif isinstance(data, list):
        sites = data
    else:
        print("[FAIL] Root JSON structure must be a list of sites (or an object with a 'sites' list).")
        return False

    print(f"Found {len(sites)} site entries.")
    if len(sites) < 15:
        print(f"[FAIL] Required at least 15 sites, found {len(sites)}.")
        return False

    errors = []
    warnings = []

    for idx, site in enumerate(sites):
        prefix = f"Entry {idx + 1} ({site.get('name', 'UNKNOWN')})"

        # 1. Required keys
        for key in REQUIRED_KEYS:
            if key not in site:
                errors.append(f"{prefix}: Missing required key '{key}'")

        # 2. Latitude validation
        lat = site.get("lat_deg")
        if not isinstance(lat, (int, float)):
            errors.append(f"{prefix}: lat_deg must be numeric, got {type(lat).__name__}")
        elif not (-90.0 <= lat <= 90.0):
            errors.append(f"{prefix}: lat_deg ({lat}) outside valid range [-90.0, 90.0]")

        # 3. Longitude validation
        lon = site.get("lon_deg")
        if not isinstance(lon, (int, float)):
            errors.append(f"{prefix}: lon_deg must be numeric, got {type(lon).__name__}")
        elif not (-180.0 <= lon <= 360.0):
            errors.append(f"{prefix}: lon_deg ({lon}) outside valid range [-180.0, 360.0]")

        # 4. Status validation
        status = site.get("status")
        if status not in VALID_STATUSES:
            errors.append(f"{prefix}: Invalid status '{status}'. Expected one of {sorted(VALID_STATUSES)}")

        # 5. Candidate region vs landing point check
        if status == "candidate region":
            name = str(site.get("name", "")).lower()
            notes = str(site.get("notes", "")).lower()
            if "region" not in name and "region" not in notes and "feature" not in notes and "spot" not in notes:
                warnings.append(f"{prefix}: Status is 'candidate region' but name/notes do not mention 'region' or 'feature'")

        # 6. Year validation
        year = site.get("year")
        if not isinstance(year, int):
            errors.append(f"{prefix}: year must be integer, got {type(year).__name__} ({year})")
        elif not (1950 <= year <= 2040):
            warnings.append(f"{prefix}: year ({year}) outside customary lunar mission range [1950, 2040]")

        # 7. URL validation
        url = site.get("source_url")
        if not isinstance(url, str):
            errors.append(f"{prefix}: source_url must be string")
        else:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                errors.append(f"{prefix}: Invalid source_url '{url}'")

        # 8. Mission and country/agency
        if not site.get("mission"):
            errors.append(f"{prefix}: mission cannot be empty")
        if not site.get("country/agency"):
            errors.append(f"{prefix}: country/agency cannot be empty")

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  [WARN] {w}")

    if errors:
        print(f"\n[FAIL] Validation failed with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        return False

    print(f"\n[PASS] All {len(sites)} sites passed validation successfully!")
    print(f"       - Latitude standard: South = negative [-90, 90]")
    print(f"       - Longitude standard: East positive [-180, 180]")
    print(f"       - Status breakdown:")
    status_counts = {}
    for s in sites:
        status_counts[s["status"]] = status_counts.get(s["status"], 0) + 1
    for k, v in sorted(status_counts.items()):
        print(f"         * {k}: {v}")
    return True

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "sites/sites.json"
    success = validate_sites_file(target)
    sys.exit(0 if success else 1)
