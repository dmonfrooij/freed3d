# FREE3D — Image to 3D Pipeline

Convert a single image to a printable 3D model (STL, 3MF, GLB) using [TripoSR](https://github.com/VAST-AI-Research/TripoSR) running locally on your GPU.

## Features

- 🖼️ Upload any image → get a 3D model in seconds
- 🎯 Automatic background removal
- 📐 Adjustable mesh resolution (256 → 1024)
- 🖨️ Export to STL, 3MF and GLB
- 🔧 Post-processing: smoothing, hole filling, mesh repair
- 💻 Runs 100% locally — no cloud, no API keys

## Requirements

- **Python 3.11** — [Download](https://www.python.org/downloads/release/python-3119/)
  - During install: uncheck "Add to PATH" if you have another Python version
- **Git** — [Download](https://git-scm.com/download/win)
- **NVIDIA GPU** with 6+ GB VRAM + up-to-date CUDA drivers
- Windows 10/11 64-bit

## Installation

```powershell
git clone https://github.com/dmonfrooij/free3d.git
cd free3d

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

The installer will:
1. Create a Python 3.11 virtual environment
2. Install PyTorch 2.4.0 + CUDA 11.8
3. Clone and patch TripoSR
4. Install all dependencies
5. Pin NumPy 1.26.4 for compatibility

## Usage

```powershell
.\start.ps1
```

Browser opens automatically at `http://localhost:8000`

1. Drop an image (JPG, PNG, WEBP)
2. Choose background mode and mesh resolution
3. Click **GENEREER 3D MODEL**
4. Download STL / 3MF / GLB when done

## Tips for best results

- Use images with a **plain background** (white/grey works best)
- Object should be **fully visible** and well-lit
- **Front-facing** objects work better than top-down views
- Minimum **512×512** pixels recommended

## Resolution guide

| Resolution | VRAM needed | Time (RTX 3080 Ti) | Quality   |
|------------|-------------|---------------------|-----------|
| 256        | ~4 GB       | ~30 sec             | Good      |
| 384        | ~7 GB       | ~2 min              | Great     |
| 512        | ~11 GB      | ~15 min             | Excellent |
| 640+       | 16+ GB      | Very long           | Extreme   |

## Project structure

```
free3d/
├── backend/
│   └── main.py        # FastAPI server + TripoSR pipeline
├── frontend/
│   └── index.html     # Web UI
├── install.ps1        # One-click installer
├── start.ps1          # Start the app
└── README.md
```

## Credits

- [TripoSR](https://github.com/VAST-AI-Research/TripoSR) by VAST AI Research & Stability AI
- [transparent-background](https://github.com/plemeri/transparent-background) for background removal

## License

MIT
