"""Command-line front-end for ps5rmtctl."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import List, Optional

from . import config
from .buttons import ALIASES, CANONICAL, UnknownButton, resolve
from .core import PS5, PS5Error


class _BenignNoiseFilter(logging.Filter):
    """Drop messages that are expected for blind control and alarm users.

    Both originate from the throwaway senkusha network-test session, which we
    don't need (no video bitrate to tune): the console rejects the test
    session's client_version=7 ("Version not accepted") and the MTU probe times
    out ("Network Test timed out"). The real control session is unaffected.
    All other pyremoteplay warnings/errors still pass through.
    """

    _SQUELCH = ("Version not accepted", "Network Test timed out")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(s in msg for s in self._SQUELCH)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(_BenignNoiseFilter())

    # Squelch benign pyremoteplay noise but let real warnings through.
    pyrp = logging.getLogger("pyremoteplay")
    if not getattr(pyrp, "_ps5rmtctl_configured", False):
        pyrp.addHandler(handler)
        pyrp.propagate = False  # avoid the root lastResort handler double-printing
        pyrp._ps5rmtctl_configured = True  # type: ignore[attr-defined]

    # Surface our own INFO logs (warm session ready, idle release, ws connects).
    ours = logging.getLogger("ps5rmtctl")
    if not getattr(ours, "_ps5rmtctl_configured", False):
        ours.addHandler(handler)
        ours.setLevel(logging.INFO)
        ours.propagate = False
        ours._ps5rmtctl_configured = True  # type: ignore[attr-defined]


# --------------------------------------------------------------------- helpers
def _err(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def _resolve_host(args) -> Optional[str]:
    return getattr(args, "host", None) or os.environ.get("PS5RMTCTL_HOST") or config.get_default("host")


def _resolve_user(args) -> Optional[str]:
    return getattr(args, "user", None) or os.environ.get("PS5RMTCTL_USER") or config.get_default("user")


def _make_ps5(args, *, need_user: bool) -> PS5:
    host = _resolve_host(args)
    if not host:
        raise PS5Error("No host. Pass --host IP or run `ps5rmtctl setup` to save one.")
    user = _resolve_user(args)
    if need_user and not user:
        raise PS5Error("No user. Pass --user NAME or run `ps5rmtctl setup`.")
    return PS5(host, user)


# -------------------------------------------------------------------- commands
def cmd_discover(args) -> int:
    print("Searching for Remote Play devices on the LAN...")
    devices = _discover()
    if not devices:
        print("No devices found.")
        return 0
    for d in devices:
        print(f"  {d['host-ip']:<16} {d.get('host-type','?'):<4} {d.get('host-name','?')} "
              f"[{d.get('status','?')}]")
    return 0


def _discover() -> List[dict]:
    from pyremoteplay.ddp import search
    return search()


def cmd_status(args) -> int:
    ps5 = _make_ps5(args, need_user=False)
    ps5.refresh()
    print(ps5.status_summary)
    return 0


def cmd_accounts(args) -> int:
    accounts = PS5.list_accounts()
    if not accounts:
        print("No PSN accounts stored. Run `ps5rmtctl login`.")
        return 0
    print("Stored PSN accounts:")
    for name in accounts:
        print(f"  {name}")
    return 0


def cmd_login(args) -> int:
    print(
        "1. Open this URL in a browser and log in to your PSN account:\n\n"
        f"   {PS5.login_url()}\n\n"
        "2. After login you land on a blank/'redirect' page. Copy that page's\n"
        "   full URL (starts with https://remoteplay.dl.playstation.net/...).\n"
    )
    redirect = args.redirect or input("Paste redirect URL > ").strip()
    if not redirect:
        return _err("No redirect URL provided.")
    name = PS5.add_account(redirect)
    print(f"\nStored PSN account: {name}")
    if not config.get_default("user"):
        config.update_config(user=name)
        print(f"Set default user to '{name}'.")
    return 0


def cmd_register(args) -> int:
    ps5 = _make_ps5(args, need_user=True)
    pin = args.pin or input(
        f"On the PS5: Settings -> System -> Remote Play -> Link Device.\n"
        f"Enter the 8-digit PIN for user '{ps5.user}' > "
    ).strip()
    ps5.register(ps5.user, pin)
    print(f"Registered '{ps5.user}' with console at {ps5.host}.")
    config.update_config(host=ps5.host, user=ps5.user)
    return 0


def cmd_setup(args) -> int:
    """Guided one-time setup: pick host, login, register, save defaults."""
    host = args.host
    if not host:
        devices = _discover()
        ps5s = [d for d in devices if d.get("host-type") == "PS5"] or devices
        if ps5s:
            print("Found:")
            for i, d in enumerate(ps5s):
                print(f"  [{i}] {d['host-ip']} {d.get('host-name','?')}")
            sel = input("Select device number (or type an IP) > ").strip()
            host = ps5s[int(sel)]["host-ip"] if sel.isdigit() else sel
        else:
            host = input("No devices auto-found. Enter PS5 IP address > ").strip()
    if not host:
        return _err("No host selected.")
    config.update_config(host=host)

    if not PS5.list_accounts():
        rc = cmd_login(argparse.Namespace(redirect=None))
        if rc != 0:
            return rc
    user = config.get_default("user") or PS5.list_accounts()[0]
    config.update_config(user=user)

    ps5 = PS5(host, user)
    if user not in ps5.registered_users:
        pin = input(
            "Console not yet linked. On the PS5: Settings -> System -> Remote Play "
            "-> Link Device.\nEnter the 8-digit PIN > "
        ).strip()
        ps5.register(user, pin)
    print(f"\nSetup complete. host={host} user={user}")
    print("Try:  ps5rmtctl tap cross")
    return 0


def cmd_wake(args) -> int:
    ps5 = _make_ps5(args, need_user=True)
    print("Waking console...")
    ok = ps5.wake(timeout=args.timeout)
    print("Console is on." if ok else "Timed out waiting for console to wake.")
    return 0 if ok else 1


def cmd_buttons(args) -> int:
    print("Friendly names:")
    for alias in sorted(ALIASES):
        print(f"  {alias:<10} -> {ALIASES[alias]}")
    print("\nCanonical names:", ", ".join(CANONICAL))
    return 0


def cmd_tap(args) -> int:
    ps5 = _make_ps5(args, need_user=True)
    # Validate up front for a clean error before opening a session.
    for name in args.buttons:
        resolve(name)
    if args.wake:
        ps5.wake(timeout=args.timeout)
    asyncio.run(ps5.tap(*args.buttons, delay=args.delay, gap=args.gap))
    print(f"Sent: {' '.join(args.buttons)}")
    return 0


def cmd_hold(args) -> int:
    ps5 = _make_ps5(args, need_user=True)
    resolve(args.button)
    if args.wake:
        ps5.wake(timeout=args.timeout)
    asyncio.run(ps5.hold(args.button, duration=args.duration))
    print(f"Held {args.button} for {args.duration}s")
    return 0


def cmd_remote(args) -> int:
    ps5 = _make_ps5(args, need_user=True)
    if args.wake:
        ps5.wake(timeout=args.timeout)
    asyncio.run(_remote(ps5))
    return 0


def _resolve_token(args) -> str:
    """Token precedence: --token > env > config; generate + persist if absent."""
    token = getattr(args, "token", None) or os.environ.get("PS5RMTCTL_TOKEN") or config.get_default("token")
    if not token:
        import secrets

        token = secrets.token_urlsafe(16)
        config.update_config(token=token)
        print("Generated a new API token and saved it to config.")
    return token


def cmd_serve(args) -> int:
    from .server import serve
    from .service import PS5Service

    host = _resolve_host(args)
    user = _resolve_user(args)
    if not host or not user:
        raise PS5Error("serve needs a host and user. Run `setup` or pass --host/--user.")
    token = _resolve_token(args)
    service = PS5Service(host, user, idle_timeout=args.idle_timeout)
    print(f"PS5 control server  (user '{user}' -> console {host})")
    print(f"  bind:   http://{args.bind}:{args.port}/")
    print(f"  token:  {token}")
    print(f"  open:   http://<server-ip>:{args.port}/?token={token}")
    print("Ctrl-C to stop.\n")
    serve(service, token, host=args.bind, port=args.port)
    return 0


# ----------------------------------------------------------- interactive remote
# Raw byte sequence -> canonical button. Single keypress = one tap.
_REMOTE_KEYS = {
    b"\x1b[A": "UP", b"\x1b[B": "DOWN", b"\x1b[C": "RIGHT", b"\x1b[D": "LEFT",
    b"\r": "CROSS", b"\n": "CROSS", b" ": "CROSS",
    b"\x7f": "CIRCLE",  # backspace = back/circle
    b"z": "CROSS", b"x": "CIRCLE", b"c": "SQUARE", b"v": "TRIANGLE",
    b"h": "PS", b"p": "OPTIONS", b"t": "TOUCHPAD", b"g": "SHARE",
    b"1": "L1", b"2": "L2", b"9": "R1", b"0": "R2",
}
_REMOTE_QUIT = {b"q", b"\x03", b"\x1b"}

_REMOTE_LEGEND = """\
Interactive remote — single keypress sends a tap. 'q' or Esc to quit.

  Arrow keys : D-pad            Enter/Space : CROSS (X)
  z : CROSS   x : CIRCLE         Backspace   : CIRCLE (back)
  c : SQUARE  v : TRIANGLE
  h : PS/home p : OPTIONS        t : TOUCHPAD   g : SHARE/create
  1 : L1  2 : L2  9 : R1  0 : R2
