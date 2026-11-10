#!/usr/bin/env bash
# Image Enhancer worker: one-click install on Ubuntu (22.04 or newer).
# Installs ComfyUI + FLUX.2 [klein] 4B next to this script, the worker's own Python packages,
# and an "Image Enhancer worker" icon in the app menu and on the desktop.
# Safe to run again: it updates ComfyUI and skips model files that are already complete.
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
for c in python3 python3.12 python3.11 python3.10 python3.13; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,13)" 2>/dev/null; then
        PY="$c"; break
    fi
done
[ -n "$PY" ] || fail "Python 3.10 to 3.13 wasn't found. On Ubuntu 22.04+ it comes built in; try: sudo apt install python3"
PYV="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
# Ubuntu leaves out venv/pip by default
"$PY" -c "import venv, ensurepip" 2>/dev/null || NEED+=("python${PYV}-venv" python3-pip)

if [ ${#NEED[@]} -gt 0 ]; then
    echo "Installing: ${NEED[*]} (Ubuntu will ask for your password)"
    sudo apt-get update && sudo apt-get install -y "${NEED[@]}" || fail "Couldn't install ${NEED[*]}."
fi
echo "Python: $("$PY" -c 'import sys; print(sys.version.split()[0])')"

GPU="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -n1)"
if [ -n "$GPU" ]; then
    echo "Graphics card: $GPU"
else
    echo -e "\e[33mNo NVIDIA driver found (nvidia-smi). Install it first: open 'Software & Updates' -> 'Additional Drivers'"
    echo -e "and pick the recommended NVIDIA driver (or run: sudo ubuntu-drivers install), restart, then run this again.\e[0m"
    read -rp "Carry on anyway? The model won't run without it (y/N) " ans
    [[ "$ans" =~ ^[Yy] ]] || exit 1
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
if [ -d "$COMFY/venv" ] && ! "$VPY" -c "import sys" >/dev/null 2>&1; then rm -rf "$COMFY/venv"; fi
if [ ! -x "$VPY" ]; then
    say "Making ComfyUI's own Python environment"
    "$PY" -m venv "$COMFY/venv" || fail "Couldn't make ComfyUI's Python environment."
fi
say "Installing PyTorch for NVIDIA (CUDA 12.8) and ComfyUI's packages (a few GB the first time)"
"$VPY" -m pip install --upgrade pip
"$VPY" -m pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 \
    || fail "Installing PyTorch failed (see above)."
"$VPY" -m pip install -r "$COMFY/requirements.txt" || fail "Installing ComfyUI's packages failed (see above)."
"$VPY" -c "import torch; print('PyTorch', torch.__version__, '| CUDA available:', torch.cuda.is_available())"

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
say "Checking that ComfyUI starts and finds the model (this loads ComfyUI once)"
"$WPY" "$HERE/enhancer_worker.py" --check || fail "The check found a problem (see above). worker/comfyui.log has ComfyUI's own messages."

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
read -rp "Start the worker now? (Y/n) " ans
[[ "$ans" =~ ^[Nn] ]] || exec "$HERE/start_worker.sh"
