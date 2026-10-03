# Contributing

Thanks for helping. Bug reports, ideas and pull requests are all welcome.

## Running from source

Needs Windows 10 1809+ and Python 3.12+.

```
python -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r requirements.lock
.venv\Scripts\python main.py
```

From source, admin actions (deep unjam, WindowsApps clean-up, apps with a Windows service, changing the default
drive) are switched off unless the folder can only be changed by admins - use an installed build to test those.

## Checks

```
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check --select F,E9,B .
.venv\Scripts\python tools\screenshots.py      # renders every page invisibly; fails if one raises
```

Code style: short docstrings, few comments (only where the why isn't obvious), plain-English messages for users.

## Building an installer

`pwsh -File build.ps1` builds for this PC's processor: clean venv from `requirements.lock` -> tests -> PyInstaller
-> smoke test -> `dist\Unjammed-Setup-<version>-<arch>.exe` (needs Inno Setup 6). Dependencies change through
`requirements.txt` / `requirements-dev.txt`, then regenerate both locks:

```
uv pip compile requirements.txt requirements-dev.txt --generate-hashes --python-platform windows --python-version 3.14 --no-header -o requirements.lock
uv pip compile requirements.txt requirements-dev.txt --generate-hashes --python-platform aarch64-pc-windows-msvc --python-version 3.14 --no-header -o requirements-arm64.lock
```

## Releasing (maintainers)

1. Bump `__version__` in `storemgr/__init__.py`, add the section to `CHANGELOG.md`, commit.
2. Tag and push: `git tag v1.2.0 && git push origin v1.2.0`. The Release workflow builds x64 and ARM64 natively and
   attaches both installers to a draft release.
3. On the maintainer's PC (where the signing key lives):
   `.venv\Scripts\python tools\sign_release.py --publish v1.2.0` - downloads the installers, writes and uploads the
   signed `SHA256SUMS`, and publishes the release. Installed copies only accept updates signed with that key.
