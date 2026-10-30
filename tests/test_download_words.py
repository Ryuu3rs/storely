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
