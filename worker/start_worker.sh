#!/usr/bin/env bash
# Image Enhancer worker (Ubuntu/Linux): keeps this PC connected to the app and paints the pictures it sends.
#   ./start_worker.sh                    ComfyUI + FLUX.2 [klein] 4B (run install_ubuntu.sh once first)
#   ./start_worker.sh --backend classic  built-in test filters, no GPU needed
#   ./start_worker.sh --new-key          paste the Uplink key again (if Anvil says it's wrong)
# Close the window (or press Ctrl+C) to stop.

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

if [ ! -t 0 ] || [ ! -t 1 ]; then
    for t in ptyxis gnome-terminal kgx konsole xfce4-terminal x-terminal-emulator xterm; do
        if command -v "$t" >/dev/null 2>&1; then
            case "$t" in
                ptyxis|kgx|gnome-terminal) exec "$t" -- bash "$HERE/start_worker.sh" "$@" ;;
                *) exec "$t" -e bash "$HERE/start_worker.sh" "$@" ;;
            esac
        fi
    done
fi

cd "$HERE" || exit 1
printf '\e]0;Image Enhancer worker\a'
if [ ! -x ".venv/bin/python" ]; then
    echo "The worker isn't installed on this PC yet. Run install_ubuntu.sh first."
    read -rp "Press Enter to close" _
    exit 1
fi
".venv/bin/python" enhancer_worker.py "$@"
echo
echo "The worker stopped."
read -rp "Press Enter to close" _
