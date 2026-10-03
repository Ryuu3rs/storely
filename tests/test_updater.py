"""Self-update: version compare, asset choice, host allowlist, Ed25519-signed SHA256SUMS, install path guard."""

import base64
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from storemgr import updater

GH = "https://github.com/Ryuu3rs/unjammed/releases/download/v9.1.0/"
CDN = "https://release-assets.githubusercontent.com/github-production-release-asset/1/abc?sig=x"
X64, ARM = "Unjammed-Setup-9.1.0.0-x64.exe", "Unjammed-Setup-9.1.0.0-arm64.exe"
PAYLOAD = b"MZ fake installer " * 1000


class Resp:
    def __init__(self, url, status=200, body=b"", headers=None):
        self.url, self.status_code, self._body, self.headers = url, status, body, headers or {}

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]

    def json(self):
        return json.loads(self._body)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


@pytest.fixture
def net(monkeypatch):
    """routes[url] = Resp | Exception; every requested url is recorded in .calls."""
    n = SimpleNamespace(routes={}, calls=[])

    def get(url, **kw):
        assert kw.get("allow_redirects") is False
        n.calls.append(url)
        r = n.routes.get(url)
        if r is None:
            raise requests.ConnectionError(f"no route to {url}")
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(updater.requests, "get", get)
    return n


@pytest.fixture
def key(monkeypatch):
    k = Ed25519PrivateKey.generate()
    raw = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(updater, "PUBLIC_KEY", base64.b64encode(raw).decode())
    return k


@pytest.fixture
def upd_dir(tmp_path, monkeypatch):
    d = tmp_path / "updates"
    monkeypatch.setattr(updater, "UPDATE_DIR", d)
    return d


def asset(name, size=1):
    return {"name": name, "size": size, "browser_download_url": GH + name}


def api(tag="v9.1.0", names=(X64, ARM, "SHA256SUMS", "SHA256SUMS.sig"), **extra):
    return {"tag_name": tag, "body": "  What's new\n", "html_url": "https://github.com/Ryuu3rs/unjammed/releases/tag/v9.1.0",
            "assets": [asset(n, len(PAYLOAD) if n.endswith(".exe") else 1) for n in names], **extra}


def release(name=X64, size=None):
    size = len(PAYLOAD) if size is None else size
    return updater.Release("9.1.0", "", GH + name, size, GH + "SHA256SUMS", GH + "SHA256SUMS.sig", GH)


def publish(net, k, sums=None, sig_of=None, installer=PAYLOAD, name=X64, cdn=CDN):
    """Serve a release: SUMS + sig directly from github.com, the installer through a redirect to `cdn`."""
    sums = sums if sums is not None else f"{hashlib.sha256(installer).hexdigest()}  {name}\n".encode()
    sig = base64.b64encode(k.sign(sig_of if sig_of is not None else sums))
    net.routes[GH + "SHA256SUMS"] = Resp(GH + "SHA256SUMS", body=sums)
    net.routes[GH + "SHA256SUMS.sig"] = Resp(GH + "SHA256SUMS.sig", body=sig + b"\n")
    net.routes[GH + name] = Resp(GH + name, 302, headers={"Location": cdn})
    net.routes[cdn] = Resp(cdn, body=installer)


# versions

@pytest.mark.parametrize("cand,cur,newer", [("1.2.1", "1.2.0", True), ("v1.10.0", "1.9.9", True), ("2.0.0", "1.99.99", True),
                                            ("1.2.0", "1.2.0", False), ("1.1.9", "1.2.0", False), ("v1.2", "1.0.0", False),
                                            ("1.3.0-beta", "1.2.0", False), ("", "1.2.0", False), ("1.3.0", "junk", False)])
def test_is_newer(cand, cur, newer):
    assert updater.is_newer(cand, cur) is newer


# release parsing / asset choice

@pytest.mark.parametrize("arch,name", [("x64", X64), ("arm64", ARM)])
def test_parse_release_picks_this_arch(arch, name):
    rel = updater.parse_release(api(), current="1.2.0", arch=arch)
    assert rel.version == "9.1.0" and rel.installer_url == GH + name and rel.installer_name == name
    assert rel.sums_url == GH + "SHA256SUMS" and rel.sig_url == GH + "SHA256SUMS.sig"
    assert rel.size == len(PAYLOAD) and rel.notes == "What's new" and rel.page_url.startswith("https://github.com/")


