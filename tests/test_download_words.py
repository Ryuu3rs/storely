"""Network failures reach the user as something they can act on, never as HTTPSConnectionPool(...) noise."""

import requests

from storemgr.download import plain


def test_connection_error_reads_plainly():
    e = requests.ConnectionError("HTTPSConnectionPool(host='tlu.dl.delivery.mp.microsoft.com', port=443): Max retries")
    assert plain(e) == "Can't reach Microsoft's servers - check your internet connection"


def test_timeout_reads_plainly():
    assert "didn't answer in time" in plain(requests.ReadTimeout("read timed out"))


def test_http_status_reads_plainly():
    r = requests.Response()
    r.status_code = 503
    assert "HTTP 503" in plain(requests.HTTPError(response=r)) and "try again" in plain(requests.HTTPError(response=r))


def test_other_errors_pass_through():
    assert plain(RuntimeError("signature check failed")) == "signature check failed"


def test_one_downloader_per_file(tmp_path):
    import threading

    import pytest

    from storemgr.download import _FileLock
    dest = tmp_path / "app.msix"
    holder = _FileLock(dest, threading.Event()).__enter__()
    try:
        with pytest.raises(RuntimeError, match="still running"):
            _FileLock(dest, threading.Event(), wait=1.5).__enter__()
    finally:
        holder.__exit__(None, None, None)
    with _FileLock(dest, threading.Event(), wait=1):     # free again once the first one is done
        pass
