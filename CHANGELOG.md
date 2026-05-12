# Changelog

All notable changes to Shot Library will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---



### Added
- Open source release on GitHub
- Comprehensive documentation (README, Getting Started, Studio Guide, Architecture)
- GPL-3.0 License

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



---


---


