---
feature: Swiss-Industrial Telemetry Console Design System
status: Final
date: 2026-11-01
---

# Design System & UI Architecture (`DESIGN.md`) — YT//DOSSIER_ENGINE

## 1. Structural Archetype: High-Density Telemetry Workspace

`YT//DOSSIER_ENGINE` is modeled after precision engineering and financial/audio telemetry interfaces (**Linear, Raycast, Teenage Engineering, Vercel**):
- **3-Pane Master Shell (`.app-shell`):**
  1. **Left Collapsible Datasets & Catalogs Rail (`260px`):** Instant switching between Cross-Track Comparison (`00 // BENCHMARK & COMPARE`), Single-Track 5-Layer Dossiers (`01 // TRACK DOSSIERS`), Artist Top 100 Sweeps (`02 // ARTIST TOP 100 SWEEPS`), and Engine Telemetry (`03 // ENGINE TELEMETRY`).
  2. **Main High-Density Canvas (`minmax(0, 1fr)`):** Top execution bar, live sweep progress monitor, entity header + 4-column Date & Cycle Telemetry Grid, 6-cell KPI Strip, sticky view tabs with pinned filter controls, and tabular/card workspaces.
  3. **Right Split-Pane Share Card & Territory Inspector (`360px`):** Displays the 1080×1920 (9:16) vertical YouTube Share Card preview, `#1` Peak History box, interactive Territory Cycle Timeline, and decoded Protobuf `?r=` token.

---

## 2. Color Tokens & Surface Hierarchy

Strictly monochromatic carbon/zinc surfaces with **International Signal Orange (`#FF5500`)** for primary actions/velocity and **Chart Emerald (`#10B981`)** for `#1` chart peaks and zero-token telemetry:

| CSS Variable | Hex / Value | Semantic Usage |
| :--- | :--- | :--- |
| `--bg-canvas` | `#070708` | Deep carbon primary background |
| `--bg-panel` | `#0E0E11` | Navigation rails, headers, table row headers |
| `--bg-elevated` | `#141418` | Elevated toolbars, section headers, active pills |
| `--bg-hover` | `#1A1A20` | Interactive row and button hover state |
| `--bg-active` | `#202028` | Selected table row / active card surface |
| `--border-hairline` | `#1F1F24` | Crisp `1px solid` structural hairlines |
| `--border-strong` | `#2E2E36` | Input controls, buttons, and card frames |
| `--text-primary` | `#F4F4F6` | High-contrast titles, primary values |
| `--text-secondary` | `#A0A0AB` | Secondary metadata, table cells |
| `--text-muted` | `#686873` | Monospace labels, timestamps, hints |
| `--accent-orange` | `#FF5500` | Primary execution accent, velocity bars, Top 5 badges |
| `--accent-emerald` | `#10B981` | `#1` Champion badges, disk cache status, upvote counts |
| `--accent-amber` | `#F59E0B` | Historical / Past `#1` peak badges |

---

## 3. Typography & Numeric Discipline

- **UI & Editorial Headings (`--font-sans`):** `'Inter', -apple-system, BlinkMacSystemFont, sans-serif` with tight tracking (`-0.025em`) on entity titles.
- **Telemetry, Ranks, Timestamps & IDs (`--font-mono`):** `'JetBrains Mono', ui-monospace, SFMono-Regular, monospace`.
- **Mandatory Tabular Numerals:** Every metric, rank pill, view count, hourly velocity, percentage, and timestamp enforces `font-variant-numeric: tabular-nums` so columns align vertically to the pixel.

---

## 4. Responsive Breakpoints & Modern Web Patterns

1. **`> 1320px` (Full 3-Pane Desktop):**
   - Single-row 48px Top Command Bar (`grid-template-columns: auto minmax(0, 1fr) auto`), docked Left Sidebar (`260px`), and docked Right Inspector (`360px`).
2. **`<= 1320px` (Laptop / Compact Desktop):**
   - Right Inspector automatically transitions into a fixed off-canvas slide-over drawer (`width: min(370px, 92vw)`), freeing horizontal space for data tables and side-by-side comparison columns.
3. **`<= 1120px` (Tablet Landscape):**
   - Top Command Bar transitions cleanly into a balanced 2-deck grid (Row 1: Brand + Status/Compare/Inspector buttons; Row 2: Full-width Sweep Execution Form).
4. **`<= 900px` (Tablet Portrait & Mobile):**
   - Left Datasets Sidebar transitions into an off-canvas slide-over drawer with a blurred backdrop (`#drawer-backdrop`).
   - Sticky tab bar stacks filter controls cleanly beneath the horizontal tab strip so filters remain 100% accessible.
5. **CSS Container Queries (`@container (width < 600px)`):**
   - Data tables inside `.containment-region` automatically adapt to narrow containers while preserving sticky row headers (`tbody th`) and keyboard scroll regions (`tabindex="0" role="region"`).
6. **State-Aware Sticky Headers (`IntersectionObserver`):**
   - `.sticky-tabs-container` uses an `IntersectionObserver` (`threshold: [1]`, `rootMargin: '-1px 0px 0px 0px'`) to toggle `.is-stuck` when scrolled, applying a subtle backdrop blur and shadow.

---

## 5. Historical Cycle Filters & Multi-Surface Sub-Grids

1. **Dynamic Cycle & Period Selector (`#cycle-date-filter`):**
   - Gathers every unique `chart_date` and `chart_week_label` across Daily and Weekly charts.
   - Formats weekly periods as `Week Ending YYYY-MM-DD` while listing single daily snapshots as `YYYY-MM-DD`.
   - Enables instant territory inspection across individual historical release days without triggering page reloads.

2. **Live Rank Tier Filter (`#rank-tier-filter`):**
   - Automatically parses current placements and previous peak history to present dynamic count badges:
     - `All Current + Past #1s (N)`
     - `Current #1 Champions (N)`
     - `Past #1s Only — Prev / Historical (N)`
     - `Top 5 Tier (<= #5)` / `Top 10 Tier (<= #10)` / `Top 20 Tier (<= #20)`

3. **Multi-Surface Sub-Grids (`02 // MUSIC VIDEO CHARTS`):**
   - Tab 2 cleanly divides placements into distinct, titled sections:
     - `3A // DAILY TOP MUSIC VIDEOS CHART`: 24h finalized daily velocity cycles.
     - `3C // WEEKLY TOP MUSIC VIDEOS CHART`: Official Thursday-ending weekly cycles (archives spanning back to 2016).