@pytest.mark.parametrize("data", [
    api(tag="v1.2.0"), api(tag="v1.0.0"), api(tag="nightly"), api(draft=True), api(prerelease=True),
    api(names=(X64, "SHA256SUMS")), api(names=(ARM, "SHA256SUMS", "SHA256SUMS.sig")),
    api(names=("Unjammed-Setup-9.0.0.0-x64.exe", "SHA256SUMS", "SHA256SUMS.sig")), {}, [],
])
def test_parse_release_rejects(data):
    assert updater.parse_release(data, current="1.2.0", arch="x64") is None


def test_parse_release_rejects_asset_on_other_host():
    data = api()
    data["assets"][0]["browser_download_url"] = "https://evil.example/" + X64
    assert updater.parse_release(data, current="1.2.0", arch="x64") is None


def test_machine_arch_is_known():
    assert updater.machine_arch() in ("x64", "arm64")


# host allowlist

@pytest.mark.parametrize("url", [GH + X64, CDN, "https://api.github.com/repos/x/y", "https://objects.githubusercontent.com/a",
                                 "https://github.com:443/a"])
def test_allowed_urls(url):
    assert updater.allowed_url(url)


@pytest.mark.parametrize("url", ["http://github.com/a", "https://github.com.evil.example/a", "https://evilgithub.com/a",
                                 "https://github.com@evil.example/a", "https://user@github.com/a", "https://github.com:8443/a",
                                 "https://raw.githubusercontent.com/a", "https://evil.example/github.com/a", "ftp://github.com/a",
                                 "file:///C:/x.exe", "", "https://[::1/"])
def test_rejected_urls(url):
    assert not updater.allowed_url(url)


def test_redirect_to_bad_host_is_refused(net):
    net.routes[GH + "a"] = Resp(GH + "a", 302, headers={"Location": "https://github.com.evil.example/a"})
    with pytest.raises(RuntimeError, match="unexpected address"):
        updater._get(GH + "a", 5)
    assert net.calls == [GH + "a"]


def test_redirect_downgrade_to_http_is_refused(net):
    net.routes[GH + "a"] = Resp(GH + "a", 301, headers={"Location": "http://objects.githubusercontent.com/a"})
    with pytest.raises(RuntimeError):
        updater._get(GH + "a", 5)


def test_final_url_on_bad_host_is_refused(net):
    net.routes[GH + "a"] = Resp("https://evil.example/a")
    with pytest.raises(RuntimeError, match="unexpected address"):
        updater._get(GH + "a", 5)


def test_redirect_loop_is_cut(net):
    net.routes[GH + "a"] = Resp(GH + "a", 302, headers={"Location": GH + "a"})
    with pytest.raises(RuntimeError, match="too many redirects"):
        updater._get(GH + "a", 5)


# check()

def test_check_finds_newer_release(net, monkeypatch):
    monkeypatch.setattr(updater, "machine_arch", lambda: "arm64")
    net.routes[updater.LATEST_URL] = Resp(updater.LATEST_URL, body=json.dumps(api()).encode())
    rel = updater.check()
    assert rel and rel.installer_name == ARM


@pytest.mark.parametrize("route", [Resp(updater.LATEST_URL, 404, b'{"message":"Not Found"}'),
                                   Resp(updater.LATEST_URL, 403, b'{"message":"API rate limit exceeded"}'),
                                   Resp(updater.LATEST_URL, 200, b"<html>captive portal</html>"),
                                   requests.ConnectionError("offline"), requests.Timeout("slow")])
def test_check_is_quiet_when_nothing_to_do(net, route):
    net.routes[updater.LATEST_URL] = route
    assert updater.check() is None


# signed sums + download

def test_download_verifies_and_saves(net, key, upd_dir):
    publish(net, key)
    (upd_dir).mkdir()
    (upd_dir / "Unjammed-Setup-9.0.0.0-x64.exe").write_bytes(b"old")
    seen = []
    path = updater.download(release(), progress=lambda d, t, s: seen.append((d, t)))
    assert path == upd_dir / X64 and path.read_bytes() == PAYLOAD
    assert sorted(p.name for p in upd_dir.iterdir()) == [X64]
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))
    net.calls.clear()
    assert updater.download(release()) == path          # already downloaded and still good: no re-download
    assert GH + X64 not in net.calls


