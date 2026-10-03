<#
Builds My Store: clean venv from the hash-pinned lock -> tests -> PyInstaller (dist\MyStore) -> smoke test ->
Inno Setup installer (dist\MyStore-Setup-<version>.exe).
  pwsh -File build.ps1            full build
  pwsh -File build.ps1 -NoTests   skip pytest
#>
param([switch]$NoTests)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$venv = Join-Path $PSScriptRoot 'build\venv'
$py = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $py)) {
    $base = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
    & $base -m venv $venv
    if ($LASTEXITCODE) { throw 'could not create the build venv' }
}
& $py -m pip install --disable-pip-version-check -q --require-hashes -r requirements.lock
if ($LASTEXITCODE) { throw 'dependency install failed (hash mismatch or network)' }

if (-not $NoTests) {
    & $py -m pytest -q
    if ($LASTEXITCODE) { throw 'tests failed' }
}

& $py tools\make_installer_images.py
& $py -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build\pyinstaller MyStore.spec
if ($LASTEXITCODE) { throw 'PyInstaller failed' }

$cli = 'dist\MyStore\mystore-cli.exe'
$v = & $cli --version
if ($LASTEXITCODE -or -not $v) { throw "smoke test failed: $cli --version" }
Write-Host "built $v"
if (Get-ChildItem dist\MyStore -Recurse -Include *.ps1, *.py | Select-Object -First 1) { throw 'loose scripts in the build' }

$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw 'Inno Setup 6 not found (winget install JRSoftware.InnoSetup)' }
& $iscc /Q installer\MyStore.iss
if ($LASTEXITCODE) { throw 'Inno Setup failed' }
Get-ChildItem dist\MyStore-Setup-*.exe | Sort-Object LastWriteTime | Select-Object -Last 1 |
    ForEach-Object { Write-Host "installer: $($_.FullName) ($([math]::Round($_.Length / 1MB, 1)) MB)" }
