#!/usr/bin/env python3
"""Static site builder: fetch Google Sheet → transform → inline → write dist/index.html.

Usage:
    python3 build.py --sheet-url <url> --credential <path> --output <path>
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

# ============================================================
#  GRID PARSING CONFIG
# ============================================================
TIME_MAP = {
    "8-9 am": "08:00", "9-10 am": "09:00", "10-11 am": "10:00",
    "11-12 am": "11:00", "12-1 pm": "12:00", "1-2 pm": "13:00",
    "2-3 pm": "14:00", "3-4 pm": "15:00", "4-5 pm": "16:00",
    "5-6 pm": "17:00", "6-7 pm": "18:00", "7-8 pm": "19:00",
    "8-9 pm": "20:00",
}

# id, date, title, theme, color, source col, row range
DAYS_LAYOUT = [
    (1, "7/19 (日)", "南下海岸線啟程",
     "MPK → Santa Barbara → Solvang → Moro Beach", "#1e4d7b", 2, (4, 16)),
    (2, "7/20 (一)", "海洋公路 1 號漫遊",
     "Cambria → Hearst Castle → Big Sur → Monterey", "#9a6e00", 3, (4, 16)),
    (3, "7/21 (二)", "蒙特雷海濱日",
     "Monterey Bay Aquarium → 17 Miles Drive → Carmel-by-the-Sea", "#2d5a2d", 4, (4, 16)),
    (4, "7/22 (三)", "進城舊金山",
     "Drive to SF → Santa Cruz → Half Moon Bay → Pigeon Point → Golden Gate", "#4a2d7a", 5, (4, 16)),
    (5, "7/23 (四)", "舊金山經典 1 日",
     "Boudin → Alcatraz → Cable Car → Union Square → Lombard → Ghirardelli", "#7a1f1f", 6, (4, 16)),
    (6, "7/24 (五)", "金門北岸自然行",
     "Muir Woods → Sausalito Waterfront → 回到 SF", "#6b2545", 7, (4, 16)),
    (7, "7/25 (六)", "矽谷遠足",
     "Stanford 校園 & 周邊午餐", "#0C447C", 2, (20, 32)),
    (8, "7/26 (日)", "返鄉日",
     "Apple Park Visitor Center → Netskope HQ → Kath's House", "#534AB7", 3, (20, 32)),
]

META = {
    "eyebrow": "SF ROAD TRIP · 2026",
    "title_main": "加州",
    "title_em": "太平洋公路",
    "title_tail": "舊金山",
    "sub": "7月19日 — 7月26日 · 8天 · 自駕公路旅行",
    "pill_1": "✈ MPK → SFO",
    "pill_2": "Big Sur 公路 1 號",
    "pill_3": "Monterey · Alcatraz · Muir Woods",
    "pill_4": "8天 · 多飯店",
}

RE_CHECKIN = re.compile(r"(?:check ?in|checkin|stay\s*@|stay\s+at)", re.I)
HOTEL_ICONS = [
    ("A", "#0C447C", "#EBF3FB"),
    ("M", "#27500A", "#EAF3DE"),
    ("D", "#534AB7", "#EEEDFE"),
    ("S", "#833C00", "#FAEEDA"),
    ("H", "#444441", "#F1EFE8"),
]


def slot_of(text: str):
    t = text.lower()
    if "breakfast" in t or "brunch" in t: return "b"
    if "lunch" in t: return "l"
    if "dinner" in t: return "d"
    return None


def clean_meal_name(text: str) -> str:
    t = re.sub(r"^\s*\d{1,2}:\d{2}\s*", "", text.strip())
    m = re.search(r"(?:breakfast|lunch|dinner|brunch)\s+(?:@|at|in)\s+(.+?)$", t, re.I)
    if m: return m.group(1).strip().rstrip(".,;:")
    m = re.search(r"and\s+(?:breakfast|lunch|dinner|brunch)\s+(?:@|at|in)?\s*(.+?)$", t, re.I)
    if m and m.group(1).strip(): return m.group(1).strip()
    stripped = re.sub(r"\b(breakfast|lunch|dinner|brunch)\b\s*(@|at|in)?\s*", "", t, flags=re.I).strip()
    return re.sub(r"^\W+", "", stripped) or "TBD"


def region_for(text: str) -> str:
    t = text.lower()
    if "monterey" in t: return "蒙特雷"
    if "san francisco" in t or "sf" in t or "donatello" in t: return "舊金山"
    if "moro" in t or "morro" in t: return "中加州海岸"
    return "其他"


# ============================================================
#  TRANSFORM
# ============================================================
def transform(grid):
    """grid: 2D list from gspread .get(). Returns structured dict."""
    maxw = max((len(r) for r in grid), default=0)
    grid = [r + [""] * (maxw - len(r)) for r in grid]

    def cell(r1, c0):
        r = r1 - 1
        if r >= len(grid) or c0 >= len(grid[r]): return ""
        return grid[r][c0].strip()

    days = []
    spots = []
    meals = []
    meals_seen = set()
    hotels = []
    hotel_id = 1

    for did, date, title, theme, color, col, (rstart, rend) in DAYS_LAYOUT:
        days.append({
            "id": str(did), "date": date, "title": title,
            "color": color, "theme": theme, "core": ""
        })

        for r in range(rstart, rend + 1):
            time_label = cell(r, 0)
            if time_label not in TIME_MAP: continue
            text = cell(r, col)
            if not text: continue
            time = TIME_MAP[time_label]

            # Hotel check-in
            if RE_CHECKIN.search(text):
                m = re.search(r"(?:check\s*in|checkin|stay\s*@|stay\s+at)\s*(.+?)$", text, re.I)
                name = (m.group(1).strip() if m else text)
                name = re.sub(r"\s*\(.*?\)\s*", "", name).strip()
                name = re.sub(r"\bhotel\b\s+(in\s+)?", "", name, flags=re.I).strip()
                name = re.sub(r"^[\-•]+\s*", "", name).strip()

                rows_md_lines = []
                paren = re.search(r"\(([^)]+)\)", text)
                if paren: rows_md_lines.append(f"備註 | {paren.group(1).strip()}")
                money = re.search(r"\$[\d.,]+(?:\s*\w+)?", text)
                if money: rows_md_lines.append(f"費用 | {money.group(0)}")

                ic, icc, icb = HOTEL_ICONS[(hotel_id - 1) % len(HOTEL_ICONS)]
                hotels.append({
                    "id": str(hotel_id), "region": region_for(text),
                    "icon": ic, "icon_color": icc, "icon_bg": icb,
                    "name": name or "Hotel TBD",
                    "dates": f"Day {did}（{date}） 入住",
                    "address": "",
                    "rows_md": "\n".join(rows_md_lines),
                    "tags": "default:詳情待補",
                    "conf": "", "cancel_status": "tip:待確認",
                })
                hotel_id += 1
                spots.append({
                    "day_id": str(did), "time": time,
                    "title": "🏨 入住 " + (name[:30] or "TBD"),
                    "desc": text, "tags": "hotel:住宿",
                    "route_path": "", "route_time": "", "route_warn": "",
                    "extra_md": "", "route_detail_md": "", "rental_md": "",
                })
                continue

            # Meal?
            slot = slot_of(text)
            if slot:
                key = (did, slot)
                if key not in meals_seen:
                    meals_seen.add(key)
                    meals.append({
                        "day_id": str(did), "slot": slot,
                        "name": clean_meal_name(text), "note": text,
                        "url": "", "options_md": "",
                    })
                    continue
                spots.append({
                    "day_id": str(did), "time": time, "title": text[:60],
                    "desc": text, "tags": "food:用餐",
                    "route_path": "", "route_time": "", "route_warn": "",
                    "extra_md": "", "route_detail_md": "", "rental_md": "",
                })
                continue

            # Regular spot
            title_clean = re.split(r"[,，:：]\s*", text, maxsplit=1)[0].strip()
            if len(title_clean) > 50: title_clean = title_clean[:50] + "…"

            tags = []
            tl = text.lower()
            if any(w in tl for w in ["drive", "freeway", "head to", "return", "leave", "to "]):
                tags.append("drive:駕車")
            if any(w in tl for w in ["beach", "park", "trail", "woods", "falls", "bridge", "garden"]):
                tags.append("park:景點")
            if "optional" in tl:
                tags.append("tip:可選")
            if any(w in tl for w in ["ferry", "alcatraz", "castle", "museum", "aquarium"]):
                tags = [t for t in tags if not t.startswith("drive:")]
                tags.append("tip:必訪")
            tags_str = ";".join(dict.fromkeys(tags))

            spots.append({
                "day_id": str(did), "time": time,
                "title": title_clean, "desc": text, "tags": tags_str,
                "route_path": "", "route_time": "", "route_warn": "",
                "extra_md": "", "route_detail_md": "", "rental_md": "",
            })

    meta_list = [{"key": k, "value": v} for k, v in META.items()]
    return {
        "meta": meta_list,
        "days": days,
        "spots": spots,
        "meals": meals,
        "hotels": hotels,
        "checklist": [],
    }


# ============================================================
#  FETCH + WRITE
# ============================================================
def extract_ids(sheet_url: str):
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
    if not m: raise ValueError(f"Not a valid Google Sheet URL: {sheet_url}")
    sheet_id = m.group(1)
    gm = re.search(r"[?&#]gid=(\d+)", sheet_url)
    gid = int(gm.group(1)) if gm else None
    return sheet_id, gid


def fetch_grid(sheet_url: str, credential_path: str):
    sheet_id, gid = extract_ids(sheet_url)
    creds = Credentials.from_service_account_file(credential_path, scopes=[
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    ws = next((w for w in sh.worksheets() if w.id == gid), None) if gid is not None else sh.sheet1
    if ws is None:
        raise RuntimeError(f"No worksheet with gid={gid}")
    print(f"  source: {sh.title} / {ws.title} ({ws.row_count}×{ws.col_count})")
    return ws.get("A1:Z40")


def build(sheet_url: str, credential_path: str, template_path: Path, output_path: Path):
    print(f"→ Fetching sheet...")
    grid = fetch_grid(sheet_url, credential_path)

    print(f"→ Transforming...")
    data = transform(grid)
    print(f"  {len(data['days'])} days, {len(data['spots'])} spots, "
          f"{len(data['meals'])} meals, {len(data['hotels'])} hotels")

    print(f"→ Reading template: {template_path}")
    template = template_path.read_text(encoding="utf-8")

    if "__INLINE_DATA__" not in template:
        raise RuntimeError("template.html missing __INLINE_DATA__ placeholder")

    # Embed as JSON. Use json.dumps with ensure_ascii=False to keep Chinese readable.
    inline = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    # Inject build timestamp (Taipei TZ)
    tz = timezone(timedelta(hours=8))
    built_at = datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z")

    output_html = (template
        .replace("__INLINE_DATA__", inline)
        .replace("__BUILT_AT__", built_at)
        .replace("__SOURCE_URL__", sheet_url))

    print(f"→ Writing: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_html, encoding="utf-8")
    print(f"✓ Done. Size: {len(output_html):,} bytes  Built: {built_at}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-url", required=True)
    ap.add_argument("--credential", required=True)
    ap.add_argument("--template", default="template.html")
    ap.add_argument("--output", default="dist/index.html")
    args = ap.parse_args()

    try:
        build(args.sheet_url, args.credential,
              Path(args.template), Path(args.output))
    except Exception as e:
        print(f"✗ Build failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
