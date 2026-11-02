---
feature: YouTube Dossier Engine Technical Specifications
status: Final
date: 2026-11-01
---

# Technical Specifications (`SPECS.md`) — YT//DOSSIER_ENGINE (`v1.2.0`)

## 1. System Architecture & Zero-Token Protocol

`YT//DOSSIER_ENGINE` operates with **$0.00 API token cost** by combining two direct extraction mechanisms:

1. **YouTube Charts InnerTube v1 (`https://charts.youtube.com/youtubei/v1/browse`):**
   - **Browse ID:** `FEmusic_analytics`
   - **Client Context:** `WEB_MUSIC_ANALYTICS` (`clientVersion: "2.0"`)
   - **Supported Surfaces:**
     - `VIDEOS`: **Daily Top Music Videos** (Top 100 finalized 24-hour cycle per sovereign country or Global; typically lags wall-clock time by 24–48 hours).
     - `TRENDING_VIDEOS`: **Overall YouTube Trending** (Top 20–100 live real-time snapshot per sovereign country).
   - **Supported Territories:** 86 sovereign ISO 3166-1 alpha-2 country codes plus `GLOBAL`.

2. **YouTube Media & Top Comment Extraction (`yt-dlp`):**
   - Extracts static video metadata, exact UTC `release_timestamp`, video/audio stream specs, description lyrics, and top community comments.
   - **Top Engaged Comment Extraction Args:**
     ```bash
     yt-dlp --dump-single-json --skip-download --write-comments \
       --extractor-args "youtube:comment_sort=top;max_comments=60,60,0,0" \
       "https://www.youtube.com/watch?v=<VIDEO_ID>"
     ```
   - Pulls up to 60 top-level parent comments (`max_replies=0`) using YouTube's `top` sort, sorts them strictly by `like_count` descending in Python, and exports the top `N` (default 20) with `YYYY-MM-DD HH:MM PST` timestamps and direct `&lc=<comment_id>` permalinks.

---

## 2. Virality Tier & Velocity Formulas

### 2.1 Velocity Metrics
Given `release_timestamp` (UTC) and snapshot execution time `now_utc`:
- `hours_since_release = max(1.0, round((now_utc - release_dt).total_seconds() / 3600.0, 2))`
- `views_per_hour = round(view_count / hours_since_release, 2)`
- `likes_per_hour = round(like_count / hours_since_release, 2)`
- `like_to_view_ratio_pct = round((like_count / view_count) * 100, 2)`
- `comment_to_view_ratio_pct = round((comment_count / view_count) * 100, 4)`

### 2.2 Dual-Axis Virality Tier Classification
To ensure newly released high-velocity music videos and older high-view catalog videos are both properly classified, `virality_tier` is computed using a dual-threshold OR rule:

```python
if views >= 50_000_000 or views_per_hour >= 250_000:
    virality_tier = "Mega-Viral"
elif views >= 10_000_000 or views_per_hour >= 50_000:
    virality_tier = "High-Velocity"
elif views >= 1_000_000 or views_per_hour >= 10_000:
    virality_tier = "Viral"
elif views >= 100_000 or views_per_hour >= 1_000:
    virality_tier = "Moderate"
else:
    virality_tier = "Emerging"
```

---

## 3. 5-Layer Composable Dataset Schema

Each track dossier folder (`datasets/youtube/<slug>_<video_id>/`) contains:

| Layer | JSON File | CSV File | Primary Key / Deduplication Rule |
| :--- | :--- | :--- | :--- |
| **Manifest** | `manifest.json` | — | Overwritten on each sync with updated `date_metrics` and `summary_metrics` |
| **Layer 1: Metadata** | `video_metadata.json` | `video_metadata.csv` | `video_id` |
| **Layer 2: Telemetry** | `video_telemetry_snapshot.json` | `video_telemetry_snapshot.csv` + `video_telemetry_history.csv` | Appends time-series row to `video_telemetry_history.csv` on every re-sweep |
| **Layer 3: Rankings** | `country_chart_rankings.json` | `country_chart_rankings.csv` | Composite key `(country_code, chart_type, chart_date)` — merges new dates while preserving historical cycles |
| **Layer 4: Comments** | `top_comments_ranked.json` | `top_comments_ranked.csv` | `comment_id` — sorted by `likes_count` descending |
| **Layer 5: Share Cards** | `share_cards_registry.json` | `share_cards_registry.csv` + `share_cards_cache/*.jpg` | Keyed by `country_code` + cached on disk in `share_cards_cache/` |

