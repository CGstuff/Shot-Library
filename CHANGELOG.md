# Changelog

All notable changes to Shot Library will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Open source release on GitHub
- Comprehensive documentation (README, Getting Started, Studio Guide, Architecture)
- GPL-3.0 License

---

## [1.1.0] - 2026-05-13

### Added

#### Shot Metadata Expansion (Schema v12)
- **Frame Range** (`frame_in` / `frame_out`) — Editorial cut range per shot, backfilled from the latest playblast's `frame_count` at migration time
- **Description** column — Free-form notes for shots (display-only in SL; intended for authoring upstream)
- **Priority** column — Three-tier production priority (1=Low / 2=Normal / 3=Urgent), defaults to Normal for all shots

#### Shot Info Panel
- **New section** between Shot Identity and Playblast Info, surfacing shot-level facts at a glance:
  - **FPS** — pulled from the latest playblast
  - **Frame Range** — from the shot row (v12 columns)
  - **Duration** — computed `frame_count / fps`, shown in seconds (e.g., `4.17s`)
  - **Resolution** — project resolution from `app_settings`, with playblast preview pixels as a parenthetical when they differ (e.g., `3840×2160 (preview: 1920×1080 @ 50%)`)
  - **Description** — when non-empty
- All fields are read-only — matches the architectural law that Blender is the only write authority

#### Priority Badge (Lineage section)
- **Colored badge** below the Status row: **green** Low, **blue** Normal, **red** Urgent
- **Click to change** — opens a Low/Normal/Urgent menu with the current value checked
- Routes through the same `bulk_set_priority` code path as the multi-select context menu, so single-shot and multi-shot updates share one transaction-safe service call

#### Bulk Priority Editing
- **"Set Priority" submenu** on the shot context menu — adapts to the selection size ("Set Priority for 4 shots" vs "Set Priority")
- Applies to the full multi-selection when the right-clicked shot is part of it, otherwise to just that shot
- Single SQL transaction across selected shots
- Per-shot audit log entries with old → new values
- Status-bar feedback: `"5 shots updated to priority Urgent"` (5s)

#### Project Resolution Setting
- **Settings → Backup → Project Settings** — configure the project's final delivery resolution
- **Preset dropdown** — HD 1080p / QHD 1440p / UHD 4K / DCI 4K / 8K / Custom
- **Width × Height spinboxes** (`0` = unset, displays as `—`)
- **Stored in `app_settings`** keys `project_resolution_width` / `project_resolution_height` — shared with Pipeline Control
- **Resolution disambiguation** — Shot Info now distinguishes the project's render target from the playblast preview pixels (especially useful when playblasts are captured at 50% for performance)

### Changed
- **Playblast Info section** — removed duplicate `FPS` / `Frame Count` / `Duration` rows (these now live canonically in Shot Info). Playblast Info keeps Name, Version, and Total Versions.
- **Default scrolling priority order** — new shots discovered during scans receive `priority=2` (Normal) via the `upsert` write path

### Fixed
- **Sync service** now preserves user-set v12 metadata across re-indexing — re-scans no longer reset `priority` / `frame_in` / `frame_out` / `description` back to defaults

### Database Schema (v12)
- Added `frame_in INTEGER`, `frame_out INTEGER`, `description TEXT DEFAULT ''`, `priority INTEGER DEFAULT 2` columns to `shots`
- Added `idx_shots_priority` index on `shots(priority)`
- Migration backfills `frame_in = 1`, `frame_out = playblasts.frame_count` for shots with an existing latest playblast
- Migration runs atomically inside the standard `_conn.transaction()` wrapper

---

## [1.0.0] - 2026-05-12

### Added

#### Core Features
- **Shot Discovery** — Automatic detection of shots from `.blend` files
- **Folder Schema Parser** — Configurable JSON schemas to adapt to any studio folder structure
- **Editorial Order Sorting** — Storyboard-order display using EEEE.SSSS.CCCC.HHHH format
- **Shot Versioning** — Support for versioned shots (shot_v001, shot_v002) with version grouping

