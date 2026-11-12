#!/usr/bin/env bash
# Image Enhancer worker: one-click install on Ubuntu (22.04 to 26.04, Python 3.10 to 3.14).
# Works with an NVIDIA card (CUDA) or an AMD Radeon card (ROCm, e.g. RX 6700 XT); the Intel graphics
# built into the processor are ignored.
# Installs ComfyUI + FLUX.2 [klein] 4B next to this script, the worker's own Python packages,
# and an "Image Enhancer worker" icon in the app menu and on the desktop.
# Safe to run again: it updates ComfyUI, swaps PyTorch if the graphics card changed, and skips
# model files that are already complete.
#
# Double-click: right-click this file -> Properties -> turn on "Executable as Program",
#               then right-click -> "Run as a Program".
# Or in a terminal:  bash install_ubuntu.sh

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

# Started from the Files app there's no window to show progress or ask questions: reopen in a terminal.
if [ ! -t 0 ] || [ ! -t 1 ]; then
    for t in ptyxis gnome-terminal kgx konsole xfce4-terminal x-terminal-emulator xterm; do
        if command -v "$t" >/dev/null 2>&1; then
            case "$t" in
                ptyxis|kgx|gnome-terminal) exec "$t" -- bash "$HERE/install_ubuntu.sh" "$@" ;;
                *) exec "$t" -e bash "$HERE/install_ubuntu.sh" "$@" ;;
            esac
        fi
    done
    exit 1
fi

COMFY="$HERE/ComfyUI"
cd "$HERE" || exit 1

say()  { echo; echo -e "\e[36m== $1\e[0m"; }
fail() { echo; echo -e "\e[31mPROBLEM: $1\e[0m"; read -rp "Press Enter to close" _; exit 1; }

# ---------------------------------------------------------------- 1. tools
say "Checking Python, Git, curl and the graphics card"
NEED=()
command -v git  >/dev/null 2>&1 || NEED+=(git)
command -v curl >/dev/null 2>&1 || NEED+=(curl)

PY=""
for c in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,14)" 2>/dev/null; then
        PY="$c"; break
    fi
done
[ -n "$PY" ] || fail "Python 3.10 to 3.14 wasn't found. On Ubuntu 22.04+ it comes built in; try: sudo apt install python3"
PYV="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
# Ubuntu leaves out venv/pip by default
"$PY" -c "import venv, ensurepip" 2>/dev/null || NEED+=("python${PYV}-venv" python3-pip)

# Which graphics card: NVIDIA (vendor 0x10de) or AMD (0x1002). Intel's built-in graphics (0x8086) don't count.
GPU_KIND=""
for v in /sys/class/drm/card[0-9]*/device/vendor; do
    [ -f "$v" ] || continue
    case "$(cat "$v")" in
        0x10de) GPU_KIND=nvidia; break ;;
        0x1002) GPU_KIND=amd ;;
    esac
done
[ "$GPU_KIND" = amd ] && ! command -v lspci >/dev/null 2>&1 && NEED+=(pciutils)

