# Builds the Windows desktop app into dist\URLtoVideo and dist\URLtoVideo-windows.zip.
# Run from anywhere: powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1
# Needs Python 3.10+ on PATH. Downloads yt-dlp and ffmpeg on the first run.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Bin = Join-Path $PSScriptRoot "bin"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null

if (-not (Test-Path "$Bin\yt-dlp.exe")) {
    Write-Host "Downloading yt-dlp.exe..."
    Invoke-WebRequest "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" -OutFile "$Bin\yt-dlp.exe"
}
if (-not (Test-Path "$Bin\ffmpeg.exe")) {
    Write-Host "Downloading ffmpeg..."
    $zip = Join-Path $env:TEMP "ffmpeg-win64.zip"
    $unz = Join-Path $env:TEMP "ffmpeg-win64"
    Invoke-WebRequest "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -OutFile $zip
    if (Test-Path $unz) { Remove-Item -Recurse -Force $unz }
    Expand-Archive $zip -DestinationPath $unz
    $dir = Get-ChildItem $unz -Directory | Select-Object -First 1
    Copy-Item "$($dir.FullName)\bin\ffmpeg.exe", "$($dir.FullName)\bin\ffprobe.exe" $Bin
    Copy-Item "$($dir.FullName)\LICENSE.txt" "$Bin\FFMPEG_LICENSE.txt"
}

Push-Location $Root
try {
    if (-not (Test-Path ".venv-desktop")) { python -m venv .venv-desktop }
    $py = ".venv-desktop\Scripts\python.exe"
    & $py -m pip install --upgrade pip | Out-Null
    & $py -m pip install -r desktop\requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    & $py -m PyInstaller desktop\URLtoVideo.spec --noconfirm --clean --distpath dist --workpath build
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
    $out = "dist\URLtoVideo-windows.zip"
    if (Test-Path $out) { Remove-Item $out }
    Compress-Archive -Path dist\URLtoVideo -DestinationPath $out
    Write-Host "Built dist\URLtoVideo\URLtoVideo.exe and $out"
} finally {
    Pop-Location
}
