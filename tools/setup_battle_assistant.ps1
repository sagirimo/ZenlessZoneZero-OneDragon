$ErrorActionPreference = 'Stop'
$battleRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $battleRoot
$battleUv = Join-Path $battleRoot '.install\battle-tools\bin\uv.exe'
if (-not (Test-Path -LiteralPath $battleUv)) {
    Write-Host 'Downloading the official environment tool...'
    $battlePackageDir = Join-Path $battleRoot '.install\battle-setup'
    New-Item -ItemType Directory -Path $battlePackageDir -Force | Out-Null
    $battleArchive = Join-Path $battlePackageDir 'uv-0.13.5.zip'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/astral-sh/uv/releases/download/0.13.5/uv-x86_64-pc-windows-msvc.zip' -OutFile $battleArchive
    $battleExpectedHash = 'a38b8d1902b7cfbc76b423ba1bb456f623f42064cdc72628b6075b89afd1019a'
    if ((Get-FileHash -LiteralPath $battleArchive -Algorithm SHA256).Hash -ne $battleExpectedHash) {
        throw 'Environment tool checksum mismatch. Please retry the download.'
    }
    Expand-Archive -LiteralPath $battleArchive -DestinationPath $battlePackageDir -Force
    $battleDownloadedUv = Get-ChildItem -LiteralPath $battlePackageDir -Recurse -Filter 'uv.exe' | Select-Object -First 1
    if ($null -eq $battleDownloadedUv) { throw 'The downloaded package does not contain uv.exe.' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $battleUv) -Force | Out-Null
    Copy-Item -LiteralPath $battleDownloadedUv.FullName -Destination $battleUv -Force
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $battleRoot '.install\battle-python'
$env:UV_CACHE_DIR = Join-Path $battleRoot '.install\battle-cache'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
& $battleUv sync --frozen --no-dev --python 3.11
if ($LASTEXITCODE -ne 0) { throw 'Environment setup failed. Read the error above and retry.' }
Write-Host 'Ready. Open the battle launcher CMD to start.'