if [ ${#NEED[@]} -gt 0 ]; then
    echo "Installing: ${NEED[*]} (Ubuntu will ask for your password)"
    sudo apt-get update && sudo apt-get install -y "${NEED[@]}" || fail "Couldn't install ${NEED[*]}."
fi
echo "Python: $("$PY" -c 'import sys; print(sys.version.split()[0])')"

RELOGIN=""
if [ "$GPU_KIND" = nvidia ]; then
    GPU="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -n1)"
    if [ -n "$GPU" ]; then
        echo "Graphics card: $GPU"
    else
        echo -e "\e[33mNVIDIA card found but no NVIDIA driver (nvidia-smi). Install it first: open 'Software & Updates' -> 'Additional Drivers'"
        echo -e "and pick the recommended NVIDIA driver (or run: sudo ubuntu-drivers install), restart, then run this again.\e[0m"
        read -rp "Carry on anyway? The model won't run without it (y/N) " ans
        [[ "$ans" =~ ^[Yy] ]] || exit 1
    fi
elif [ "$GPU_KIND" = amd ]; then
    GPU="$(lspci 2>/dev/null | grep -iE 'vga|display|3d' | grep -iE 'amd|ati' | head -n1 | sed 's/^[^:]*: //')"
    GPU="${GPU:-AMD Radeon}"
    echo "Graphics card: $GPU"
    # Ubuntu's own kernel driver (amdgpu) is all that's needed: the AMD PyTorch brings the rest of ROCm with it.
    [ -e /dev/kfd ] || fail "The AMD compute device (/dev/kfd) is missing. Update Ubuntu (sudo apt full-upgrade), restart, then run this again."
    if [ ! -r /dev/kfd ] || [ ! -w /dev/kfd ]; then
        echo "Giving your account access to the graphics card for computing (groups 'render' and 'video')."
        sudo usermod -aG render,video "$USER" || fail "Couldn't add you to the 'render' group."
        RELOGIN=1   # a group only takes effect at the next login; until then the test runs through 'sg render'
    fi
else
    echo -e "\e[33mNo NVIDIA or AMD graphics card found. For NVIDIA, install the driver first ('Software & Updates' ->"
    echo -e "'Additional Drivers'); AMD cards work with Ubuntu's built-in driver.\e[0m"
    read -rp "Carry on anyway? The model won't run without one (y/N) " ans
    [[ "$ans" =~ ^[Yy] ]] || exit 1
    GPU_KIND=nvidia
fi

# ---------------------------------------------------------------- 2. ComfyUI
if [ -f "$COMFY/main.py" ]; then
    say "Updating ComfyUI"
    git -C "$COMFY" pull --ff-only || echo "(couldn't update ComfyUI; carrying on with the copy that's here)"
else
    say "Downloading ComfyUI"
    git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFY" || fail "git clone failed."
fi

VPY="$COMFY/venv/bin/python"
# A venv copied from another computer (or Windows) doesn't work here: make a fresh one.
# Same for one made with another Python version (e.g. copied from a PC with an older Ubuntu).
if [ -d "$COMFY/venv" ] && ! "$VPY" -c "import sys; assert '%d.%d' % sys.version_info[:2] == '$PYV'" >/dev/null 2>&1; then
    rm -rf "$COMFY/venv"
fi
if [ ! -x "$VPY" ]; then
    say "Making ComfyUI's own Python environment"
    "$PY" -m venv "$COMFY/venv" || fail "Couldn't make ComfyUI's Python environment."
fi
"$VPY" -m pip install --upgrade pip
TORCH=(torch torchvision torchaudio)
# pip would keep a PyTorch built for the other card maker (e.g. copied from the NVIDIA PC): take it out first.
HAS_HIP="$("$VPY" -c "import torch; print('yes' if torch.version.hip else 'no')" 2>/dev/null)"
if [ "$GPU_KIND" = amd ]; then
    say "Installing PyTorch for AMD (ROCm) and ComfyUI's packages (a few GB the first time)"
    [ "$HAS_HIP" = no ] && "$VPY" -m pip uninstall -y "${TORCH[@]}"
    TORCH_OK=""
    for rocm in rocm7.2 rocm6.4; do
        "$VPY" -m pip install --upgrade "${TORCH[@]}" --index-url "https://download.pytorch.org/whl/$rocm" && { TORCH_OK=1; break; }
        echo "(PyTorch for $rocm didn't install; trying an older ROCm)"
    done
    [ -n "$TORCH_OK" ] || fail "Installing PyTorch for AMD failed (see above)."
else
    say "Installing PyTorch for NVIDIA (CUDA 12.8) and ComfyUI's packages (a few GB the first time)"
    [ "$HAS_HIP" = yes ] && "$VPY" -m pip uninstall -y "${TORCH[@]}"
    "$VPY" -m pip install --upgrade "${TORCH[@]}" --index-url https://download.pytorch.org/whl/cu128 \
        || fail "Installing PyTorch failed (see above)."
fi
if ! "$VPY" -m pip install -r "$COMFY/requirements.txt"; then
    # On a brand-new Python a package may have no ready-made build yet: get the tools to build it, then retry.
    echo "Getting the build tools some packages need, then trying again (Ubuntu may ask for your password)"
    sudo apt-get install -y build-essential cmake pkg-config "python${PYV}-dev" \
        && "$VPY" -m pip install -r "$COMFY/requirements.txt" || fail "Installing ComfyUI's packages failed (see above)."
fi

# gpu.env: settings the graphics card needs; start_worker.sh loads it and ComfyUI inherits it from the worker.
# Runs ComfyUI's Python with graphics card access (through 'sg render' until the next login gives the group).
gpu_py() {
    if [ -n "$RELOGIN" ]; then sg render -c "$(printf '%q ' "$VPY" "$@")"; else "$VPY" "$@"; fi
}
rm -f "$HERE/gpu.env"
if [ "$GPU_KIND" = amd ]; then
    ARCH="$(gpu_py -c "import torch; print(torch.cuda.get_device_properties(0).gcnArchName.split(':')[0])" 2>/dev/null)"
    echo "AMD chip: ${ARCH:-(not readable yet)}"
    {
        echo "# Made by install_ubuntu.sh for this PC's AMD card ($GPU). Run the installer again if the card changes."
        case "$ARCH" in
            # RX 6700/6600/6500 (RDNA2) aren't on ROCm's list but run fine as their big brother, the RX 6800 (gfx1030)
            gfx1031|gfx1032|gfx1033|gfx1034|gfx1035|gfx1036|"") echo "export HSA_OVERRIDE_GFX_VERSION=10.3.0" ;;
            gfx1102|gfx1103) echo "export HSA_OVERRIDE_GFX_VERSION=11.0.0" ;;
        esac
        echo "export MIOPEN_FIND_MODE=FAST   # skips minutes of tuning the first time each picture size is used"
    } > "$HERE/gpu.env"
    . "$HERE/gpu.env"
fi

