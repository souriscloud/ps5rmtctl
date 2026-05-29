"""HTTP + WebSocket API server exposing a warm PS5 session over the network.

Designed to run on an always-on machine on the PS5's LAN (e.g. a desktop) and be
reached from any device, ideally over a private overlay network like Tailscale.

Endpoints (JSON):
    GET  /                 -> touch web UI (no auth; contains no secrets)
    GET  /api/buttons      -> valid button names (no auth)
    GET  /api/status       -> console + session status            (auth)
    POST /api/wake         -> wake console from rest               (auth)
    POST /api/tap          {buttons:[...], delay?, gap?}           (auth)
    POST /api/press        {button}                                (auth)
    POST /api/release      {button}                                (auth)
    POST /api/hold         {button, duration?}                     (auth)
    GET  /ws               -> WebSocket; low-latency input stream  (auth)

Auth: a bearer token, supplied as ``Authorization: Bearer <token>`` or a
``?token=`` query parameter (the latter so browsers/WebSockets/PWAs can connect).
Bind to your Tailscale IP to keep it off the open LAN.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
from typing import Optional

from aiohttp import WSMsgType, web

from .buttons import CANONICAL, UnknownButton
from .core import PS5Error
from .service import PS5Service
from .webui import INDEX_HTML

_LOGGER = logging.getLogger(__name__)

_PROTECTED_PREFIXES = ("/api/", "/ws")
_UNPROTECTED = ("/api/buttons",)


def _check_token(request: web.Request, token: str) -> bool:
    supplied = request.headers.get("Authorization", "")
    if supplied.startswith("Bearer "):
        supplied = supplied[len("Bearer "):]
    if not supplied:
        supplied = request.query.get("token", "")
    return hmac.compare_digest(supplied, token)


@web.middleware
async def _auth_middleware(request: web.Request, handler):
    token = request.app["token"]
    path = request.path
    needs_auth = path in _PROTECTED_PREFIXES or path.startswith("/api/")
    if path in _UNPROTECTED:
        needs_auth = False
    if needs_auth and not _check_token(request, token):
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


def _service(request: web.Request) -> PS5Service:
    return request.app["service"]


async def _run_action(coro):
    """Await a service action and map errors to JSON responses."""
    try:
        result = await coro
        return web.json_response({"ok": True, "result": result})
    except UnknownButton as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except PS5Error as exc:
        return web.json_response({"error": str(exc)}, status=502)


# ----------------------------------------------------------------- HTTP routes
async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def handle_buttons(request: web.Request) -> web.Response:
    return web.json_response({"buttons": CANONICAL})


async def handle_status(request: web.Request) -> web.Response:
    try:
        return web.json_response(await _service(request).status())
    except PS5Error as exc:
        return web.json_response({"error": str(exc)}, status=502)


async def handle_wake(request: web.Request) -> web.Response:
    return await _run_action(_service(request).wake())


async def handle_connect(request: web.Request) -> web.Response:
    return await _run_action(_service(request).connect())


async def handle_disconnect(request: web.Request) -> web.Response:
    return await _run_action(_service(request).disconnect())


async def handle_tap(request: web.Request) -> web.Response:
    data = await request.json()
    buttons = data.get("buttons") or ([data["button"]] if data.get("button") else [])
    if not buttons:
        return web.json_response({"error": "no buttons given"}, status=400)
    return await _run_action(
        _service(request).tap(
            buttons,
            delay=float(data.get("delay", 0.1)),
            gap=float(data.get("gap", 0.08)),
        )
    )


async def handle_press(request: web.Request) -> web.Response:
    data = await request.json()
    return await _run_action(_service(request).press(data["button"]))


async def handle_release(request: web.Request) -> web.Response:
    data = await request.json()
    return await _run_action(_service(request).release(data["button"]))


async def handle_hold(request: web.Request) -> web.Response:
    data = await request.json()
    return await _run_action(
        _service(request).hold(data["button"], duration=float(data.get("duration", 1.0)))
    )


# ------------------------------------------------------------------- WebSocket
async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    service = _service(request)
    _LOGGER.info("WebSocket client connected: %s", request.remote)
    async for msg in ws:
        if msg.type != WSMsgType.TEXT:
            continue
        try:
            data = msg.json()
            action = data.get("action")
            if action == "tap":
                buttons = data.get("buttons") or [data["button"]]
                await service.tap(buttons, delay=float(data.get("delay", 0.1)))
            elif action == "press":
                await service.press(data["button"])
            elif action == "release":
                await service.release(data["button"])
            elif action == "hold":
                await service.hold(data["button"], duration=float(data.get("duration", 1.0)))
            elif action == "wake":
                await service.wake()
            elif action == "connect":
                await service.connect()
            elif action == "disconnect":
                await service.disconnect()
            else:
                await ws.send_json({"error": f"unknown action: {action!r}"})
                continue
            await ws.send_json({"ok": True, "action": action})
        except (UnknownButton, KeyError) as exc:
            await ws.send_json({"error": f"bad request: {exc}"})
        except PS5Error as exc:
            await ws.send_json({"error": str(exc)})
    _LOGGER.info("WebSocket client disconnected: %s", request.remote)
    return ws


def build_app(service: PS5Service, token: str) -> web.Application:
    app = web.Application(middlewares=[_auth_middleware])
    app["service"] = service
    app["token"] = token
    app.add_routes([
        web.get("/", handle_index),
        web.get("/api/buttons", handle_buttons),
        web.get("/api/status", handle_status),
        web.post("/api/wake", handle_wake),
        web.post("/api/connect", handle_connect),
        web.post("/api/disconnect", handle_disconnect),
        web.post("/api/tap", handle_tap),
        web.post("/api/press", handle_press),
        web.post("/api/release", handle_release),
        web.post("/api/hold", handle_hold),
        web.get("/ws", handle_ws),
    ])

    async def _on_startup(app: web.Application):
        app["idle_task"] = asyncio.ensure_future(service.run_idle_watcher())

    async def _on_cleanup(app: web.Application):
        task = app.get("idle_task")
        if task:
            task.cancel()
        await service.close()

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


def serve(service: PS5Service, token: str, host: str = "0.0.0.0", port: int = 8645) -> None:
    """Blocking: run the API server until interrupted."""
    app = build_app(service, token)
    web.run_app(app, host=host, port=port, print=None)
