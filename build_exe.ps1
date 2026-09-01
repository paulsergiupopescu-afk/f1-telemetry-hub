<#
    Build the single unified F1TelemetryHub.exe application.

    The executable includes the Solo Engineer, Split Screen dashboard, report
    generators, engineer logic, and all imported circuit racing-line data.

    Run:
      powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
#>

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot
Set-Location $projectDir

$needed = @(
    "f1_app.py", "f1_hub.py", "f1_solo.py", "f1_26_split_telemetry.py",
    "f1_report.py", "f1_compare.py", "f1_championship.py",
    "f1_race_report.py", "f1_solo_report.py", "f1_engineer.py",
    "f1_track_data.py"
)
foreach ($file in $needed) {
    if (-not (Test-Path (Join-Path $projectDir $file))) {
        Write-Host "Missing $file." -ForegroundColor Red
        exit 1
    }
}
if (-not (Test-Path (Join-Path $projectDir "tracks"))) {
    Write-Host "Missing imported tracks directory." -ForegroundColor Red
    exit 1
}

$venvPython = Join-Path $projectDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    $basePython = $null
    $baseArgs = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $basePython = "py"
        $baseArgs = @("-3")
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $basePython = "python"
    } else {
        Write-Host "Python was not found. Install it from python.org and enable Add to PATH." -ForegroundColor Red
        exit 1
    }
    & $basePython @baseArgs -m venv (Join-Path $projectDir ".venv")
}

Write-Host "Installing build dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $projectDir "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "Dependency installation failed." -ForegroundColor Red
    exit 1
}

$hiddenImports = @(
    "f1_26_split_telemetry", "f1_report", "f1_compare", "f1_championship",
    "f1_race_report", "f1_solo_report", "f1_engineer", "f1_track_data",
    "f1_database", "f1_session_studio", "f1_strategy", "f1_strategy_lab",
    "f1_live_strategy", "f1_race_control", "f1_driver_learning", "f1_community_reference",
    "f1_setup_packages", "f1_web_app", "webview",
    "f1_prerace", "f1_setup_library", "f1_theme", "f1_ui",
    "f1_ai_engineer",
    "openpyxl", "matplotlib.backends.backend_agg"
)
$hiddenArgs = @()
foreach ($module in $hiddenImports) {
    $hiddenArgs += "--hidden-import"
    $hiddenArgs += $module
}

# --onedir (the default) instead of --onefile: a onefile build re-extracts
# every DLL/library to a fresh %TEMP% folder on every launch, which is why
# the app was so slow to open from a shortcut. --onedir extracts once, at
# build time, so the shortcut just runs the exe directly.
Write-Host "Building unified F1TelemetryHub app folder..." -ForegroundColor Cyan
& $venvPython -m PyInstaller --noconfirm --clean --windowed --noupx `
    --name F1TelemetryHub --icon "assets\race_command_icon_v2.ico" @hiddenArgs `
    --add-data "tracks;tracks" --add-data "web;web" `
    --add-data "assets\brendon_leigh_setups_v1_5.json;assets" `
    --add-data "assets\race_command_icon_v2.ico;assets" `
    --add-data "assets\race_command_icon_v2.png;assets" `
    f1_app.py

$output = Join-Path $projectDir "dist\F1TelemetryHub\F1TelemetryHub.exe"
if ($LASTEXITCODE -eq 0 -and (Test-Path $output)) {
    $sizeMb = [math]::Round((Get-Item $output).Length / 1MB, 1)
    Write-Host "Done: $output ($sizeMb MB)" -ForegroundColor Green
    Write-Host "Point your Windows shortcut at this exe (inside the F1TelemetryHub folder), not a copy of it alone -- it needs the adjacent files." -ForegroundColor Yellow
} else {
    Write-Host "Build failed. Review the messages above." -ForegroundColor Red
    exit 1
}
