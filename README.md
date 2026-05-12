<p align="center">
  <img src="assets/Icon.png" alt="Shot Library" width="128" height="128">
</p>

<h1 align="center">Shot Library</h1>

<p align="center">
  <strong>A read-only production visibility system for Blender pipelines</strong>
</p>

<p align="center">
  <a href="#license"><img src="https://img.shields.io/badge/License-GPL_v3-blue.svg" alt="GPL v3 License"></a>
  <img src="https://img.shields.io/badge/Python-3.9+-blue.svg" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/PyQt6-6.5+-orange.svg" alt="PyQt6">
  <img src="https://img.shields.io/badge/Blender-4.0+-orange.svg" alt="Blender 4.0+">
  <img src="https://img.shields.io/badge/FastAPI-REST%20API-009688.svg" alt="FastAPI">
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#installation">Installation</a> •
  <a href="GETTING_STARTED.md">Getting Started</a> •
  <a href="STUDIO_GUIDE.md">Studio Guide</a> •
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

## Background

Shot Library is a **read-only production visibility system** built for feature film and animation pipelines. It provides a unified view of all shots, playblasts, lookdevs, and renders across your project—without ever modifying production data.

Unlike asset management tools, Shot Library treats your **filesystem as the source of truth**. It indexes and displays what's already there, adapting to any studio's folder structure through configurable schemas.

