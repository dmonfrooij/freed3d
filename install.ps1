# FREE3D - Installatie
# Gebruik: rechterklik > "Run with PowerShell"
Set-Location $PSScriptRoot
$ErrorActionPreference = "Continue"

function Step($m) { Write-Host "`n== $m ==" -ForegroundColor Cyan }
function OK($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Fail($m) { Write-Host "[FOUT] $m" -ForegroundColor Red; Read-Host; exit 1 }

Write-Host "FREE3D - Image to 3D Pipeline" -ForegroundColor Yellow

# Python 3.11
Step "Python 3.11 zoeken"
$py = $null
@(
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "C:\Python311\python.exe",
    "C:\Program Files\Python311\python.exe"
) | ForEach-Object { if ((Test-Path $_) -and -not $py) { $py = $_ } }
if (-not $py) { try { py -3.11 --version 2>$null | Out-Null; $py = "py -3.11" } catch {} }
if (-not $py) { Fail "Python 3.11 niet gevonden. Download: https://www.python.org/downloads/release/python-3119/" }
OK $py

# Venv
Step "Schone venv aanmaken"
if (Test-Path "venv") { Remove-Item -Recurse -Force "venv" }
& $py -m venv venv
if (-not (Test-Path "venv\Scripts\python.exe")) { Fail "venv aanmaken mislukt" }
$PY = ".\venv\Scripts\python.exe"
& $PY -m pip install --upgrade pip setuptools wheel -q
OK "venv klaar"

# PyTorch
Step "PyTorch 2.4.0 + CUDA 11.8 (~2.5 GB)"
& $PY -m pip install "torch==2.4.0+cu118" "torchvision==0.19.0+cu118" "torchaudio==2.4.0+cu118" --index-url https://download.pytorch.org/whl/cu118 -q
OK "PyTorch geinstalleerd"

# Overige dependencies
Step "Alle dependencies installeren"
& $PY -m pip install "omegaconf>=2.3" "einops" "trimesh[easy]" "Pillow" "huggingface_hub" "transformers>=4.35" "accelerate" "imageio" "scipy" "PyMCubes" "httpx" "onnxruntime" "fastapi==0.115.5" "uvicorn[standard]==0.32.1" "python-multipart==0.0.12" "pydantic==2.9.2" -q
OK "Dependencies geinstalleerd"

# transparent-background optioneel
Step "transparent-background (optioneel)"
& $PY -m pip install "transparent-background" -q 2>&1 | Out-Null
OK "transparent-background geinstalleerd (of overgeslagen)"

# NumPy 1.26 ALS LAATSTE
Step "NumPy 1.26 pinnen (als laatste stap)"
& $PY -m pip install "numpy==1.26.4" --force-reinstall -q
OK "NumPy 1.26.4 gepind"

# TripoSR ophalen
Step "TripoSR ophalen"
if (Test-Path "triposr_repo") { Remove-Item -Recurse -Force "triposr_repo" }
git clone --quiet https://github.com/VAST-AI-Research/TripoSR.git triposr_repo
if (-not (Test-Path "triposr_repo\tsr")) { Fail "Git clone mislukt. Is git geinstalleerd?" }
if (Test-Path "backend\tsr") { Remove-Item -Recurse -Force "backend\tsr" }
Copy-Item -Recurse "triposr_repo\tsr" "backend\tsr"
OK "TripoSR gekopieerd"

# Patches
Step "TripoSR broncode patchen"
& $PY -c @"
import re, ast, sys

p = 'backend/tsr/utils.py'
txt = open(p, encoding='utf-8').read()
txt = txt.replace(
    'image = torch.from_numpy(np.array(image).astype(np.float32) / 255.0)',
    'image = torch.tensor(np.array(image).astype(np.float32) / 255.0)'
)
txt = re.sub(r'^import rembg\s*$', '# rembg removed', txt, flags=re.MULTILINE)
txt = re.sub(r'from rembg import remove', 'try:\n    from rembg import remove\nexcept ImportError:\n    def remove(img, **kw): return img', txt)
txt = re.sub(r'rembg\.remove\(([^)]+)\)', r'remove(\1)', txt)
ast.parse(txt)
open(p, 'w', encoding='utf-8').write(txt)
print('[OK] utils.py gepatcht')

p2 = 'backend/tsr/models/isosurface.py'
txt2 = open(p2, encoding='utf-8').read()
old = 'from torchmcubes import marching_cubes'
new = 'try:\n    from torchmcubes import marching_cubes\nexcept ImportError:\n    import mcubes as _mc\n    import torch as _t\n    import numpy as _np\n    def marching_cubes(vol, threshold):\n        v, f = _mc.marching_cubes(vol.cpu().numpy(), float(threshold))\n        return _t.tensor(v.astype(_np.float32)), _t.tensor(f.astype(_np.int64))\n'
if old in txt2:
    txt2 = txt2.replace(old, new)
    ast.parse(txt2)
    open(p2, 'w', encoding='utf-8').write(txt2)
    print('[OK] isosurface.py gepatcht')
else:
    print('[!] isosurface.py al gepatcht')

sys.path.insert(0, 'backend')
from tsr.system import TSR
print('[OK] TSR importeerbaar!')
"@
if ($LASTEXITCODE -ne 0) { Fail "Patches mislukt" }

# Finale test
Step "Finale test"
& $PY -c @"
import sys
sys.path.insert(0, 'backend')
import numpy as np
import torch
print(f'numpy {np.__version__}')
print(f'torch {torch.__version__} | CUDA: {torch.cuda.is_available()}')
if torch.cuda.is_available(): print(f'GPU: {torch.cuda.get_device_name(0)}')
arr = np.zeros((4,4), dtype=np.float32)
t = torch.tensor(arr)
print(f'[OK] numpy->torch werkt: {t.shape}')
from tsr.system import TSR
print('[OK] Alles klaar!')
"@

Write-Host "`n=============================" -ForegroundColor Green
Write-Host " Installatie voltooid!" -ForegroundColor Green
Write-Host " Start met: .\start.ps1" -ForegroundColor Green
Write-Host "=============================" -ForegroundColor Green
Read-Host "Druk Enter"
