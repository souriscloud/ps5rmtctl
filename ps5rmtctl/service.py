"""Warm, self-healing Remote Play session for daemon/server use.

Unlike :meth:`core.PS5.session` (which opens and tears down a session per call),
``PS5Service`` holds ONE session open and reuses it, so a button press is a
single packet with no per-press handshake. It transparently re-establishes the
session if the console slept or the network blipped (``ensure_connected``), and
serializes all input through an asyncio lock.

Everything runs on a single asyncio event loop (the daemon's) — the Remote Play
session is created with that loop, so there is no cross-thread access.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable, List, Optional

from .buttons import resolve
from .core import PS5, PS5Error

_LOGGER = logging.getLogger(__name__)


class PS5Service:
    """Owns a long-lived Remote Play session to one console."""

    def __init__(
        self,
        host: str,
        user: str,
        *,
        wake_timeout: float = 60.0,
        session_timeout: float = 7.0,
        idle_timeout: float = 120.0,
    ):
        self.ps5 = PS5(host, user)
        self.host = host
        self.user = user
        self.wake_timeout = wake_timeout
        self.session_timeout = session_timeout
        # Seconds of inactivity after which the session is auto-released so it
        # doesn't block other Remote Play clients. 0 disables auto-release.
        self.idle_timeout = idle_timeout
        self._last_activity = 0.0
        # Created lazily so the Lock binds to the running loop (matters on 3.9,
        # where asyncio.Lock() binds at construction time, not first await).
        self._lock_obj: Optional[asyncio.Lock] = None

    @property
    def _lock(self) -> asyncio.Lock:
        if self._lock_obj is None:
            self._lock_obj = asyncio.Lock()
        return self._lock_obj

    @property
    def device(self):
        return self.ps5.device

    @property
    def controller(self):
        return self.device.controller

    def _is_ready(self) -> bool:
        sess = self.device.session
        return sess is not None and sess.is_ready

    def _touch(self) -> None:
        self._last_activity = asyncio.get_running_loop().time()

    async def _wake(self) -> None:
        if self.device.is_on:
            return
        _LOGGER.info("Console is in rest mode; sending wakeup")
        self.device.wakeup(user=self.user)  # quick DDP packet
        if not await self.device.async_wait_for_wakeup(self.wake_timeout):
            raise PS5Error("Timed out waiting for the console to wake.")

    async def ensure_connected(self, *, wake: bool = True) -> None:
        """(Re)establish the warm session if it isn't ready. Holds no lock itself."""
        if self._is_ready():
            return
        # Drop any dead session and refresh status (also populates the MAC used
        # as the per-console key for create_session / wakeup).
        self.device.disconnect()
        await self.device.async_get_status()
        if not self.device.is_on:
            if not wake:
                raise PS5Error("Console is off and wake is disabled.")
            await self._wake()
            await self.device.async_get_status()

        loop = asyncio.get_running_loop()
        sess = self.device.create_session(self.user, loop=loop, receiver=None)
        if sess is None:
            raise PS5Error(
                f"Could not create session. Is user '{self.user}' registered with this console?"
            )
        if not await self.device.connect():
            err = getattr(self.device.session, "error", "unknown error")
            self.device.disconnect()
            raise PS5Error(f"Session failed to start: {err}")
        if not await self.device.async_wait_for_session(self.session_timeout):
            self.device.disconnect()
            raise PS5Error("Timed out waiting for the session to become ready.")
        _LOGGER.info("Warm session ready: %s as %s", self.host, self.user)

    # ------------------------------------------------------- lifecycle (on-demand)
    async def connect(self) -> dict:
        """Explicitly establish the session (waking the console if needed)."""
        async with self._lock:
            await self.ensure_connected()
            self._touch()
            return self._status_locked()

    async def disconnect(self) -> dict:
        """Release the session immediately so other Remote Play clients can connect."""
        async with self._lock:
            self.device.disconnect()
            _LOGGER.info("Session released on request")
            return self._status_locked()

    # ----------------------------------------------------------------- actions
    async def tap(self, names: Iterable[str], *, delay: float = 0.1, gap: float = 0.08) -> List[str]:
        buttons = [resolve(n) for n in names]
        async with self._lock:
            await self.ensure_connected()
            for i, button in enumerate(buttons):
                await self.controller.async_button(button, "tap", delay=delay)
                if gap and i < len(buttons) - 1:
                    await asyncio.sleep(gap)
            self._touch()
        return buttons

    async def press(self, name: str) -> str:
        button = resolve(name)
        async with self._lock:
            await self.ensure_connected()
            await self.controller.async_button(button, "press")
            self._touch()
        return button

    async def release(self, name: str) -> str:
        button = resolve(name)
        async with self._lock:
            await self.ensure_connected()
            await self.controller.async_button(button, "release")
            self._touch()
        return button

    async def hold(self, name: str, duration: float = 1.0) -> str:
        button = resolve(name)
        async with self._lock:
            await self.ensure_connected()
            await self.controller.async_button(button, "press")
            try:
                await asyncio.sleep(duration)
            finally:
                await self.controller.async_button(button, "release")
            self._touch()
        return button

    async def run_idle_watcher(self) -> None:
        """Background task: release the session after `idle_timeout` of inactivity."""
        if self.idle_timeout <= 0:
            return
        try:
            while True:
                await asyncio.sleep(min(self.idle_timeout, 15.0))
                if not self._is_ready():
                    continue
                idle = asyncio.get_running_loop().time() - self._last_activity
                if idle < self.idle_timeout:
                    continue
                async with self._lock:
                    idle = asyncio.get_running_loop().time() - self._last_activity
                    if self._is_ready() and idle >= self.idle_timeout:
                        self.device.disconnect()
                        _LOGGER.info("Released idle session after %.0fs", idle)
        except asyncio.CancelledError:
            pass

    async def wake(self) -> dict:
        async with self._lock:
            await self.device.async_get_status()
            await self._wake()
            return self._status_locked()

    async def status(self) -> dict:
        async with self._lock:
            await self.device.async_get_status()
            return self._status_locked()

    def _status_locked(self) -> dict:
        return {
            "host": self.host,
            "user": self.user,
            "on": self.device.is_on,
            "status": self.device.status_name,
            "app": self.device.app_name,
            "session_ready": self._is_ready(),
        }

    async def close(self) -> None:
        async with self._lock:
            self.device.disconnect()
            _LOGGER.info("Service closed; session disconnected")
