# Image Enhancer: install ComfyUI + FLUX.2 [klein] 4B next to the worker, and the worker's own Python packages.
# Right-click -> Run with PowerShell, or:  powershell -ExecutionPolicy Bypass -File setup_comfyui.ps1
# Safe to run again: it updates ComfyUI and skips model files that are already complete.
# Needs: Windows 10/11, an NVIDIA card (8 GB+), Python 3.10-3.13 (python.org), Git (git-scm.com), ~15 GB free disk.

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Comfy = Join-Path $Here "ComfyUI"
Set-Location $Here

function Say($msg) { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "PROBLEM: $msg" -ForegroundColor Red; Read-Host "Press Enter to close"; exit 1 }

# ---------------------------------------------------------------- 1. tools
Say "Checking Python, Git and the graphics card"
$PyExe = $null
$PyArgs = @()
foreach ($v in @("3.12", "3.11", "3.10", "3.13")) {
    try { & py "-$v" -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { $PyExe = "py"; $PyArgs = @("-$v"); break } } catch {}
}
if (-not $PyExe) {
    try { & python -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,13)" 2>$null; if ($LASTEXITCODE -eq 0) { $PyExe = "python" } } catch {}
}
if (-not $PyExe) { Fail "Python 3.10 to 3.13 wasn't found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again." }
Write-Host ("Python: " + (& $PyExe @PyArgs -c "import sys; print(sys.version.split()[0])"))
try { git --version | Out-Null } catch { Fail "Git wasn't found. Install it from https://git-scm.com/download/win, then run this again." }
$Gpu = ""
try { $Gpu = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null | Select-Object -First 1) } catch {}
if ($Gpu) { Write-Host "Graphics card: $Gpu" } else { Write-Host "No NVIDIA card found (nvidia-smi). ComfyUI will be very slow or fail; the worker's 'classic' test engine still works." -ForegroundColor Yellow }

# ---------------------------------------------------------------- 2. ComfyUI
if (Test-Path (Join-Path $Comfy "main.py")) {
    Say "Updating ComfyUI"
    git -C $Comfy pull --ff-only
} else {
    Say "Downloading ComfyUI"
    git clone https://github.com/comfyanonymous/ComfyUI.git $Comfy
    if ($LASTEXITCODE -ne 0) { Fail "git clone failed." }
}

$Venv = Join-Path $Comfy "venv"
$VPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VPy)) {
    Say "Making ComfyUI's own Python environment"
    & $PyExe @PyArgs -m venv $Venv
}
Say "Installing PyTorch for NVIDIA (CUDA 12.8) and ComfyUI's packages (a few GB the first time)"
& $VPy -m pip install --upgrade pip
& $VPy -m pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { Fail "Installing PyTorch failed (see above)." }
& $VPy -m pip install -r (Join-Path $Comfy "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "Installing ComfyUI's packages failed (see above)." }
& $VPy -c "import torch; print('PyTorch', torch.__version__, '| CUDA available:', torch.cuda.is_available())"

# ---------------------------------------------------------------- 3. the model (FLUX.2 [klein] 4B, Apache 2.0)
Say "Downloading FLUX.2 [klein] 4B (about 12.5 GB; resumes if interrupted)"
$Models = @(
    @{ Dir = "diffusion_models"; File = "flux-2-klein-4b-fp8.safetensors"; Size = 4070624520;
       Url = "https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8/resolve/main/flux-2-klein-4b-fp8.safetensors" },
    @{ Dir = "text_encoders"; File = "qwen_3_4b.safetensors"; Size = 8044982048;
       Url = "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors" },
    @{ Dir = "vae"; File = "flux2-vae.safetensors"; Size = 336213556;
       Url = "https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors" }
)
foreach ($m in $Models) {
    $dir = Join-Path $Comfy ("models\" + $m.Dir)
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $dest = Join-Path $dir $m.File
    if ((Test-Path $dest) -and ((Get-Item $dest).Length -eq $m.Size)) { Write-Host "Already here: $($m.File)"; continue }
    Write-Host "Downloading $($m.File) ..."
    & curl.exe -L --fail --retry 5 --retry-delay 5 -C - -o $dest $m.Url
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 33) { Fail "Downloading $($m.File) failed. Run this script again to resume." }
    if ((Get-Item $dest).Length -ne $m.Size) { Fail "$($m.File) is incomplete. Run this script again to resume." }
}

# ---------------------------------------------------------------- 4. the worker's own environment
Say "Installing the worker's packages (anvil-uplink, Pillow)"
$WVenv = Join-Path $Here ".venv"
$WPy = Join-Path $WVenv "Scripts\python.exe"
if (-not (Test-Path $WPy)) { & $PyExe @PyArgs -m venv $WVenv }
& $WPy -m pip install --upgrade pip
& $WPy -m pip install -r (Join-Path $Here "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "Installing the worker's packages failed." }

# ---------------------------------------------------------------- 5. check
Say "Checking that ComfyUI starts and finds the model (this loads ComfyUI once)"
& $WPy (Join-Path $Here "enhancer_worker.py") --check
if ($LASTEXITCODE -ne 0) { Fail "The check found a problem (see above). worker\comfyui.log has ComfyUI's own messages." }

Write-Host ""
Write-Host "All set. Next: double-click start_worker.bat and paste the app's SERVER Uplink key when it asks." -ForegroundColor Green
Read-Host "Press Enter to close"