---

## 4. Past `#1` Rank Detection & Territory Timeline Enrichment

When `load_all_youtube_datasets()` hydrates a dataset for the Web Console, it groups all historical and current rows by `country_code` and computes:
- `all_time_best_rank`: Minimum `rank_position` (or `previous_position` if `previous_position == 1`) ever recorded for that country.
- `reached_number_one`: `True` if any recorded cycle in that country had `rank_position == 1` or `previous_position == 1`.
- `number_one_timeline`: Ordered list of every `#1` achievement in that territory (`chart_date`, `chart_week`, `chart_type`, and whether it was a `Current Cycle #1` or `Previous Cycle #1`).
- `territory_history`: Chronological list of all captured chart cycles for that territory, allowing one-click switching inside the right-hand Inspector drawer.

---

## 5. URL Query String Routing Specification

The Web Console synchronizes application state with the URL query string via `window.history.pushState` and `popstate` listeners:

| Parameter | Allowed Values | Description |
| :--- | :--- | :--- |
| `view` | `track` \| `artist` \| `compare` \| `lookup` | Active workspace mode |
| `id` | `<dataset_folder_id>` or `<video_id>` | Active track or artist dataset identifier |
| `tab` | `overview` \| `daily` \| `trending` \| `cards` \| `audience` \| `layers` | Active sub-view tab when `view=track` or `view=artist` |
| `layout` | `columns` \| `rows` | Side-by-Side Columns (`columns`) vs. Stacked Strips (`rows`) on the `compare` view |
| `sort` | `views_per_hour` \| `views` \| `likes` \| `like_ratio` \| `unique_countries` \| `ever_ones` \| `best_rank` \| `hours_since_release` \| `top_comment_likes` | Active sort metric on the `compare` view |
| `dir` | `desc` \| `asc` | Sort direction on the `compare` view |
| `pins` | Comma-separated `<track_id>` list | Pinned track IDs isolated in the Compare view |
| `q` | Artist name, `@handle`, channel ID, or URL | Active query on the `lookup` view |
| `type` | `ALL` \| `Official MV` \| `Lyric / Audio` \| `Performance / Live` \| `Teaser / Film` \| `Behind / Vlog` \| `Short` | Active video type filter on the `lookup` view |
| `status` | `ALL` \| `NOT_ADDED` \| `ADDED` | Workspace added status filter on the `lookup` view |

---

## 6. HTTP Server Endpoints (`youtube_dossier_web_server.py`)

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/` or `/index.html` | Compiles and serves the live interactive console HTML |
| `GET` | `/api/datasets` | Returns full hydrated JSON payload for all Track Dossiers & Artist Sweeps |
| `GET` | `/api/sweep/status` | Returns real-time progress (`current_idx`, `total_countries`, `hits_found`, `elapsed_sec`, `message`) |
| `POST` | `/api/channel/lookup` | Resolves an artist/channel query, lists up to 120 channel videos, classifies video types, and flags `already_added` tracks |
| `POST` | `/api/sweep/batch-tracks` | Sequentially compiles 5-Layer Track Dossiers for a shortlisted array of `video_ids` with live progress & cancel support |
| `POST` | `/api/sweep/track` | Starts a Single-Track 5-Layer Dossier sweep (returns `409 Conflict` if a sweep is already active) |
| `POST` | `/api/sweep/artist` | Starts an Artist / Channel Top 100 sweep |
| `POST` | `/api/sweep/cancel` | Sets the thread-safe cancellation flag to abort an active sweep |
| `GET` | `/api/share-card/image` | Serves a 1080×1920 Share Card JPEG from `share_cards_cache/` (or downloads and caches it on demand) |
| `POST` | `/api/share-cards/cache-all` | Concurrently downloads and caches all 1080×1920 JPEGs for a dataset into `share_cards_cache/` |
| `POST` | `/api/share-cards/export-zip` | Packages all or selected 1080×1920 JPEGs + `share_cards_manifest.json` into a named `.zip` archive |
| `GET` | `/api/export/<folder>/<file>` | Downloads raw `.json`, `.csv`, `.md`, `.jpg`, or `.zip` files from a dataset directory |
