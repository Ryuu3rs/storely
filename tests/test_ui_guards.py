"""UI plumbing that must not turn a closed page into an error dialog."""

import pytest

from storemgr.jobs import Jobs


def test_result_for_a_closed_page_is_ignored(qapp):
    jobs = Jobs(None)

    def callback(result, error):
        raise RuntimeError("Internal C++ object (QPushButton) already deleted.")
    jobs._cb[1] = callback
    jobs._done(1, "cards", None)        # must not raise


def test_other_errors_still_surface(qapp):
    jobs = Jobs(None)
    jobs._cb[2] = lambda r, e: (_ for _ in ()).throw(RuntimeError("something real"))
    with pytest.raises(RuntimeError, match="something real"):
        jobs._done(2, None, None)
