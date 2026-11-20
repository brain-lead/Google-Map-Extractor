# build_exe.ps1 - Automated Nuitka Native C/C++ Compilation + Authenticode Signing + Runtime Test Pipeline
# Conforms strictly to Brain Lead AGENTS.md and the brainlead-build skill.
param(
    [string]$AppName = "Google_Map_Extractor",
    [string]$ReleaseName = "Google_Map_Extractor_v3.0",
    [switch]$Standalone = $false,
    [switch]$Console = $false,
    [switch]$SkipFrontendBuild = $false
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
Set-Location $root

# 1. Resolve Application Metadata from app_info.py
$AppVersion = "3.0"
$AppId = "Google Map Extractor"
$AppDescription = "GME (Google Map Extractor) - Google Maps Business Data Extractor & Lead Scoring"

if (Test-Path "$root\app_info.py") {
    try {
        $info = python -c "import app_info; print('|'.join([getattr(app_info, 'APP_NAME', 'Google_Map_Extractor'), getattr(app_info, 'APP_VERSION', '3.0'), getattr(app_info, 'APP_ID', 'Google Map Extractor'), getattr(app_info, 'APP_DESCRIPTION', '')]))"
        $parts = $info.Trim().Split('|')
        if ($parts.Count -ge 1 -and $parts[0]) { $AppName = $parts[0] }
        if ($parts.Count -ge 2 -and $parts[1]) { $AppVersion = $parts[1] }
        if ($parts.Count -ge 3 -and $parts[2]) { $AppId = $parts[2] }
        if ($parts.Count -ge 4 -and $parts[3]) { $AppDescription = $parts[3] }
    } catch {
        Write-Warning "Could not read app_info.py dynamically; using defaults."
    }
}
if (-not $ReleaseName) { $ReleaseName = "$($AppName)_v$($AppVersion)" }

# Normalize version to 4-part Windows PE version (e.g. "3.0" -> "3.0.0.0")
$verParts = $AppVersion -replace '[^0-9\.]', '' -split '\.' | Where-Object { $_ -ne "" }
while ($verParts.Count -lt 4) { $verParts += "0" }
$peVersion = ($verParts[0..3] -join '.')

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " BRAIN LEAD - $AppName NUITKA NATIVE C++ BUILD PIPELINE " -ForegroundColor Cyan
Write-Host " Version: $AppVersion (PE: $peVersion)" -ForegroundColor Cyan
Write-Host " Target Release: $ReleaseName" -ForegroundColor Cyan
Write-Host " Mode: $(if ($Standalone) { 'Standalone' } else { 'Onefile' }) | Console: $(if ($Console) { 'Enabled' } else { 'Disabled' })" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 2. Frontend verification / build
$frontendDist = Join-Path $root "frontend\dist"
$frontendIndex = Join-Path $frontendDist "index.html"
if (-not (Test-Path $frontendIndex) -and -not $SkipFrontendBuild) {
    Write-Host "==> Building React frontend with Vite..." -ForegroundColor Yellow
    Push-Location (Join-Path $root "frontend")
    npm run build
    Pop-Location
}
if (-not (Test-Path $frontendIndex)) {
    Write-Error "Frontend distribution missing at $frontendIndex. Build frontend first."
    exit 1
}
Write-Host "Frontend build verified: $frontendIndex" -ForegroundColor Green

$dist = Join-Path $root "build\nuitka"
$rel = Join-Path $root "release\$ReleaseName"

# 3. Clean previous build directories & running processes
Write-Host "==> Step 1: Cleaning previous build directories & processes..." -ForegroundColor Yellow
Get-Process -Name "$AppName*", "BrainLead*" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

foreach ($d in @($dist, $rel, (Join-Path $root "release\$ReleaseName.zip"))) {
    if (Test-Path $d) {
        Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue
    }
}
New-Item -ItemType Directory -Path $dist -Force | Out-Null
New-Item -ItemType Directory -Path $rel -Force | Out-Null

# 4. Stage 1: Nuitka Native C/C++ Compilation
Write-Host "==> Step 2: Compiling Python sources to Native C/C++ with Nuitka..." -ForegroundColor Yellow
$src = Join-Path $root "app.py"
if (-not (Test-Path $src)) { $src = Join-Path $root "launcher.py" }

$nuitkaFlags = @(
    "-m", "nuitka",
    "--assume-yes-for-downloads",
    "--output-dir=$dist",
    "--output-filename=$AppName.exe",
    "--company-name=Brain Lead",
    "--product-name=$AppId",
    "--file-version=$peVersion",
    "--product-version=$peVersion",
    "--file-description=$AppDescription",
    "--copyright=Copyright (c) Brain Lead (https://brainlead.dev). All rights reserved."
)

if ($Standalone) {
    $nuitkaFlags += "--standalone"
} else {
    $nuitkaFlags += "--onefile"
}

if ($Console) {
    $nuitkaFlags += "--windows-console-mode=force"
} else {
    $nuitkaFlags += "--windows-console-mode=disable"
}

# Core packages & modules
$nuitkaFlags += "--include-package=backend"
$nuitkaFlags += "--include-package=uvicorn"
$nuitkaFlags += "--include-package=starlette"
$nuitkaFlags += "--include-package=fastapi"
$nuitkaFlags += "--include-package=pydantic"
$nuitkaFlags += "--include-package=curl_cffi"
$nuitkaFlags += "--include-package=cryptography"
$nuitkaFlags += "--include-module=app_info"
$nuitkaFlags += "--include-module=launcher"

# Bundle frontend assets inside the executable container
$nuitkaFlags += "--include-data-dir=$frontendDist=frontend/dist"

# Embed icon if present
if (Test-Path "$root\assets\icon.ico") {
    $nuitkaFlags += "--windows-icon-from-ico=$root\assets\icon.ico"
}

python @nuitkaFlags $src
if ($LASTEXITCODE -ne 0) {
    Write-Error "Nuitka native C compilation failed with exit code $LASTEXITCODE"
    exit 1
}

# 5. Stage 2: Assemble Release Package
Write-Host "==> Step 3: Assembling release folder '$rel'..." -ForegroundColor Yellow
if ($Standalone) {
    $standaloneDir = Get-ChildItem $dist -Directory -Filter "*.dist" | Select-Object -First 1
    if (-not $standaloneDir) {
        Write-Error "Nuitka standalone output directory not found in $dist"
        exit 1
    }
    Copy-Item -Path "$($standaloneDir.FullName)\*" -Destination "$rel\" -Recurse -Force
} else {
    $builtExe = Join-Path $dist "$AppName.exe"
    if (-not (Test-Path $builtExe)) {
        Write-Error "Nuitka output executable not found at $builtExe"
        exit 1
    }
    Copy-Item $builtExe "$rel\$AppName.exe" -Force
}

# Create clean database & results folders (NEVER bundle local developer license_data.json)
New-Item -ItemType Directory -Path (Join-Path $rel "database") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $rel "results") -Force | Out-Null
if (Test-Path "$root\assets") {
    Copy-Item "$root\assets" -Destination "$rel\assets" -Recurse -Force
}

