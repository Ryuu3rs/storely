"""Fast, resumable, verified downloads: parallel byte ranges, SHA1 checked against Microsoft's published digest."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from pathlib import Path

import requests

SEGMENTS = 6
MIN_SEGMENTED = 32 * 1024 * 1024
CHUNK = 1024 * 1024


class Cancelled(Exception):
    pass


class _Limiter:
    """Shared speed limit across every download thread (bytes per second; 0 = unlimited)."""

    def __init__(self):
        self.bps = 0
        self._lock = threading.Lock()
        self._next = time.monotonic()

    def take(self, n: int):
        if self.bps <= 0:
            return
        with self._lock:
            now = time.monotonic()
            self._next = max(self._next, now) + n / self.bps
            wait = self._next - now
        if wait > 0:
            time.sleep(min(wait, 5))


LIMIT = _Limiter()


def sha1_b64(path: Path) -> str:
    return file_digest(path, "sha1")


def file_digest(path: Path, algo: str) -> str:
    """sha1 -> base64 (how Microsoft's delivery service publishes it); sha256 -> lower-case hex (Store manifests)."""
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return base64.b64encode(h.digest()).decode() if algo == "sha1" else h.hexdigest()


def _size_of(url: str) -> int:
    try:
        r = requests.head(url, allow_redirects=True, timeout=30)
        return int(r.headers.get("Content-Length") or 0)
    except (requests.RequestException, ValueError):
        return 0


def fetch(url: str, dest: Path, size: int, digest: str, progress=None, cancel: threading.Event | None = None,
          algo: str = "sha1") -> Path:
    """Download url to dest (size bytes; 0 = ask the server), resuming a previous partial download, and check the
    digest. progress(done, total, bytes_per_s)."""
    cancel = cancel or threading.Event()
    digest = digest if algo == "sha1" else digest.lower()
    part = dest.with_suffix(dest.suffix + ".part")
    state_file = dest.with_suffix(dest.suffix + ".state")
    if dest.exists() and (not size or dest.stat().st_size == size) and file_digest(dest, algo) == digest:
        return dest
    size = size or _size_of(url)
    if not size:
        raise RuntimeError("the server didn't say how big the file is")

    n = SEGMENTS if size >= MIN_SEGMENTED else 1
    bounds = [(i * size // n, (i + 1) * size // n - 1) for i in range(n)]
    done = [0] * n
    try:
        st = json.loads(state_file.read_text())
        if st.get("size") == size and st.get("digest") == digest and len(st.get("done", [])) == n and part.exists():
            done = st["done"]
    except (OSError, ValueError):
        pass
    if not part.exists() or part.stat().st_size != size:
        with open(part, "wb") as f:
            f.truncate(size)
        done = [0] * n

    lock = threading.Lock()
    errors: list[Exception] = []

    def save_state():
        state_file.write_text(json.dumps({"size": size, "digest": digest, "done": done}))

    def worker(i):
        start, end = bounds[i]
        for attempt in range(5):
            pos = start + done[i]
            if pos > end:
                return
            try:
                with requests.get(url, headers={"Range": f"bytes={pos}-{end}"}, stream=True, timeout=60) as r:
                    if r.status_code not in (200, 206):
                        raise RuntimeError(f"HTTP {r.status_code}")
                    if r.status_code == 200 and pos:
                        raise RuntimeError("server ignored the byte range")
                    with open(part, "r+b") as f:
                        f.seek(pos)
                        for chunk in r.iter_content(256 * 1024 if LIMIT.bps else CHUNK):
                            if cancel.is_set():
                                raise Cancelled()
                            LIMIT.take(len(chunk))
                            f.write(chunk)
                            with lock:
                                done[i] += len(chunk)
                return
            except Cancelled:
                raise
            except Exception as e:  # network blip: retry this segment from where it got to
                if attempt == 4:
                    errors.append(e)
                    return
                time.sleep(2 * (attempt + 1))

    threads = [threading.Thread(target=lambda i=i: _guard(worker, i, errors), daemon=True) for i in range(n)]
    for t in threads:
        t.start()
    last_t, last_b = time.time(), sum(done)
    while any(t.is_alive() for t in threads):
        time.sleep(0.25)
        now, got = time.time(), sum(done)
        if progress and now - last_t >= 0.5:
            progress(got, size, (got - last_b) / (now - last_t))
            last_t, last_b = now, got
            with lock:
                save_state()
    with lock:
        save_state()
    if cancel.is_set():
        raise Cancelled()
    if errors:
        raise RuntimeError(f"download failed: {errors[0]}")
    if progress:
        progress(size, size, 0)
    got = file_digest(part, algo)
    if got != digest:
        part.unlink(missing_ok=True)
        state_file.unlink(missing_ok=True)
        raise RuntimeError(f"download corrupt ({algo.upper()} {got}, Microsoft says {digest}) - deleted")
    dest.unlink(missing_ok=True)
    part.replace(dest)
    state_file.unlink(missing_ok=True)
    return dest


def _guard(fn, i, errors):
    try:
        fn(i)
    except Cancelled:
        pass
    except Exception as e:
        errors.append(e)