GPU_TEST="import torch
ok = torch.cuda.is_available()
print('PyTorch', torch.__version__, '| graphics card available:', ok)
assert ok, 'PyTorch cannot see the graphics card'
p = torch.cuda.get_device_properties(0)
x = torch.randn(1024, 1024, device='cuda', dtype=torch.float16)
(x @ x).sum().item()
print('Using: %s, %.1f GB' % (p.name, p.total_memory / 2**30))"
gpu_py -c "$GPU_TEST" || fail "PyTorch can't use the graphics card (see above)."

# ---------------------------------------------------------------- 3. the model (FLUX.2 [klein] 4B, Apache 2.0)
say "Downloading FLUX.2 [klein] 4B (about 12.5 GB; resumes if interrupted)"
get_model() {  # dir file size url
    local dir="$COMFY/models/$1" dest="$COMFY/models/$1/$2"
    mkdir -p "$dir"
    if [ -f "$dest" ] && [ "$(stat -c %s "$dest")" = "$3" ]; then echo "Already here: $2"; return; fi
    echo "Downloading $2 ..."
    curl -L --fail --retry 5 --retry-delay 5 -C - -o "$dest" "$4"
    local rc=$?
    [ $rc -eq 0 ] || [ $rc -eq 33 ] || fail "Downloading $2 failed. Run this again to resume."
    [ "$(stat -c %s "$dest")" = "$3" ] || fail "$2 is incomplete. Run this again to resume."
}
get_model diffusion_models flux-2-klein-4b-fp8.safetensors 4070624520 \
    "https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8/resolve/main/flux-2-klein-4b-fp8.safetensors"
get_model text_encoders qwen_3_4b.safetensors 8044982048 \
    "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors"
get_model vae flux2-vae.safetensors 336213556 \
    "https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors"

# ---------------------------------------------------------------- 4. the worker's own environment
say "Installing the worker's packages (anvil-uplink, Pillow)"
WPY="$HERE/.venv/bin/python"
if [ -d "$HERE/.venv" ] && ! "$WPY" -c "import sys" >/dev/null 2>&1; then rm -rf "$HERE/.venv"; fi
[ -x "$WPY" ] || "$PY" -m venv "$HERE/.venv" || fail "Couldn't make the worker's Python environment."
"$WPY" -m pip install --upgrade pip
"$WPY" -m pip install -r "$HERE/requirements.txt" || fail "Installing the worker's packages failed."

# ---------------------------------------------------------------- 5. check
if [ -n "$RELOGIN" ]; then
    say "Skipping the ComfyUI check until you log in again (graphics card access needs a new login)"
else
    say "Checking that ComfyUI starts and finds the model (this loads ComfyUI once)"
    "$WPY" "$HERE/enhancer_worker.py" --check || fail "The check found a problem (see above). worker/comfyui.log has ComfyUI's own messages."
fi

# ---------------------------------------------------------------- 6. icons
say "Adding an 'Image Enhancer worker' icon to the app menu and the desktop"
chmod +x "$HERE/start_worker.sh" "$HERE/install_ubuntu.sh"
LAUNCHER="[Desktop Entry]
Type=Application
Name=Image Enhancer worker
Comment=Connects this PC to Image Enhancer and paints the pictures it sends
Exec=\"$HERE/start_worker.sh\"
Path=$HERE
Icon=applications-graphics
Terminal=true
Categories=Graphics;"
mkdir -p "$HOME/.local/share/applications"
echo "$LAUNCHER" > "$HOME/.local/share/applications/image-enhancer-worker.desktop"
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESK" ]; then
    echo "$LAUNCHER" > "$DESK/image-enhancer-worker.desktop"
    chmod +x "$DESK/image-enhancer-worker.desktop"
    gio set "$DESK/image-enhancer-worker.desktop" metadata::trusted true 2>/dev/null
fi

read -rp "Start the worker automatically when you log in? (y/N) " ans
if [[ "$ans" =~ ^[Yy] ]]; then
    mkdir -p "$HOME/.config/autostart"
    echo "$LAUNCHER" > "$HOME/.config/autostart/image-enhancer-worker.desktop"
    echo "Done: it will open in a terminal window each time you log in."
fi

echo
if [ -f "$HERE/config.json" ] && grep -q '"server_' "$HERE/config.json"; then
    echo -e "\e[32mAll set. The Uplink key copied over in config.json will be used.\e[0m"
else
    echo -e "\e[32mAll set. When the worker starts it asks once for the app's SERVER Uplink key.\e[0m"
fi
echo "Turn the worker OFF on the other PC first (only one PC should be connected at a time)."
if [ -n "$RELOGIN" ]; then
    echo -e "\e[33mOne more step: restart the PC (or log out and back in) so your account can use the graphics card,"
    echo -e "then run install_ubuntu.sh once more. It goes quickly the second time: just the check, then it starts the worker.\e[0m"
    read -rp "Press Enter to close" _
    exit 0
fi
read -rp "Start the worker now? (Y/n) " ans
[[ "$ans" =~ ^[Nn] ]] || exec "$HERE/start_worker.sh"
