#!/usr/bin/env python3
"""Build the Kauaʻi Connect traffic page.

Pulls planned state-highway lane closures for Kauaʻi from HDOT's public ArcGIS
feature service and writes one self-contained HTML file (dist/index.html).
Standard library only, so the GitHub Action needs no pip install.

  python build.py                      # live data
  python build.py --fixture fixtures/kauai_sample.json   # offline test
"""
import argparse
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weekly import fetch_weekly, parse_weekly

HERE = Path(__file__).parent
SERVICE = (
    "https://services.arcgis.com/HQ0xoN0EzDPBOEci/arcgis/rest/services/"
    "Lane_Closure_WFL1_View_NoEd/FeatureServer/0/query"
)
FIELDS = (
    "OBJECTID,RoadName,Route,RteDirn,ClosType,CloseFact,ClosureSide,ClosReason,"
    "ClosHours,Remarks,beginDate,enDate,BMP,EMP,NumLanes,Island"
)
HST = ZoneInfo("Pacific/Honolulu")

# ---- Editable lookup tables -------------------------------------------------
# Route number -> road name. Unknown routes fall back to "Route N".
ROUTES = {
    "50": "Kaumualiʻi Hwy",
    "51": "Kapule Hwy",
    "56": "Kūhiō Hwy",
    "560": "Kūhiō Hwy",
    "550": "Waimea Canyon Dr / Kōkeʻe Rd",
    "570": "Ahukini Rd",
    "580": "Kūamoʻo Rd",
    "581": "Olohena Rd",
}

# Town reference points (lat, lon, region). A closure is labelled with the
# nearest one. Region keys: north / east / south / west. Adjust to match the
# region slugs on kauaiconnect.com.
TOWNS = {
    "Hāʻena": (22.2204, -159.5800, "north"),
    "Wainiha": (22.2250, -159.5550, "north"),
    "Hanalei": (22.2036, -159.5039, "north"),
    "Princeville": (22.2227, -159.4800, "north"),
    "Kīlauea": (22.2111, -159.4056, "north"),
    "Anahola": (22.1417, -159.3078, "east"),
    "Moloaʻa": (22.1250, -159.3330, "east"),
    "Kapaʻa": (22.0753, -159.3190, "east"),
    "Wailua": (22.0467, -159.3370, "east"),
    "Hanamāʻulu": (21.9906, -159.3480, "lihue"),
    "Līhuʻe": (21.9811, -159.3711, "lihue"),
    "Kōloa": (21.9064, -159.4694, "south"),
    "Poʻipū": (21.8767, -159.4586, "south"),
    "Lāwaʻi": (21.9275, -159.5011, "south"),
    "Kalāheo": (21.9264, -159.5258, "south"),
    "ʻEleʻele": (21.9028, -159.5844, "west"),
    "Hanapēpē": (21.9100, -159.5900, "west"),
    "Waimea": (21.9553, -159.6711, "west"),
    "Kekaha": (21.9669, -159.7122, "west"),
    "Waimea Canyon": (22.0589, -159.6619, "west"),
    "Kōkeʻe": (22.1272, -159.6606, "west"),
}

# Planned work only: show closures starting within this many days.
HORIZON_DAYS = 7
# -----------------------------------------------------------------------------


def fetch_features(now_utc):
    cutoff = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    where = (
        "Island='Kauai' AND Active='1' AND DIRPInfo='Yes' "
        f"AND enDate >= timestamp '{cutoff}'"
    )
    feats, offset = [], 0
    while True:
        params = {
            "where": where,
            "outFields": FIELDS,
            "outSR": "4326",
            "geometryPrecision": "5",
            "maxAllowableOffset": "0.0001",
            "orderByFields": "beginDate",
            "resultOffset": str(offset),
            "resultRecordCount": "500",
            "f": "json",
        }
        url = SERVICE + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "kauaiconnect-traffic/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        if "error" in data:
            raise RuntimeError(f"ArcGIS error: {data['error']}")
        batch = data.get("features", [])
        feats.extend(batch)
        if not data.get("exceededTransferLimit") or not batch:
            return feats
        offset += len(batch)


def nearest_town(lat, lon):
    best, best_d = None, 1e9
    for name, (tlat, tlon, region) in TOWNS.items():
        dy = (lat - tlat) * 111.0
        dx = (lon - tlon) * 111.0 * math.cos(math.radians(lat))
        d = math.hypot(dx, dy)
        if d < best_d:
            best, best_d = (name, region), d
    return best