"""


def _parse_remote(buf: bytes):
    """Yield (action) tuples from a raw stdin chunk. action is a button name
    or the string 'QUIT'."""
    i = 0
    n = len(buf)
    while i < n:
        # Try a 3-byte escape sequence first (arrow keys).
        three = buf[i:i + 3]
        if three in _REMOTE_KEYS:
            yield _REMOTE_KEYS[three]
            i += 3
            continue
        one = buf[i:i + 1]
        if one in _REMOTE_QUIT:
            yield "QUIT"
            return
        if one in _REMOTE_KEYS:
            yield _REMOTE_KEYS[one]
        i += 1


async def _remote(ps5: PS5) -> None:
    import termios
    import tty

    if not sys.stdin.isatty():
        raise PS5Error("`remote` needs an interactive terminal (a TTY).")

    fd = sys.stdin.fileno()
    old_attr = termios.tcgetattr(fd)
    loop = asyncio.get_running_loop()
    queue: "asyncio.Queue[bytes]" = asyncio.Queue()

    def _on_readable():
        try:
            data = os.read(fd, 64)
        except OSError:
            return
        if data:
            queue.put_nowait(data)

    async with ps5.session() as controller:
        print(_REMOTE_LEGEND)
        print(f"Connected to {ps5.host} as {ps5.user}. Ready.\n")
        tty.setcbreak(fd)
        loop.add_reader(fd, _on_readable)
        try:
            while True:
                chunk = await queue.get()
                for action in _parse_remote(chunk):
                    if action == "QUIT":
                        print("\nDisconnecting.")
                        return
                    await controller.async_button(action, "tap")
                    print(f"  {action}        ", end="\r", flush=True)
        finally:
            loop.remove_reader(fd)
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attr)


# ------------------------------------------------------------------- arg parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ps5rmtctl",
        description="Blind PS5 remote control over PS Remote Play.",
    )
    p.add_argument("--host", help="PS5 IP address (overrides saved default)")
    p.add_argument("--user", help="PSN online-id (overrides saved default)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("discover", help="Find Remote Play devices on the LAN").set_defaults(func=cmd_discover)
    sub.add_parser("status", help="Show console status").set_defaults(func=cmd_status)
    sub.add_parser("accounts", help="List stored PSN accounts").set_defaults(func=cmd_accounts)
    sub.add_parser("buttons", help="List valid button names").set_defaults(func=cmd_buttons)

    sp = sub.add_parser("login", help="Authenticate a PSN account (one-time)")
    sp.add_argument("--redirect", help="Post-login redirect URL (else prompts)")
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("register", help="Link this console using the 8-digit PIN")
    sp.add_argument("--pin", help="8-digit Link Device PIN (else prompts)")
    sp.set_defaults(func=cmd_register)

    sp = sub.add_parser("setup", help="Guided one-time setup")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("wake", help="Wake console from rest mode")
    sp.add_argument("--timeout", type=float, default=60.0)
    sp.set_defaults(func=cmd_wake)

    sp = sub.add_parser("tap", help="Tap one or more buttons (e.g. tap down down cross)")
    sp.add_argument("buttons", nargs="+", help="Button names/aliases")
    sp.add_argument("--delay", type=float, default=0.1, help="press->release hold (s)")
    sp.add_argument("--gap", type=float, default=0.12, help="pause between taps (s)")
    sp.add_argument("--wake", action="store_true", help="Wake console first")
    sp.add_argument("--timeout", type=float, default=60.0)
    sp.set_defaults(func=cmd_tap)

    sp = sub.add_parser("hold", help="Press and hold a button")
    sp.add_argument("button")
    sp.add_argument("--duration", type=float, default=1.0, help="hold time (s)")
    sp.add_argument("--wake", action="store_true", help="Wake console first")
    sp.add_argument("--timeout", type=float, default=60.0)
    sp.set_defaults(func=cmd_hold)

    sp = sub.add_parser("remote", help="Interactive keyboard remote (low latency)")
    sp.add_argument("--wake", action="store_true", help="Wake console first")
    sp.add_argument("--timeout", type=float, default=60.0)
    sp.set_defaults(func=cmd_remote)

    sp = sub.add_parser("serve", help="Run the network control server (warm session + web UI + API)")
    sp.add_argument("--bind", default="0.0.0.0", help="Interface to bind (use your Tailscale IP to restrict access)")
    sp.add_argument("--port", type=int, default=8645)
    sp.add_argument("--token", help="API token (else env PS5RMTCTL_TOKEN, else config, else generated)")
    sp.add_argument("--idle-timeout", type=float, default=120.0,
                    help="Seconds of inactivity before auto-releasing the session (0 = never)")
    sp.set_defaults(func=cmd_serve)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except UnknownButton as exc:
        return _err(str(exc))
    except PS5Error as exc:
        return _err(str(exc))
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
