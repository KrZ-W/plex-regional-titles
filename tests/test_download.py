from unittest.mock import MagicMock

import requests

from plex_regional_titles.download import fetch_dataset, read_meta, write_meta


class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size):
        yield self._body


def test_download_then_conditional_304(tmp_path):
    dest = tmp_path / "d.csv"
    session = MagicMock()
    session.get.return_value = FakeResponse(200, b"data", {"ETag": '"e1"', "Last-Modified": "Mon"})
    r = fetch_dataset("http://x/d", dest, 7, session)
    assert r.changed and dest.read_bytes() == b"data"
    assert read_meta(dest)["etag"] == '"e1"'

    # fresh -> no request at all
    session.get.reset_mock()
    r = fetch_dataset("http://x/d", dest, 7, session)
    assert r.from_cache and not session.get.called

    # stale -> conditional request, 304 keeps file
    write_meta(dest, {**read_meta(dest), "checked_at": 0})
    session.get.return_value = FakeResponse(304)
    r = fetch_dataset("http://x/d", dest, 7, session)
    headers = session.get.call_args.kwargs["headers"]
    assert headers["If-None-Match"] == '"e1"' and headers["If-Modified-Since"] == "Mon"
    assert r.from_cache and not r.changed and dest.read_bytes() == b"data"


def test_failure_keeps_cached_file(tmp_path):
    dest = tmp_path / "d.csv"
    dest.write_bytes(b"old")
    write_meta(dest, {"checked_at": 0})
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError("down")
    r = fetch_dataset("http://x/d", dest, 7, session)
    assert r.from_cache and dest.read_bytes() == b"old"
    assert not dest.with_suffix(".csv.part").exists()


def test_http_error_keeps_cached_file(tmp_path):
    dest = tmp_path / "d.csv"
    dest.write_bytes(b"old")
    write_meta(dest, {"checked_at": 0})
    session = MagicMock()
    session.get.return_value = FakeResponse(500)
    r = fetch_dataset("http://x/d", dest, 7, session)
    assert r.from_cache and dest.read_bytes() == b"old"
