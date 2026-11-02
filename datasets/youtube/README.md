# 📹 Global Multi-Country YouTube Track & Video Intelligence Dossier Engine

> **Command**: `youtube-dossier`  
> **Source Script**: [`build_youtube_track_dossier.py`](file:///Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/blackpink-twitter/data/scripts/processors/build_youtube_track_dossier.py)  
> **Global Binary Path**: [`~/.local/bin/youtube-dossier`](file:///Users/bibbler/.local/bin/youtube-dossier)  
> **Output Root**: [`blackpink-twitter/data/datasets/youtube/`](file:///Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/blackpink-twitter/data/datasets/youtube/)  
> **Economics**: **100% Free** ($0.00 / 0 API tokens consumed)

---

## 🌟 Executive Overview

The **YouTube Track & Video Intelligence Dossier Engine** is an automated, zero-cost intelligence pipeline designed to extract, analyze, and catalog a complete 360-degree forensic dossier for any given YouTube music release or video asset.

Rather than dumping unformatted data into a single monolithic file, the engine compiles a structured, modular **5-Layer Composable Dataset** coupled with an executive Markdown briefing and a machine-readable `manifest.json`.

```
Target Video (URL or 11-char ID)
 │
 ├── 1. Static Metadata: video_metadata.json / .csv (Title, duration, tags, lyrics, channel ID)
 ├── 2. Live Telemetry: video_telemetry_snapshot.json / .csv (Views/hr, likes/hr, conversion ratios)
 ├── 3. Global Charts: country_chart_rankings.json / .csv (Daily & Trending ranks across up to 86 countries)
 ├── 4. Ranked Audience: top_comments_ranked.json / .csv (Top upvoted comments by likes & sentiment)
 └── 5. Visual Asset Layer: share_cards_registry.json / .csv (Official 1080x1920 9:16 vertical share cards)
      └── Bound together by: manifest.json (v1.1.0) & executive Markdown report
```

---

## 🚀 Key Capabilities

1. **Dynamic Input Parsing**:
   - Accepts standard watch URLs (`https://www.youtube.com/watch?v=...`), short links (`https://youtu.be/...`), Shorts URLs (`/shorts/...`), or raw 11-character video IDs.
2. **Zero-Token Local Execution**:
   - Extracts video metadata, velocity telemetry, and top community comments using `yt-dlp` locally (zero cloud bill, zero API tokens).
3. **Global 86-Territory Sweep**:
   - Sweeps all 86 official territories supported by YouTube Charts with an automated inter-request cooldown to respect network boundaries.
4. **Historical Date Scoping**:
   - Query historical daily chart rankings back to **November 6, 2023** using the `--date YYYY-MM-DD` parameter.
5. **Direct 1080×1920 High-Res Share Card Harvesting**:
   - Connects directly to the YouTube Charts InnerTube API to harvest official, server-rendered **1080×1920 (9:16 vertical) high-resolution image cards**, bypassing the need for brittle browser canvas screen-scraping.

---

## 💻 CLI Reference & Parameter Table

```bash
# Global CLI syntax
youtube-dossier (--url URL | --video-id VIDEO_ID) [OPTIONS]

# Or direct Python call
python3 blackpink-twitter/data/scripts/processors/build_youtube_track_dossier.py (--url URL | --video-id VIDEO_ID) [OPTIONS]
```

### Options

| Flag | Shorthand | Type | Default | Description |
| :--- | :---: | :---: | :---: | :--- |
| `--url` | `-u` | String | *None* | Full YouTube video URL |
| `--video-id` | `-i` | String | *None* | 11-character YouTube video ID |
| `--date` | `-d` | String | `None` (Latest) | Historical date scope in `YYYY-MM-DD` format (back to `2023-11-06`) |
| `--countries` | `-c` | String | `all` | Comma-separated ISO codes (e.g. `US,TH,BR`) or `all` for complete 86-country sweep |
| `--with-comments`| - | Flag | `False` | Opt-in to extract top 20 community comments (default: skipped for speed) |
| `--max-comments` | `-m` | Int | `0` (Disabled) | Explicitly set maximum top comments to extract (passing > 0 enables comments) |
| `--skip-comments`| - | Flag | `True` | Explicitly skip comment extraction (default behavior) |
| `--skip-charts` | - | Flag | `False` | Skip chart queries (metadata and telemetry snapshot only) |
| `--output-dir` | `-o` | String | Auto-slug | Custom target directory for output files |

---

## 📖 Usage Examples

### 1. Fast Global 86-Country Sweep (Default: Comments Skipped)
Sweeps all 86 territories, calculates view/like velocities, and registers all official share cards in seconds:
```bash
youtube-dossier --url "https://www.youtube.com/watch?v=FyS5dAywkEo"
```

### 2. Opt-in to Top Community Comments
Extracts top 20 comments with like counts:
```bash
youtube-dossier --url "https://www.youtube.com/watch?v=FyS5dAywkEo" --with-comments
# Or custom comment limit:
youtube-dossier --video-id FyS5dAywkEo --max-comments 50
```

### 3. Historical Date-Scoped Query
Pull daily chart positions and dated share cards for a specific historical date (e.g. October 25, 2026):
```bash
youtube-dossier --video-id 9ofUM-_3uQ4 --date 2026-10-25
```

### 4. Fast Regional Check
Sweep only priority territories (e.g. US, UK, Brazil, Thailand, France):
```bash
youtube-dossier --video-id 9ofUM-_3uQ4 --countries US,GB,BR,TH,FR
```
```bash
youtube-dossier --video-id 9ofUM-_3uQ4 --countries US,GB,BR,TH,FR --skip-comments
```

### 5. Artist / Channel Batch Top 100 Chart Sweep (No Video IDs Required)
Sweep YouTube Top 100 Charts across territories by Channel URL, Handle, ID, or Artist Name to automatically find all charting tracks:
```bash
# Global CLI command:
youtube-artist-charts @LISAOfficialVEVO --countries US,GB,TH,GLOBAL
youtube-artist-charts @megantheestallion
youtube-artist-charts --artist "LISA" --countries all

# Or invoke directly via youtube-dossier:
youtube-dossier @LISAOfficialVEVO --countries US,GB,TH,GLOBAL

# Auto-Pilot: Automatically generate full 5-layer dossiers for all discovered tracks:
youtube-artist-charts @LISAOfficialVEVO --dossier
```
*Outputs to `blackpink-twitter/data/datasets/youtube/artist_<artist_slug>/` with multi-track rankings CSV/JSON, `artist_catalog_manifest.json`, and an executive markdown report.*

### 6. Interactive Web Console & Remote API Server (`youtube-dossier-ui`)
Launch the Swiss Industrial Telemetry Web Console to explore all Track Dossiers and Artist Catalog Sweeps interactively, inspect 1080×1920 9:16 Share Cards, or trigger live sweeps from any local or remote browser:
```bash
# Start live local + network server (http://localhost:8088 & http://0.0.0.0:8088)
youtube-dossier-ui

# Or compile the standalone offline HTML snapshot only:
youtube-dossier-ui --build-only
```
- **Live Web Server**: `http://localhost:8088` (bound to `0.0.0.0:8088` for LAN/Tailscale remote access)
- **Standalone Offline Console**: [`blackpink-twitter/data/dashboards/youtube_dossier_console.html`](file:///Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/blackpink-twitter/data/dashboards/youtube_dossier_console.html)
- **Server & Compiler Script**: [`youtube_dossier_web_server.py`](file:///Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/blackpink-twitter/data/scripts/processors/youtube_dossier_web_server.py)

---

## 🗂️ Composable 5-Layer Dataset Architecture

Every run compiles its output into a dedicated slugged folder:  
`blackpink-twitter/data/datasets/youtube/<sanitized_title>_<video_id>/`

| Layer | Files | Description |
| :---: | :--- | :--- |
| **0** | `manifest.json` | **Unified Root Descriptor (v1.2.0)**: Machine-readable JSON linking all layers, recording record counts, charting summary, #1 champion territories, and explicit multi-date metrics (`daily_chart_cycle`, `trending_feed_state`, `dataset_date_coverage`). |
| **1** | `video_metadata.json`<br>`video_metadata.csv` | **Static Identity**: Full title, channel name, verified status, exact subscriber scale, duration, upload date, category, tags, and extracted lyrics. |
| **2** | `video_telemetry_snapshot.json`<br>`video_telemetry_snapshot.csv`<br>`video_telemetry_history.csv` | **Live Velocity & History**: Raw views, likes, comments, views/hour, likes/hour, like-to-view conversion ratio, hours since debut, virality tier, and append-only longitudinal history ledger. |
| **3** | `country_chart_rankings.json`<br>`country_chart_rankings.csv` | **Global Placement Matrix**: Ranked records per country, surface type (Daily Top Music Videos vs Overall Trending), rank positions, previous positions, status flags, and explicit `chart_date` timestamps. Non-destructive multi-date merging. |
| **4** | `top_comments_ranked.json`<br>`top_comments_ranked.csv` | **Audience Discussion**: Top upvoted comments sorted by likes, author handles, channel IDs, published dates, and like counts. (Skipped by default for 2-4s sync). |
| **5** | `share_cards_registry.json`<br>`share_cards_registry.csv` | **Visual Asset Registry**: Country-by-country catalog of official 1080×1920 (9:16 vertical) high-res graphic card URLs. |
| **Doc** | `<slug>_video_intelligence_report.md` | **Executive Markdown Briefing**: Formatted report with 4-line explicit date disambiguation (`Date Scope Target`, `Daily Music Chart Cycle`, `Trending Feed State`, `Dataset Date Coverage`), curated "Select Top Territory Placements" with peak classification badges, surface-grouped chart matrix (Daily Videos vs. Live Trending), 9:16 vertical share card visual gallery, and file links. |

---

## 🔬 Protocol Details: YouTube Charts InnerTube API

The chart and share card harvesting engine interfaces directly with YouTube's internal analytics infrastructure:

- **Endpoint**: `https://charts.youtube.com/youtubei/v1/browse?alt=json`
- **Browse Context**: `clientName: 'WEB_MUSIC_ANALYTICS'`, `clientVersion: '2.0'`, `platform: 'DESKTOP'`
- **Browse ID**: `FEmusic_analytics_charts_home`

### Share Card Structure
Share cards returned by YouTube follow this URI format:
```
https://charts.youtube.com/image/analytics/charts?r=<protobuf_base64>
```
The parameter `r` contains a Base64-encoded Protocol Buffer holding:
- Song / Video Title
- HD Video Thumbnail URL (`maxresdefault.jpg`)
- Rank Position (`1`, `2`, `32`, etc.)
- Primary Artist and Collaborator names
- Chart Surface Name (e.g. `Daily Top Music Videos Chart`)
- Full Country Name (e.g. `United States`, `Thailand`, `Brazil`)
- Chart Date (e.g. `Oct 30, 2026`)
- Dominant Graphic Color Palette (`#F84444`, `#000000`)

---

## ⚠️ Archival Depths & Operational Boundaries

1. **Daily Charts (`VIDEOS` / `SHORTS`)**:
   - Date scoping is supported via `--date YYYY-MM-DD`.
   - Historical depth extends back to **November 6, 2023**.
   - Note: Daily charts are typically published with a **24 to 48-hour calculation lag**.
2. **Weekly Charts (`TRACKS` / `ARTISTS`)**:
   - Historical depth extends back to **September 21, 2017** (7+ years of data).
   - Date queries must align with the Thursday chart close date.
3. **Trending Videos (`TRENDING_VIDEOS`)**:
   - Trending is **ephemeral only** (live snapshot).
   - It cannot be backdated. If `--date` is specified, trending checks are skipped.
4. **Rank Cutoff**:
   - YouTube Charts only serves ranked items (Top 100 for daily videos, Top 20-30 for trending). Videos ranked lower than the threshold will return as unranked.
5. **Cooldown Guardrail**:
   - The engine automatically applies a `120ms` delay between consecutive country queries to protect against transient IP rate limits.
