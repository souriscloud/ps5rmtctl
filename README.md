# ps5rmtctl

Blind (no-video) remote control for a PlayStation 5 over the local network,
built on Sony's **PS Remote Play** protocol via
[`pyremoteplay`](https://github.com/ktnrg45/pyremoteplay).

Emulates the buttons you'd press on a DualSense — D-pad, face buttons,
shoulders/triggers, PS/home, OPTIONS — from your Mac's terminal. No controller
hardware and no video decoding involved.

## Why Remote Play (and not Bluetooth)

Impersonating a DualSense over Bluetooth requires defeating Sony's controller
authentication (only partially reverse-engineered) and a Bluetooth-peripheral
mode macOS doesn't cleanly expose. Remote Play is the supported, working path:
it carries controller input to the console over the network, and the console
can even be woken from rest mode.

## Requirements

- A PS5 with **Remote Play enabled** (Settings → System → Remote Play).
- A PSN account (used once to mint credentials).
- The Mac and PS5 on the same network.
- Python 3.9 (the bundled `.venv` uses the system Python, where every native
  dependency has a prebuilt arm64 wheel).

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

> Note: `pyee` is pinned `<9` because pyremoteplay 0.7.6 imports
> `ExecutorEventEmitter` from the old top-level location.

## One-time setup

Guided:

```bash
.venv/bin/python -m ps5rmtctl setup
```

Or step by step:

```bash
# 1. find your console
.venv/bin/python -m ps5rmtctl discover

# 2. authenticate a PSN account (opens a URL; paste the post-login redirect URL)
.venv/bin/python -m ps5rmtctl login

# 3. on the PS5: Settings -> System -> Remote Play -> Link Device  (shows an 8-digit PIN)
.venv/bin/python -m ps5rmtctl register --host 192.168.0.155 --pin 12345678
```

PSN account + per-console registration keys are stored by pyremoteplay in
`~/.pyremoteplay/.profile.json`. Our own saved defaults (host/user) live in
`~/.ps5rmtctl/config.json` (override that dir with `PS5RMTCTL_HOME`), so later
commands need no flags.

## Usage

```bash
.venv/bin/python -m ps5rmtctl status              # is it on? what's running?
.venv/bin/python -m ps5rmtctl wake                # wake from rest mode

.venv/bin/python -m ps5rmtctl tap cross           # single button
.venv/bin/python -m ps5rmtctl tap down down cross # a sequence in one session
.venv/bin/python -m ps5rmtctl hold r2 --duration 2
.venv/bin/python -m ps5rmtctl tap home --wake     # wake first, then press

.venv/bin/python -m ps5rmtctl remote              # interactive keyboard remote
.venv/bin/python -m ps5rmtctl buttons             # list valid names
```

### Button names

Friendly aliases map onto DualSense buttons:

| You type | Button |
|---|---|
| `up` `down` `left` `right` | D-pad |
| `cross`/`x` `circle`/`o` `square` `triangle` | face buttons |
| `l1` `l2` `r1` `r2` `l3` `r3` | shoulders / triggers / stick clicks |
| `home`/`ps` | PS button |
| `option`/`options`/`pause` | OPTIONS |
| `share`/`create` | Create button |
| `touchpad` | touchpad click |

> The DualSense has no dedicated *pause* button; `pause` is mapped to
> `OPTIONS` (same as `option`). Change this in `ps5rmtctl/buttons.py` if you'd
> rather it be e.g. the touchpad.

### Interactive remote keys

Arrow keys = D-pad · Enter/Space = CROSS · Backspace = CIRCLE ·
`z`/`x`/`c`/`v` = CROSS/CIRCLE/SQUARE/TRIANGLE · `h` = PS · `p` = OPTIONS ·
`t` = TOUCHPAD · `g` = SHARE · `1`/`2`/`9`/`0` = L1/L2/R1/R2 · `q`/Esc = quit.

## Network control server (the daemon)

For an always-available remote, run the server on an always-on machine on the
PS5's LAN and reach it from any device — ideally over a private overlay network
like **Tailscale**, so it's encrypted and low-latency from anywhere.

```bash
# bind to your Tailscale IP so it's not exposed on the open LAN
.venv/bin/python -m ps5rmtctl serve --bind 100.x.y.z --port 8645
```

It prints an API token (generated and saved on first run). Then on any device:

```
http://<server-ip>:8645/?token=<token>
```

That serves a touch button pad (add it to your phone's home screen for an
app-like remote). The page caches the token, so afterwards just open the host.

**On-demand session (does not hog the console).** The server does *not* hold a
Remote Play session open 24/7. It links only when you use it:

- Pressing a button auto-links; the **Link/Unlink** button links/releases manually.
- After `--idle-timeout` seconds of inactivity (default 120) the session is
  auto-released, freeing the console for the official Remote Play app or anyone else.
- Only one Remote Play session can exist per console at a time — so while linked,
  the official app can't connect; Unlink (or wait for idle) to hand it back.

**API** (token via `Authorization: Bearer <t>` header or `?token=<t>`):

| Method | Path | Body | Purpose |
|---|---|---|---|
| GET | `/api/status` | | console + session state |
| POST | `/api/connect` / `/api/disconnect` | | link / release the session |
| POST | `/api/tap` | `{"buttons":["down","cross"]}` | tap a sequence |
| POST | `/api/press` / `/api/release` | `{"button":"r2"}` | hold support |
| POST | `/api/hold` | `{"button":"r2","duration":2}` | press+wait+release |
| POST | `/api/wake` | | wake from rest |
| GET | `/ws` | (WebSocket) | low-latency input stream |

The web UI uses the WebSocket with press/release pairs, so buttons feel like a
real controller (hold to repeat-scroll, tap to select).

### Deploying on the always-on desktop

The session credentials are not machine-bound — copy the profile you already
made, or re-run `login`/`register` on the desktop.

**Windows** (the awkward dep is `netifaces`, which only has Windows wheels up to
Python 3.8):

1. Install **Python 3.8, 64-bit** from python.org (Python 3.9+ on Windows would
   need MSVC build tools to compile `netifaces`).
2. `py -3.8 -m venv .venv && .venv\Scripts\pip install -e .`
3. Copy `~/.pyremoteplay/.profile.json` (from the Mac) to
   `%USERPROFILE%\.pyremoteplay\.profile.json` — or run `login` + `register` there.
4. `.venv\Scripts\python -m ps5rmtctl --host 192.168.0.155 --user SourisCLOUD serve --bind <tailscale-ip>`
5. Allow Python through Windows Firewall on the chosen port (private networks).
6. To run at boot: Task Scheduler (trigger "At log on") or a service wrapper like NSSM.

> The interactive `remote` CLI is Unix-only (it uses `termios`); `serve` is
> cross-platform. On the Windows desktop you'll use `serve`.

**Linux** is simplest (`netifaces` builds/has wheels readily) — same steps with
Python 3.9–3.11.

### Docker (Alpine)

A `Dockerfile` (Alpine, ~176 MB) and `docker-compose.yml` are included.

```bash
# your host/user/token go in .env (gitignored)
cp .env.example .env && $EDITOR .env
# seed the registration the container will use (copy the profile you made)
mkdir -p data/.pyremoteplay && cp ~/.pyremoteplay/.profile.json data/.pyremoteplay/
docker compose up -d --build
```

Open `http://<docker-host>:8645/?token=<token>`.

Notes, all verified by building/running the image:

- **Python 3.9 base** — `netifaces` doesn't compile on 3.11+'s C API.
- **Alpine/musl + gcc 14** needs `CFLAGS=-Wno-int-conversion` (the Dockerfile
  sets it) because netifaces' unused `gateways()` assumes glibc's `struct
  msghdr`. For zero workarounds, swap the base to `python:3.9-slim` (Debian).
- **Networking actually works through Docker's NAT.** A full Remote Play session
  + button input was confirmed from inside a bridge-NAT'd container — because we
  only use unicast UDP (no broadcast). So the default bridge + `-p 8645:8645`
  works on Docker Desktop (Windows/macOS) *and* Linux.
- On a **Linux** Docker host you can instead use `network_mode: host` (drop the
  `ports:` block) to sit directly on the LAN. Host mode does nothing useful on
  Docker Desktop — keep bridge there.
- The console IP must be reachable from the container; `PS5RMTCTL_HOST` takes
  the LAN IP. Mount `./data:/data` to persist credentials (`HOME=/data` in the image).

> Fallback if a future Docker/WSL2 networking change ever breaks the UDP path on
> Windows: enable WSL2 **mirrored networking** (`.wslconfig` →
> `[wsl2]\nnetworkingMode=mirrored`), which puts WSL/containers directly on the
> host LAN.

## Architecture

```
cli.py      argparse front-end, interactive raw-key remote, `serve` command
core.py     PS5 class: status / register / wake / one-shot async session + tap/hold
service.py  PS5Service: warm, self-healing, on-demand session for the daemon
server.py   aiohttp REST + WebSocket API, token auth, idle auto-release
webui.py    self-contained touch web UI served at /
buttons.py  friendly-name -> canonical-button resolution
config.py   default host/user/token storage under ~/.ps5rmtctl

Dockerfile, docker-compose.yml   Alpine container deploy (Python 3.9, bridge net)
```

Status / registration / wake are synchronous (DDP UDP). The Remote Play session
is async and runs on an asyncio loop; `core.PS5.session()` is an async context
manager that connects with **no AV receiver** (blind) and yields a ready
`Controller`.

## Tests

```bash
.venv/bin/python tests/test_offline.py   # no hardware/network needed
```

## Limitations / notes

- One Remote Play session at a time; while linked, close/avoid the official
  Remote Play app (and vice versa). Unlink to hand the console back.
- The one-shot `tap`/`hold` CLI commands open and close a session each time (a
  few seconds of handshake). For rapid input use `remote` (holds a session) or
  the `serve` daemon (warm, on-demand session) + web UI.
- Phone control is the `serve` web UI over your network/Tailscale — no native
  app or Swift protocol re-port needed.
