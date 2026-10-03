<#
Builds Storely for this PC's processor (x64 or ARM64 - PyInstaller can't cross-build; CI builds both):
clean venv from the hash-pinned lock -> tests -> PyInstaller (dist\Storely) -> smoke test ->
Inno Setup installer (dist\Storely-Setup-<version>-<arch>.exe).
  pwsh -File build.ps1            full build
  pwsh -File build.ps1 -NoTests   skip pytest
#>
param([switch]$NoTests, [string]$Python = '')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
$lock = if ($arch -eq 'arm64') { 'requirements-arm64.lock' } else { 'requirements.lock' }
$venv = Join-Path $PSScriptRoot "build\venv-$arch"
$py = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $py)) {
    $base = if ($Python) { $Python } elseif (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
    & $base -m venv $venv
    if ($LASTEXITCODE) { throw 'could not create the build venv' }
}
& $py -m pip install --disable-pip-version-check -q --require-hashes -r $lock
if ($LASTEXITCODE) { throw 'dependency install failed (hash mismatch or network)' }

if (-not $NoTests) {
    & $py -m pytest -q
    if ($LASTEXITCODE) { throw 'tests failed' }
}

& $py tools\make_installer_images.py
& $py -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath "build\pyinstaller-$arch" Storely.spec
if ($LASTEXITCODE) { throw 'PyInstaller failed' }

$cli = 'dist\Storely\storely-cli.exe'
$v = & $cli --version
if ($LASTEXITCODE -or -not $v) { throw "smoke test failed: $cli --version" }
Write-Host "built $v ($arch)"
if (Get-ChildItem dist\Storely -Recurse -Include *.ps1, *.py | Select-Object -First 1) { throw 'loose scripts in the build' }

$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw 'Inno Setup 6 not found (winget install JRSoftware.InnoSetup)' }
& $iscc /Q "/DArch=$arch" installer\Storely.iss
if ($LASTEXITCODE) { throw 'Inno Setup failed' }
Get-ChildItem "dist\Storely-Setup-*-$arch.exe" | Sort-Object LastWriteTime | Select-Object -Last 1 |
    ForEach-Object { Write-Host "installer: $($_.FullName) ($([math]::Round($_.Length / 1MB, 1)) MB)" }
