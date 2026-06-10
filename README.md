# 🤖 VERA — Visual Editor Reasoning Agent

> *Your AI co-pilot inside Unreal Engine.*

VERA is an open-source AI agent that can **see, understand, and control** the Unreal Engine 5 editor — navigating menus, changing settings, launching builds, and automating repetitive workflows, all through natural language commands.

```
You say:  "Set up this project for Android with only the Lobby map"
VERA:     → Opens Project Settings
          → Changes Default Maps to Lobby
          → Configures Android flags
          → Launches the build
          → Reports the result
```

## ✨ Key Features

- **Natural language commands** — Talk to your editor like a human
- **Token-efficient architecture** — 90%+ of actions execute with zero LLM calls
- **Hybrid perception** — Local OCR + CV first, Gemini Vision only as fallback  
- **UE Python API integration** — Direct editor scripting, no screenshots needed
- **Action recipe cache** — Learned workflows never cost tokens twice
- **Open source & extensible** — Community-contributed recipes welcome

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                    VERA AGENT                        │
│                                                     │
│  Natural Language Input                             │
│         ↓                                           │
│  [ Planner ] ──→ UE Python API (free, direct)       │
│         ↓                                           │
│  [ State Machine ] ──→ Coord Registry Cache (free)  │
│         ↓                                           │
│  [ Perception Layer ]                               │
│    ├── Local OCR / CV  (free, Tesseract/YOLO)       │
│    └── Gemini Vision   (paid, fallback only)        │
│         ↓                                           │
│  [ Action Executor ] → PyAutoGUI / UE Python        │
└─────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

```bash
pip install vera-ue
vera "Set project default map to Lobby"
vera "Configure Android build and launch on connected device"
vera "Open Material M_Landscape and add Feature Level Switch"
```

## 📦 Installation

```bash
git clone https://github.com/YOUR_USERNAME/vera
cd vera
pip install -e ".[dev]"
cp .env.example .env
# Add your GEMINI_API_KEY to .env
```

## 🔧 Configuration

```yaml
# vera.config.yaml
llm:
  provider: gemini
  model: gemini-2.0-flash  # Use flash for minimum token cost
  vision_model: gemini-2.0-flash

perception:
  prefer_local_ocr: true       # Always try OCR before LLM
  screenshot_quality: 70       # Lower = fewer tokens when Vision is needed
  roi_detection: true          # Crop to relevant UI region only

cache:
  coord_registry: true         # Cache UI element positions
  action_cache: true           # Cache completed workflows
  embedding_model: local       # Use local sentence-transformers
```

## 🧠 Built-in Recipes

| Recipe | Command |
|--------|---------|
| Android Setup | `vera "setup android build"` |
| Map Config | `vera "set default map to [MapName]"` |
| Material Fix | `vera "fix sampler limit on [MaterialName]"` |
| Launch Device | `vera "launch on connected Android device"` |
| Package Build | `vera "package shipping build for Android"` |

## 🤝 Contributing

Contributions are welcome! Especially:
- **New recipes** for common UE5 workflows
- **UI coordinate mappings** for UE5 panels
- **OCR improvements** for better local detection

## 📄 License

MIT — Free for personal and commercial use.

---

*Built with ❤️ for the Unreal Engine community.*
