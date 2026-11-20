@echo off
setlocal
cd /d "%~dp0"

REM Activate a local virtualenv if one exists. If you build inside a conda
REM env such as build310, run this .bat from that already-activated env.
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat

REM Clean stale artifacts from a previous PyArmor 7 build.
if exist dist\obf rmdir /s /q dist\obf
if exist BrainLead.spec del /q BrainLead.spec
if exist BrainLead.patched.spec del /q BrainLead.patched.spec

REM 1) Frontend - only if not already built or synced from the Linux box.
if exist frontend\dist\index.html (
    echo [1/3] Frontend already built - skipping npm build.
) else (
    echo [1/3] Building React frontend...
    cd frontend
    call npm install
    if errorlevel 1 goto :fail
    call npm run build
    if errorlevel 1 goto :fail
    cd ..
)

REM 2) Generate a PyInstaller spec carrying all bundling options. PyArmor 9
REM    then obfuscates the scripts and packs them via this spec.
echo [2/3] Generating PyInstaller spec (PyArmor 9 plus PyInstaller)...
python -m pyarmor.cli -v
pyi-makespec --onefile --noconsole --name BrainLead --add-data "frontend/dist;frontend/dist" --hidden-import backend.licensing --hidden-import multipart --collect-all curl_cffi launcher.py
if errorlevel 1 goto :fail

REM 3) Obfuscate with PyArmor 9 and bundle into a single EXE.
REM    -r launcher.py backend recursively obfuscates the entry point plus backend.
echo [3/3] Obfuscating with PyArmor 9 and bundling into BrainLead.exe...
python -m pyarmor.cli gen --pack BrainLead.spec -r launcher.py backend
if errorlevel 1 goto :fail

echo.
echo Build complete. The EXE is in dist\BrainLead.exe
goto :done

:fail
echo.
echo Build failed. See errors above.
pause
exit /b 1

:done
pause