def test_signature_from_another_key_is_rejected(net, key, upd_dir):
    publish(net, Ed25519PrivateKey.generate())
    with pytest.raises(RuntimeError, match="signature"):
        updater.download(release())
    assert GH + X64 not in net.calls and not (upd_dir / X64).exists()


def test_tampered_sums_are_rejected(net, key, upd_dir):
    good = f"{hashlib.sha256(PAYLOAD).hexdigest()}  {X64}\n".encode()
    evil = b"EVIL!" + PAYLOAD
    publish(net, key, sums=f"{hashlib.sha256(evil).hexdigest()}  {X64}\n".encode(), sig_of=good, installer=evil)
    with pytest.raises(RuntimeError, match="signature"):
        updater.download(release())
    assert GH + X64 not in net.calls and not (upd_dir / X64).exists()


@pytest.mark.parametrize("sig", [b"", b"not base64!!", base64.b64encode(b"x" * 64)])
def test_garbage_signature_is_rejected(sig, key):
    with pytest.raises(RuntimeError, match="signature"):
        updater.verify_sums(b"abc", sig)


def test_wrong_hash_is_rejected_and_deleted(net, key, upd_dir):
    publish(net, key, sums=f"{'0' * 64}  {X64}\n".encode())
    with pytest.raises(RuntimeError, match="doesn't match"):
        updater.download(release())
    assert not any(upd_dir.iterdir())


def test_installer_missing_from_sums_is_rejected(net, key, upd_dir):
    publish(net, key, sums=f"{hashlib.sha256(PAYLOAD).hexdigest()}  {ARM}\n".encode())
    with pytest.raises(RuntimeError, match="isn't listed"):
        updater.download(release())
    assert GH + X64 not in net.calls


def test_oversized_download_is_rejected(net, key, upd_dir):
    publish(net, key)
    with pytest.raises(RuntimeError, match="bigger"):
        updater.download(release(size=100))
    assert not any(upd_dir.iterdir())


def test_installer_redirect_to_bad_host_is_refused(net, key, upd_dir):
    publish(net, key, cdn="https://release-assets.githubusercontent.com.evil.example/x")
    with pytest.raises(RuntimeError, match="unexpected address"):
        updater.download(release())
    assert not (upd_dir / X64).exists()


def test_cancel_leaves_nothing(net, key, upd_dir):
    publish(net, key)
    ev = threading.Event()
    ev.set()
    with pytest.raises(updater.Cancelled):
        updater.download(release(), cancel=ev)
    assert not any(upd_dir.iterdir())


def test_unexpected_installer_name_is_refused(net, key, upd_dir):
    rel = updater.Release("9.1.0", "", GH + "..%5Cevil.exe", 1, GH + "SHA256SUMS", GH + "SHA256SUMS.sig", GH)
    with pytest.raises(RuntimeError, match="unexpected installer name"):
        updater.download(rel)
    assert net.calls == []


# install()

def test_install_runs_only_our_downloads(upd_dir, tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(updater, "_shell_open", lambda f, p, c: ran.append((f, p, c)) or 0)
    upd_dir.mkdir()
    good = upd_dir / X64
    good.write_bytes(PAYLOAD)
    outside = tmp_path / X64
    outside.write_bytes(PAYLOAD)
    (upd_dir / "other.exe").write_bytes(b"x")
    for bad in (outside, upd_dir / "other.exe", upd_dir / ARM, upd_dir / ".." / X64, tmp_path / "updates2" / X64):
        with pytest.raises(RuntimeError, match="not a downloaded"):
            updater.install(bad)
    assert ran == []
    updater.install(good)
    assert ran == [(str(good.resolve()), "/SP- /SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS", str(upd_dir.resolve()))]


def test_install_reports_cancelled_uac(upd_dir, monkeypatch):
    monkeypatch.setattr(updater, "_shell_open", lambda f, p, c: 1223)
    upd_dir.mkdir()
    (upd_dir / X64).write_bytes(PAYLOAD)
    with pytest.raises(RuntimeError, match="cancelled"):
        updater.install(upd_dir / X64)
