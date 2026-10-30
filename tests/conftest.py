"""Keep tests away from the real user's data: storemgr reads %LOCALAPPDATA% (data folder, log, migration of old
folders) when it is first imported, so point it at a throwaway folder before any test module imports it."""

import os
import tempfile

import pytest

_SANDBOX = tempfile.mkdtemp(prefix="storely-tests-")
os.environ["LOCALAPPDATA"] = os.path.join(_SANDBOX, "LocalAppData")
os.environ["ProgramData"] = os.path.join(_SANDBOX, "ProgramData")
os.makedirs(os.environ["LOCALAPPDATA"], exist_ok=True)


@pytest.fixture(scope="session")
def qapp():
    """One full QApplication for every Qt test (a plain QCoreApplication created first would block widgets)."""
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