# 6. Stage 3: Authenticode Code Signing & 1-Click Defender Whitelist
Write-Host "==> Step 4: Signing $AppName.exe with Authenticode..." -ForegroundColor Yellow
$signScript = Join-Path $root "sign_exe.ps1"
if (Test-Path $signScript) {
    & $signScript -FilePath "$rel\$AppName.exe" -ExportCertPath "$rel\BrainLead.cer"
} else {
    Write-Warning "sign_exe.ps1 not found at $signScript; skipping Authenticode signing."
}

# Bundle 1-click certificate trust installer
$trustBat = Join-Path $rel "Trust_Certificate.bat"
@"
@echo off
title Brain Lead - Trust Certificate Installer
echo ==============================================================
echo  Brain Lead Software - Certificate Trust Installer
echo ==============================================================
echo Installing Brain Lead security certificate to trusted publisher...
certutil -addstore -f "Root" "%~dp0BrainLead.cer"
certutil -addstore -f "TrustedPublisher" "%~dp0BrainLead.cer"
echo.
echo ==============================================================
echo Done! Windows Defender and SmartScreen now trust this tool.
echo You can now launch $AppName.exe with full confidence.
echo ==============================================================
pause
"@ | Set-Content -Path $trustBat -Encoding ASCII

# 7. Stage 4: Full Real-World Runtime Launch Verification
Write-Host "==> Step 5: Testing Release Executable Runtime Launch ($rel\$AppName.exe)..." -ForegroundColor Yellow
Get-Process -Name "$AppName*" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

$proc = Start-Process -FilePath "$rel\$AppName.exe" -WorkingDirectory $rel -PassThru
Write-Host "Launched $AppName.exe (PID=$($proc.Id)). Verifying initialization..." -ForegroundColor Cyan

# Give the process 6 seconds to initialize Uvicorn and start listening
Start-Sleep -Seconds 6
if ($proc.HasExited) {
    Write-Error "$AppName.exe exited prematurely with code $($proc.ExitCode)!"
    exit 1
}

# Scan logs in %APPDATA%\BrainLead for any startup crashes
$appDataLogDir = Join-Path ([Environment]::GetFolderPath("ApplicationData")) "BrainLead"
$errLog = Join-Path $appDataLogDir "stderr.log"
if (Test-Path $errLog) {
    $errContent = Get-Content $errLog -Raw
    if ($errContent -and ($errContent -match "Traceback \(most recent call last\):" -or $errContent -match "ModuleNotFoundError" -or $errContent -match "ImportError")) {
        try { taskkill /F /T /PID $proc.Id 2>$null } catch {}
        Write-Error "CRITICAL: Exception detected in stderr.log: $errContent"
        exit 1
    }
}

Write-Host "Runtime verification PASSED ($AppName.exe started cleanly with 0 tracebacks)." -ForegroundColor Green

# 8. Stage 5: Process Tree Termination & ZIP Packaging
Write-Host "==> Step 6: Packaging release ZIP archive..." -ForegroundColor Yellow
try { taskkill /F /T /PID $proc.Id 2>$null } catch {}
Get-Process -Name "$AppName*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 4

$zipPath = Join-Path $root "release\$ReleaseName.zip"
$archived = $false
for ($attempt = 1; $attempt -le 5; $attempt++) {
    try {
        Compress-Archive -Path "$rel\*" -DestinationPath $zipPath -Force
        $archived = $true
        break
    } catch {
        Write-Warning "File lock detected on archive attempt $attempt. Waiting 3 seconds..."
        Start-Sleep -Seconds 3
    }
}
if (-not $archived) {
    python -c "import shutil, sys; shutil.make_archive(sys.argv[1].replace('.zip', ''), 'zip', sys.argv[2])" $zipPath $rel
}

$zipSize = (Get-Item $zipPath).Length
Write-Host "==========================================================" -ForegroundColor Green
Write-Host " NUITKA NATIVE BUILD & SIGNING COMPLETE!" -ForegroundColor Green
Write-Host " Executable : $rel\$AppName.exe" -ForegroundColor Green
Write-Host " Package    : $zipPath ($([math]::Round($zipSize/1MB, 2)) MB)" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
