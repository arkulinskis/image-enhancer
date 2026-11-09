@echo off
rem Image Enhancer worker: keeps this PC connected to the app and paints the pictures it sends.
rem   start_worker.bat                 ComfyUI + FLUX.2 [klein] 4B (run setup_comfyui.ps1 once first)
rem   start_worker.bat --backend classic   built-in test filters, no GPU needed
rem   start_worker.bat --new-key           paste the Uplink key again (if Anvil says it's wrong)
rem Close this window (or press Ctrl+C) to stop.
title Image Enhancer worker
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run
echo The worker's Python environment isn't set up yet. Setting up a small one now (anvil-uplink + Pillow)...
where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
if not exist ".venv\Scripts\python.exe" (
  echo Couldn't make a Python environment. Install Python from python.org, or run setup_comfyui.ps1.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
:run
".venv\Scripts\python.exe" enhancer_worker.py %*
echo.
echo The worker stopped.
pause