#### Media Management
- **Playblast Indexer** — Tracks versioned MP4s in `PlayBlast/` folders
- **Lookdev Indexer** — Tracks lookdev renders in `Lookdev/` folders
- **Render Indexer** — PNG/EXR sequence indexing with MP4 proxy generation
- **Archive Support** — Tracks archived versions in `_archive/` subfolders
- **Latest Version Detection** — Automatically identifies the latest version

#### Multi-Camera Support (Schema v9-v10)
- **Shot Roles** — Standalone, Master, and View shot types
- **Reference Detection** — Automatic master/view relationship detection from filenames
- **View Names** — Support for camera suffixes (cam01, ref02)

#### Review System
- **Frame-Level Comments** — Comments attached to specific frames
- **Draw-Over Annotations** — Pen, brush, shapes, arrows, and text tools
- **User Color Coding** — Unique colors per reviewer
- **Sidecar JSON** — Portable review data alongside videos

#### Status Tracking
- **Shot Statuses** — WIP, In Review, Needs Work, Approved, Final, Blocked
- **Color-Coded Badges** — Visual status indicators
- **Bulk Status Updates** — Change multiple shots at once
- **Audit Trail** — All status changes logged

#### Integration
- **Operation Modes** — Standalone (full control) and Pipeline (read-only status)
- **Pipeline Control Integration** — Mode detection via `app_settings` table
- **REST API** — FastAPI server with JWT authentication
- **Blender Addon** — Playblast and lookdev capture

#### User Interface
- **Three-Pane Layout** — Folder tree, shot grid/list, metadata panel
- **Grid View** — 16:9 aspect ratio cards with thumbnails
- **List View** — Compact rows for dense information
- **Hover Preview** — Auto-playing video popup on hover (500ms delay)
- **Frame Timeline** — Timeline with frame ruler and playback controls
- **Dark/Light Themes** — Customizable appearance
- **Sequence Review Window** — Editorial-order playback with shot scrubbing

#### Performance
- **512MB Pixmap Cache** — Configurable thumbnail cache
- **Thumbnail Threading** — 4 background workers
- **Batch Loading** — 100 items per batch for smooth scrolling
- **Debounced File Observer** — 250ms debounce for filesystem events
- **Pre-buffered Playback** — 2-3 frames pre-loaded

### Database Schema (v11)
- `shots` — Core shot metadata with versioning and multi-camera support
- `playblasts` — Versioned playblast tracking
- `lookdevs` — Lookdev render tracking
- `renders` — Image sequence and proxy tracking
- `reviews` — Review session metadata
- `comments` — Frame-level comments
- `annotations` — Draw-over data
- `users` — User management
- `tasks` — Task assignments (Pipeline Control integration)
- `app_settings` — Application settings including operation mode
- `audit_log` — Change audit trail
- `folder_schemas` — Cached schema configurations

### Blender Addon
- **Minimum Version** — Blender 4.0+
- **Playblast Operator** — Render viewport to MP4 with automatic versioning
- **Lookdev Operator** — Render lookdev to MP4 with metadata
- **Version Manager** — Automatic version numbering and archiving
- **JSON Sidecars** — Metadata files alongside videos

---

## Schema Version History

| Version | Changes |
|---------|---------|
| v1 | Initial schema with shots, playblasts, status |
| v2 | Shot versioning (base_shot_name, shot_version, version_group_id) |
| v3 | Lookdevs table |
| v4 | Reviews, comments, annotations tables |
| v5 | Users table |
| v6 | Tasks table |
| v7 | app_settings table (operation_mode) |
| v8 | display_mode column on shots |
| v9 | Multi-camera support (shot_role, master_shot_id) |
| v10 | view_name column for camera suffixes |
| v11 | Renders table for image sequences |
| v12 | Shot metadata expansion (frame_in, frame_out, description, priority) |

---

## [0.9.0] - 2024-12-15

### Added
- Initial internal beta release
- Basic shot browsing and playblast viewing
- Folder tree navigation
- Simple status tracking

---

[Unreleased]: https://github.com/CGstuff/Shot-Library/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/CGstuff/Shot-Library/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/CGstuff/Shot-Library/releases/tag/v1.0.0
[0.9.0]: https://github.com/CGstuff/Shot-Library/releases/tag/v0.9.0
