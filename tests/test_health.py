"""Health checks must not fall over (or show a raw command) when Windows is slow to answer."""

import subprocess
from datetime import datetime

import pytest

from storemgr import health, winapps


def test_boot_time_needs_no_powershell(monkeypatch):
    monkeypatch.setattr(health, "ps", lambda *a, **k: pytest.fail("boot time must not use PowerShell"))
    boot = health._boot_time()
    assert isinstance(boot, datetime) and boot < datetime.now().astimezone()


def test_services_need_no_powershell(monkeypatch):
    monkeypatch.setattr(health, "ps", lambda *a, **k: pytest.fail("services must not use PowerShell"))
    s = health.services()
    assert s.get("AppXSvc") in ("Running", "Stopped", "Starting", "Stopping")


def test_slow_event_log_is_skipped_not_raised(monkeypatch):
    def slow(*a, **k):
        raise winapps.WindowsBusy(["pwsh"], 120)
    monkeypatch.setattr(health, "ps", slow)
    assert health.installer_jobs() == []


def test_timeout_message_is_plain_words():
    e = winapps.WindowsBusy(["pwsh", "-Command", "Get-CimInstance Win32_OperatingSystem"], 30)
    assert isinstance(e, subprocess.TimeoutExpired)
    assert "pwsh" not in str(e) and "Get-CimInstance" not in str(e) and "30 seconds" in str(e)
