# CLAUDE.md — ca-trip project context

> Read this first. Contains all context from the previous session so you can continue without re-asking.

## What this project is

A **static itinerary website** for a 2026 California road trip (SF · Big Sur · Monterey, 7/19–7/28).
Content is authored in a Google Sheet, rendered to a self-contained HTML file via a local build pipeline,
and deployed to GitHub Pages.

**Live site:** https://mong0520.github.io/ca-trip/
**GitHub repo:** https://github.com/mong0520/ca-trip (public)

## Architecture

```
Google Sheet (time × day grid)
        ↓ build.py (uses gspread + service account)
   structured JSON {meta, days, spots, meals, hotels}
        ↓ template.html injection (replaces __INLINE_DATA__)
   dist/index.html (self-contained: CSS + JS + data inlined, ~30KB)
        ↓ git push to mong0520/ca-trip main branch
   GitHub Pages serves index.html from / root
```

At runtime the browser does **no network calls** — everything is inlined.

## Key locations

| Thing | Path / URL |
|-------|-----------|
| **This repo (deploy target)** | `/Users/neilwei/git/github.com/mong0520/ca-trip/` |
| **Build pipeline** | `/Users/neilwei/trip2026-viewer/` |
| **Service account credential** | `/Users/neilwei/.uid_devops/personal_google_sheets_credential.json` |
| **Source Google Sheet (user's grid)** | https://docs.google.com/spreadsheets/d/16y_CiDH2TmPyMEkTD2iKNA7ZgJ9LJSQ97A-U4cbAYI0/edit?gid=2057583261 |
| **Travel Template sheet (intermediate / unused after static build)** | https://docs.google.com/spreadsheets/d/1gGeDihacpB_rDrCKEglYCP6qBJPuvHCs8qfdHJlaR34/edit |
| **Service account email** | `google-photo@myphoto-1527596562021.iam.gserviceaccount.com` |
| **GCP project** | `myphoto-1527596562021` |

The build pipeline is currently in a **separate folder** (`/Users/neilwei/trip2026-viewer/`).
You may want to move it here — see "Consolidation suggestion" below.

## Build pipeline files (in `/Users/neilwei/trip2026-viewer/`)

```
trip2026-viewer/
├── Taskfile.yml      # `task render` reads SHEET_URL hardcoded here
├── build.py          # fetch sheet → transform grid → inject into template
├── template.html     # HTML shell with __INLINE_DATA__ + __BUILT_AT__ + __SOURCE_URL__ placeholders
├── viewer.html       # legacy dynamic version (uses gviz CSV fetch, kept for reference)
├── dist/index.html   # build output
└── README.md
```

### How to update the site

```bash
# 1. Edit the Google Sheet (the time × day grid one) — user does this in browser
# 2. Rebuild static HTML
cd /Users/neilwei/trip2026-viewer && task render
# 3. Copy to this repo and push
cp /Users/neilwei/trip2026-viewer/dist/index.html /Users/neilwei/git/github.com/mong0520/ca-trip/index.html
cd /Users/neilwei/git/github.com/mong0520/ca-trip
git add index.html && git commit -m "update $(date +%F)" && git push
# GitHub Pages auto-rebuilds in ~30 seconds
```

The user asked at the end of last session whether to wrap this into a single `task deploy` command —
that was not yet done.

## Source sheet format (the quirky part)

The source sheet is a **time × day grid**, NOT a structured schema:

- **Column A** = time labels: `8-9 am`, `9-10 am`, ..., `8-9 pm` (13 slots)
- **Row 3** = date headers for days 1–6: `Sunday, July 19, 2026` ... `Friday, July 24, 2026` (cols B–H)
- **Row 19** = date headers for days 7–8: `Saturday, July 25, 2026`, `Sunday, July 26, 2026`
- **Row 19 cols F, G** show `Wednesday, January 25, 2023` / `Thursday, January 26, 2023` — **these are leftover template residue, ignored.**
- **Cells = activities** at that day×time (sparse — many empty)

Title says "7/19-7/28" but only 8 days have data. Days 9–10 (7/27, 7/28) are not in the sheet.

### Transform rules (encoded in `build.py`)

- Cells containing `check in`, `checkin`, `stay @`, `stay at` → **Hotel** entry
- Cells containing `breakfast`, `lunch`, `dinner`, `brunch` → **Meal** entry (first match per day per slot)
- Everything else → **Spot** entry
- Day metadata (title, theme, color) is **hardcoded** in `DAYS_LAYOUT` in `build.py`

### Known data-quality issues (from sparse source data)

These come from the source sheet being informal — fix by editing the sheet OR improving `build.py` parsers:

| Where | Current output | What it should be |
|-------|---------------|-------------------|
| D5 早餐 name | `public transportation)` | `Boudin Bakery Cafe` |
| D5 晚餐 name | `and Ghirardelli Square` | `Ghirardelli Square` |
| Hotel 1 name | `Moro Beach Avolon Inn 7815 for 2 rooms +$122.63 3rd room` | Just `Moro Beach Avalon Inn`, move price to rows_md |
| D7 lunch | `there` | name of Stanford-area restaurant |

## Markdown dialect (used in spot extra_md / route_detail_md / rental_md)

The build pipeline supports this mini-language in cells:

| Syntax | Renders as |
|--------|-----------|
| `## 標題` | Card title (bold) |
| `### 子標題` | Sub-heading |
| `**bold**` | `<strong>` |
| `!warn 文字` | 🔴 red warning row |
| `!tip 文字` | 🟢 green tip row |
| `!info 文字` | 🔵 blue info row |
| `- item` | bullet list |
| blank line | paragraph break |

The current build doesn't use any of these in spot output yet (just plain titles + descriptions),
because the source sheet doesn't author rich content. But the renderer supports it for future use.

## Tags

In the `tags` cell of a spot: semicolon-delimited `type:text` pairs.
Available types: `drive`, `food`, `shop`, `park`, `hotel`, `warn`, `tip`, `default`.

Example: `warn:入境旺季排隊 60 分鐘;tip:女孩必拍`

## GitHub Pages setup (already done)

- Repo: `mong0520/ca-trip` (was PRIVATE, changed to PUBLIC during deploy — required for free Pages)
- Pages source: **`main` branch, `/` root**
- URL: https://mong0520.github.io/ca-trip/
- HTTPS enforced
- First deploy commit: `247e312` (Initial deploy: 2026 SF road trip itinerary)

## Schema reference (data shape inside the inlined JSON)

```ts
{
  meta:  Array<{key, value}>,       // hero text, pills
  days:  Array<{id, date, title, color, theme, core}>,
  spots: Array<{day_id, time, title, desc, tags, route_path, route_time, route_warn,
                extra_md, route_detail_md, rental_md}>,
  meals: Array<{day_id, slot, name, note, url, options_md}>,  // slot: b/l/d
  hotels: Array<{id, region, icon, icon_color, icon_bg, name, dates, address,
                 rows_md, tags, conf, cancel_status}>,
  checklist: []  // not used yet
}
```

`day_id` in spots/meals matches `id` in days (string).
Hotels' `region` controls the grouping headers in the Hotels tab.

## Consolidation suggestion (not yet done)

The build pipeline (`build.py`, `Taskfile.yml`, `template.html`) currently lives in
`/Users/neilwei/trip2026-viewer/` — separate from this repo. To consolidate:

```bash
# Move build files into this repo
cd /Users/neilwei/git/github.com/mong0520/ca-trip
cp /Users/neilwei/trip2026-viewer/{build.py,Taskfile.yml,template.html} .

# Adjust Taskfile so OUTPUT goes to ./index.html (root, not dist/)
sed -i '' "s|dist/index.html|index.html|" Taskfile.yml

# Add a `deploy` task that runs render + git push
# (see Future improvements below)

git add build.py Taskfile.yml template.html .gitignore
git commit -m "Move build pipeline into repo"
git push
```

**`.gitignore` to add:**
```
__pycache__/
*.pyc
.DS_Store
# Don't commit credentials — they live in ~/.uid_devops/ outside the repo
```

After consolidation, the workflow becomes:

```bash
cd /Users/neilwei/git/github.com/mong0520/ca-trip
task deploy   # render + commit + push, one command
```

## Future improvements (mentioned but not done)

1. **`task deploy` command** — combine render + git commit + git push
2. **GitHub Actions** — auto-rebuild on a schedule (would need credential as encrypted secret;
   careful: it's a personal service account, not project-scoped)
3. **Auto-detect dates from sheet** — instead of hardcoded `DAYS_LAYOUT` in `build.py`
4. **Smart meal name extraction** — improve regex to handle cases like
   `"X and lunch @ Y"` (currently leaks "and")
5. **Hotel name cleanup** — strip prices, room counts from name field

## Quirks worth knowing

- **iCloud sync issue with Desktop**: Earlier in the project I had files in `~/Desktop/trip2026-viewer/`
  that got moved to `.Trash` automatically (probably iCloud Desktop sync). All files now live
  outside the Desktop to avoid this.
- **Browse skill (gstack/browse)** got stuck mid-session — couldn't verify the static build visually.
  Verification was done via `curl + python json.loads` to confirm data integrity. The viewer.html
  was visually validated earlier in the same session and uses the same renderer, so confidence is high.
- **The Travel Template sheet (`1gGeDihacpB...`)** is an intermediate format we created early in the
  session. After moving to the static build flow, **it's no longer used** by anything — the build
  reads from the source grid sheet directly. You can ignore or delete it.

## Service account info (for sharing new sheets)

If a new Google Sheet needs to be readable by the build:

1. Open Sheet → Share
2. Add: `google-photo@myphoto-1527596562021.iam.gserviceaccount.com`
3. Permission: **Viewer** (read-only is enough)
4. Update `SHEET_URL` in `Taskfile.yml`

The credential JSON is at `/Users/neilwei/.uid_devops/personal_google_sheets_credential.json`.
There is also a UID-org service account (`uid-rate-limiting@uid-cloud...`) — that one is for work sheets,
not personal. Don't confuse them.

## Personal skill files (related)

- `/Users/neilwei/.claude/skills/personal-google-sheet/SKILL.md` — Personal Google Sheets skill
- `/Users/neilwei/.claude/skills/uid-access-google-sheet/SKILL.md` — UID work Sheets skill (do NOT use for this project)

## Session history summary (high-level only)

1. User showed me the inspiration: `github.com/CH-CTH/trip2026` (a beautifully designed AI-generated trip site)
2. We reverse-engineered the format into a Google Sheet schema (Meta/Days/Spots/Meals/Hotels)
3. Filled it with 3 days of demo data, then ingested user's actual SF trip from a sparse grid sheet
4. Built a dynamic viewer (viewer.html, gviz CSV fetch) — works but requires the sheet to be "anyone with link"
5. Built a static renderer (`build.py` + `template.html`) — fully self-contained output
6. Deployed to GitHub Pages at `mong0520.github.io/ca-trip` (changed repo to public)

The output you see today is from the **static** path, not the dynamic viewer.