def to_record(f):
    a = f["attributes"]
    if not a.get("beginDate") or not a.get("enDate") or a["beginDate"] == a["enDate"]:
        return None
    paths = (f.get("geometry") or {}).get("paths") or []
    line = []
    for p in paths:
        pts = [[round(y, 5), round(x, 5)] for x, y in p]
        if len(pts) > 60:
            step = math.ceil(len(pts) / 60)
            pts = pts[::step] + [pts[-1]]
        line.append(pts)
    town, region = (None, None)
    if line:
        mid = line[0][len(line[0]) // 2]
        town, region = nearest_town(mid[0], mid[1])
    route = str(a.get("Route") or "").strip()
    road = (a.get("RoadName") or "").strip() or ROUTES.get(route) or (f"Route {route}" if route else "State highway")
    remarks = " ".join((a.get("Remarks") or "").split())
    return {
        "id": a["OBJECTID"],
        "route": route,
        "road": road,
        "type": a.get("ClosType") or "",
        "fact": a.get("CloseFact") or "",
        "side": a.get("ClosureSide") or "",
        "reason": a.get("ClosReason") or "",
        "hours": a.get("ClosHours") or "",
        "remarks": remarks,
        "start": a["beginDate"],
        "end": a["enDate"],
        "bmp": round(a["BMP"], 2) if a.get("BMP") is not None else None,
        "emp": round(a["EMP"], 2) if a.get("EMP") is not None else None,
        "town": town,
        "region": region,
        "line": line,
    }


def sev_of_text(t):
    t = t.lower()
    if re.search(r"\bfull (road )?closure\b", t):
        return 3
    if "lane closure" in t:
        return 2
    return 1


def match_records(text, records):
    """Match an HDOT text item to feed records by route + milepost overlap."""
    rm = re.search(r"\(Routes?\s+(\d+)", text, re.I) or re.search(r"Route\s+(\d+)", text, re.I)
    mm = re.search(r"mile\s*post\s+([\d.]+)\s*(?:to|-|–|and)\s*([\d.]+)", text, re.I)
    if not rm or not mm:
        return []
    a, b = sorted((float(mm.group(1)), float(mm.group(2))))

    def near(r):
        if r["bmp"] is None or r["emp"] is None:
            return False
        lo, hi = sorted((r["bmp"], r["emp"]))
        return min(b, hi) - max(a, lo) >= 0.5 * min((b - a) or 0.1, (hi - lo) or 0.1)

    def pick(routes):
        return [r for r in records if r["route"] in routes and r["line"] and near(r)]

    hit = pick([rm.group(1)])
    sister = {"56": "560", "560": "56"}.get(rm.group(1))
    if not hit and sister:
        hit = pick([sister])
    return hit


def build_summary(records, weekly, now_ms):
    """Small file for the kauaiconnect.com homepage tile: closures grouped like the traffic page."""
    for r in records:
        r["_sev"] = 3 if (r["side"] == "Full" or r["fact"] == "Full") else (2 if r["fact"] == "Lane" else 1)
    if weekly:
        over = {}
        for g in weekly["groups"]:
            for i in g["items"]:
                text = "".join(s["t"] for s in i["segs"])
                for r in match_records(text, records):
                    over[r["id"]] = max(over.get(r["id"], 0), sev_of_text(text))
        for r in records:
            if r["id"] in over:
                r["_sev"] = over[r["id"]]
    groups = {}
    horizon = now_ms + 8 * 86400000
    for r in records:
        if r["end"] < now_ms - 3600000 or r["start"] > horizon:
            continue
        key = (r["route"], r["bmp"], r["emp"], r["fact"], r["side"], r["type"], r["reason"], r["hours"])
        g = groups.setdefault(key, {"road": r["road"], "town": r["town"], "route": r["route"], "sev": r["_sev"], "occ": []})
        g["sev"] = max(g["sev"], r["_sev"])
        g["occ"].append([r["start"], r["end"]])
    out = []
    for g in groups.values():
        g["occ"].sort()
        out.append(g)
    return {"generated": now_ms, "groups": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", help="JSON file with an ArcGIS 'features' list (skips the network)")
    ap.add_argument("--weekly-fixture", help="saved HDOT Kauaʻi page HTML (offline test)")
    ap.add_argument("--out", default=str(HERE / "dist" / "index.html"))
    args = ap.parse_args()

    now_utc = datetime.now(timezone.utc)
    if args.fixture:
        feats = json.loads(Path(args.fixture).read_text())["features"]
    else:
        feats = fetch_features(now_utc)

    records = [r for r in (to_record(f) for f in feats) if r]
    if not feats and not args.fixture:
        print("warning: feed returned 0 features", file=sys.stderr)

    if args.weekly_fixture:
        weekly = parse_weekly(Path(args.weekly_fixture).read_text(encoding="utf-8"))
    elif args.fixture:
        weekly = None
    else:
        weekly = fetch_weekly()

    payload = {
        "generated": int(now_utc.timestamp() * 1000),
        "weekly": weekly,
        "horizonDays": HORIZON_DAYS,
        "records": records,
        "regions": {"north": "North", "east": "East", "lihue": "Līhuʻe", "south": "South", "west": "West"},
    }
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (HERE / "template.html").read_text().replace("/*__DATA__*/null", data_js)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    summary = build_summary(records, weekly, int(now_utc.timestamp() * 1000))
    (out.parent / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({len(records)} closure records, {len(html)//1024} KB) at {now_utc.astimezone(HST):%Y-%m-%d %H:%M} HST")


if __name__ == "__main__":
    main()