Part of the [Pipeline Control](https://github.com/CGstuff/Pipeline-Control) ecosystem, alongside [Action Library](https://github.com/CGstuff/Action-Library) and [Universal Library](https://github.com/CGstuff/Universal-Library).

---

## Features

### Core Capabilities

- **Read-Only Safety** — Never modifies production files. The filesystem is the source of truth; Shot Library is an index.
- **Folder Schema Parser** — Adapts to any studio folder structure via configurable JSON schemas. No forced conventions.
- **Shot Discovery** — Automatic detection of shots from `.blend` files with version grouping and editorial ordering.
- **Multi-Camera Support** — Master/view relationships for multi-camera setups with automatic detection.

### Media Management

- **Playblast Versioning** — Tracks versioned MP4s in `PlayBlast/` folders with latest-version detection and archive tracking.
- **Lookdev Support** — Separate `Lookdev/` folder indexing for lighting and shading previews.
- **Render Management** — PNG/EXR sequence indexing with automatic MP4 proxy generation for preview.
- **PB/LD/RD Modes** — Switch between Playblast, Lookdev, and Render proxy MP4s in the preview panel.

### Review Workflow

- **Sequence Review** — View shots in editorial order, scrub through the sequence, navigate by storyboard position.
- **Shot Status Tracking** — WIP, In Review, Needs Work, Approved, Final, Blocked with color-coded badges.
- **Review System** — Frame-level comments, annotations, and draw-overs for review workflow.
- **User Color Coding** — Each reviewer gets a unique color for their comments.

### Integration

- **Operation Modes** — Standalone (full control) or Pipeline (read-only status, controlled by Pipeline Control).
- **REST API** — FastAPI server with JWT authentication for external tool integration.
- **Blender Addon** — Playblast and lookdev capture directly from Blender with automatic versioning.
- **Real-time Monitoring** — Watchdog-based folder observation with debounced updates.

### User Experience

- **Modern UI** — Grid/list views with 16:9 aspect ratio cards, dark/light themes.
- **Hover Preview** — Hover-to-play video popup with 500ms delay.
- **Frame Timeline** — Timeline with frame ruler, timecode display, and playback controls.
- **Version Comparison** — Side-by-side comparison of playblast versions.

---

## Installation

### Option 1: Download Release (Recommended)

1. Download the latest release from [Releases](https://github.com/CGstuff/Shot-Library/releases)
2. Extract to your preferred location
3. Run `ShotLibrary.exe` (Windows) or `ShotLibrary` (Linux/macOS)

### Option 2: Run from Source

```bash
# Clone the repository
git clone https://github.com/CGstuff/Shot-Library.git
cd Shot-Library

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run the application
python -m shot_library.main
```

**Requirements:**
- Python 3.9+
- PyQt6 6.5+
- OpenCV 4.8+
- Blender 4.0+ (for addon)

---

## Folder Schema Configuration

Shot Library adapts to your studio's folder structure through JSON schema files. Place a `.shot_library.json` file in your project root:

```json
{
  "name": "My Studio Schema",
  "hierarchy_levels": [
    {"level": "show", "pattern": "^(?P<show>[A-Z]{3})$"},
    {"level": "sequence", "pattern": "^SEQ(?P<seq>\\d{3})$"},
    {"level": "shot", "pattern": "^SH(?P<shot>\\d{4})$"}
  ],
  "blend_file_patterns": [
    "^(?P<shot>SH\\d{4})(?:_v(?P<version>\\d{3}))?\\.blend$"
  ],
  "playblast_folder": "PlayBlast",
  "playblast_pattern": "^v(?P<version>\\d{3})\\.mp4$"
}
```

See [GETTING_STARTED.md](GETTING_STARTED.md) for detailed schema configuration.

---

## Architecture

Shot Library follows strict architectural principles:

1. **Filesystem is Source of Truth** — The database is an index, not the authority
2. **Read-Only Operation** — Shot Library never modifies production files
3. **Blender Addon is Write Authority** — Only the addon creates playblasts/lookdevs
4. **Database is Disposable** — Can be rebuilt from filesystem at any time
5. **Configuration-Driven** — Folder schemas define structure, not hardcoded paths

```
┌─────────────────────────────────────────────────────────────────┐
│                         Shot Library                             │
├─────────────────────────────────────────────────────────────────┤
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐    │
│  │   Shot    │  │ Playblast │  │  Lookdev  │  │  Render   │    │
│  │  Indexer  │  │  Indexer  │  │  Indexer  │  │  Indexer  │    │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘    │
│        │              │              │              │           │
│        └──────────────┴──────────────┴──────────────┘           │
│                              │                                   │
│                    ┌─────────▼─────────┐                        │
│                    │  Folder Schema    │                        │
│                    │     Parser        │                        │
│                    └─────────┬─────────┘                        │
│                              │                                   │
│        ┌─────────────────────┼─────────────────────┐            │
│        │                     │                     │            │
│  ┌─────▼─────┐        ┌──────▼──────┐       ┌─────▼─────┐      │
│  │  SQLite   │        │   REST API  │       │  Blender  │      │
│  │  (Index)  │        │  (FastAPI)  │       │   Addon   │      │
│  └───────────┘        └─────────────┘       └───────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed system design.

---

## REST API

Shot Library includes a FastAPI server for external tool integration:

```bash
# Enable API in Settings > API
# Default: http://localhost:8765/api/v1/

# Get authentication token
curl -X POST http://localhost:8765/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username"}'

# List shots
curl http://localhost:8765/api/v1/shots \
  -H "Authorization: Bearer <token>"

# Update shot status
curl -X PATCH http://localhost:8765/api/v1/shots/{shot_id}/status \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"status": "Approved"}'
```

See [STUDIO_GUIDE.md](STUDIO_GUIDE.md) for complete API documentation.

---

## Documentation

| Document | Description |
|----------|-------------|
| [GETTING_STARTED.md](GETTING_STARTED.md) | First-time setup, folder schemas, browsing shots |
| [STUDIO_GUIDE.md](STUDIO_GUIDE.md) | Multi-user deployment, review system, REST API |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, indexers, database schema |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |

---

## Pipeline Control Ecosystem

Shot Library is part of a larger ecosystem for Blender pipelines:

```
                       Pipeline Control
                        (orchestrator)
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   Shot Library        Action Library      Universal Library
   (This Repo)            (global)             (global)
   Per-project         animations/poses    meshes/materials/rigs
   shots/playblasts
```

- **[Pipeline Control](https://github.com/CGstuff/Pipeline-Control)** — Orchestrator that controls status across all libraries
- **[Action Library](https://github.com/CGstuff/Action-Library)** — Global animation and pose library
- **[Universal Library](https://github.com/CGstuff/Universal-Library)** — Global asset library (meshes, materials, rigs)

---

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <sub>Built for artists who need to see their shots, not manage them.</sub>
</p>
