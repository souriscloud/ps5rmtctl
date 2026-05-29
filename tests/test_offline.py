"""Hardware-free tests: button mapping + interactive-remote key parser.

Run with:  .venv/bin/python tests/test_offline.py
(or under pytest if installed). No PS5 or network required.
"""
import sys

from pyremoteplay.controller import Controller

from ps5rmtctl.buttons import ALIASES, CANONICAL, UnknownButton, resolve
from ps5rmtctl.cli import _REMOTE_KEYS, _parse_remote


def test_canonical_matches_library():
    assert set(CANONICAL) == set(Controller.buttons())


def test_aliases_and_keys_are_valid_buttons():
    real = set(Controller.buttons())
    for alias, canonical in ALIASES.items():
        assert canonical in real, f"alias {alias}->{canonical}"
    for seq, canonical in _REMOTE_KEYS.items():
        assert canonical in real, f"key {seq!r}->{canonical}"


def test_resolve():
    assert resolve("home") == "PS"
    assert resolve("PAUSE") == "OPTIONS"
    assert resolve("option") == "OPTIONS"
    assert resolve("x") == "CROSS"
    assert resolve("CROSS") == "CROSS"
    for bad in ("", "  ", "wobble", None):
        try:
            resolve(bad)  # type: ignore[arg-type]
        except UnknownButton:
            continue
        raise AssertionError(f"expected UnknownButton for {bad!r}")


def test_remote_parser():
    assert list(_parse_remote(b"\x1b[A\x1b[B")) == ["UP", "DOWN"]
    assert list(_parse_remote(b"\x1b[C\x1b[D")) == ["RIGHT", "LEFT"]
    assert list(_parse_remote(b"\r")) == ["CROSS"]
    assert list(_parse_remote(b" ")) == ["CROSS"]
    assert list(_parse_remote(b"\x7f")) == ["CIRCLE"]
    # quit short-circuits the rest of the chunk
    assert list(_parse_remote(b"xqz")) == ["CIRCLE", "QUIT"]
    # unknown bytes are ignored, known ones still parsed
    assert list(_parse_remote(b"AzB")) == ["CROSS"]  # 'z'->CROSS; 'A'/'B' ignored


def test_server_auth_and_routes():
    from aiohttp.test_utils import make_mocked_request

    from ps5rmtctl.server import _check_token, build_app
    from ps5rmtctl.service import PS5Service

    # token via header and via query param
    req = make_mocked_request("GET", "/api/status", headers={"Authorization": "Bearer abc"})
    assert _check_token(req, "abc")
    assert not _check_token(req, "nope")
    req_q = make_mocked_request("GET", "/ws?token=abc")
    assert _check_token(req_q, "abc")

    app = build_app(PS5Service("1.2.3.4", "u"), "tok")
    paths = {r.resource.canonical for r in app.router.routes()}
    expected = {"/", "/ws", "/api/status", "/api/connect", "/api/disconnect",
                "/api/tap", "/api/press", "/api/release", "/api/hold", "/api/wake"}
    assert expected <= paths, expected - paths


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed")


if __name__ == "__main__":
    _run()
    sys.exit(0)
