"""Blind PS5 remote control core.

Thin, task-focused wrapper around :class:`pyremoteplay.device.RPDevice` that:

* discovers / queries console status,
* performs one-time PSN OAuth + console registration,
* wakes the console from rest mode,
* opens a Remote Play session **without** a video receiver and sends button input.

Status / registration / wake operations are synchronous (they use DDP UDP
sockets). Only the session + button control is async, because the Remote Play
session must run on an asyncio event loop.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from pyremoteplay.device import RPDevice
from pyremoteplay.oauth import get_login_url, get_user_account
from pyremoteplay.profile import Profiles, format_user_account

from . import config
from .buttons import resolve

_LOGGER = logging.getLogger(__name__)

# Time to wait for the session handshake to complete once connected.
SESSION_TIMEOUT = 7.0


class PS5Error(RuntimeError):
    """Raised for control-flow errors talking to the console."""


class PS5:
    """A single PS5 console reachable on the LAN.

    :param host: IP address (or hostname) of the console.
    :param user: PSN online-id to authenticate as. Optional for status-only use.
    """

    def __init__(self, host: str, user: Optional[str] = None):
        config.init_profiles()
        self.host = host
        self.user = user
        self.device = RPDevice(host)

    # ------------------------------------------------------------------ status
    def refresh(self) -> dict:
        """Poll console status over DDP. Returns the raw status dict (or {})."""
        return self.device.get_status() or {}

    @property
    def is_on(self) -> bool:
        return self.device.is_on

    @property
    def status_summary(self) -> str:
        s = self.device.status or {}
        if not s:
            return "unreachable"
        state = s.get("status", "?")
        app = s.get("running-app-name")
        base = f"{self.device.host_type or '?'} '{self.device.host_name or '?'}' — {state}"
        return f"{base} (running: {app})" if app else base

    @property
    def registered_users(self) -> List[str]:
        """PSN users that have been registered against *this* console."""
        self.device.get_status()  # populates mac address used as the key
        return self.device.get_users()

    # ------------------------------------------------------------ registration
    @staticmethod
    def login_url() -> str:
        """Return the PSN OAuth login URL to open in a browser."""
        return get_login_url()

    @staticmethod
    def add_account(redirect_url: str) -> str:
        """Exchange the post-login redirect URL for PSN account credentials.

        Returns the PSN online-id (username) that was stored. Call once per PSN
        account; the resulting profile is reused for all consoles.
        """
        config.init_profiles()
        account = get_user_account(redirect_url)
        if not account:
            raise PS5Error(
                "Could not get PSN account from that redirect URL. Make sure you "
                "copied the full URL of the 'redirect' page after logging in."
            )
        profile = format_user_account(account)
        if profile is None:
            raise PS5Error("Could not build a user profile from the PSN account data.")
        profiles = Profiles.load()
        profiles.update_user(profile)
        profiles.save()
        return profile.name

    @staticmethod
    def list_accounts() -> List[str]:
        config.init_profiles()
        return Profiles.load().usernames

    def register(self, user: str, pin: str) -> None:
        """Link this console to ``user`` using the 8-digit PIN from the console.

        Get the PIN on the PS5: Settings -> System -> Remote Play ->
        Link Device (shows an 8-digit code).
        """
        if not (pin.isnumeric() and len(pin) == 8):
            raise PS5Error("PIN must be exactly 8 digits.")
        status = self.refresh()
        if not status:
            raise PS5Error(f"Console at {self.host} is not reachable.")
        if status.get("status-code") != 200:
            raise PS5Error("Console must be powered on to register.")
        result = self.device.register(user, pin)
        if not result:
            raise PS5Error("Registration failed (check the PIN and that you are logged in to PSN on the console).")
        self.user = user

    # -------------------------------------------------------------------- wake
    def wake(self, timeout: float = 60.0) -> bool:
        """Wake the console from rest mode. Returns True once it is on."""
        self.refresh()
        if self.device.is_on:
            return True
        if not self.user:
            raise PS5Error("A registered user is required to wake the console.")
        self.device.wakeup(user=self.user)
        return self.device.wait_for_wakeup(timeout)

    # ---------------------------------------------------------------- sessions
    @asynccontextmanager
    async def session(self, timeout: float = SESSION_TIMEOUT):
        """Async context manager yielding a ready, connected Controller.

        Opens a video-less Remote Play session, waits for the handshake, yields
        the :class:`~pyremoteplay.controller.Controller`, and always disconnects
        on exit.
        """
        if not self.user:
            raise PS5Error("A registered user is required to open a session.")
        self.refresh()
        if not self.device.is_on:
            raise PS5Error("Console is not on. Wake it first (`wake`) or turn it on.")

        loop = asyncio.get_running_loop()
        # receiver=None => no video/audio decoding (blind control).
        sess = self.device.create_session(self.user, loop=loop, receiver=None)
        if sess is None:
            raise PS5Error(
                f"Could not create session. Is user '{self.user}' registered with this console?"
            )
        if not await self.device.connect():
            err = getattr(self.device.session, "error", "unknown error")
            raise PS5Error(f"Session failed to start: {err}")
        if not await self.device.async_wait_for_session(timeout):
            self.device.disconnect()
            raise PS5Error("Timed out waiting for the session to become ready.")
        try:
            yield self.device.controller
        finally:
            self.device.disconnect()

    # ----------------------------------------------------------- button helpers
    async def tap(self, *names: str, delay: float = 0.1, gap: float = 0.12) -> None:
        """Tap one or more buttons in sequence within a single session.

        :param delay: press->release hold time for each tap.
        :param gap: pause between consecutive taps in the sequence.
        """
        buttons = [resolve(n) for n in names]
        async with self.session() as controller:
            for i, button in enumerate(buttons):
                await controller.async_button(button, "tap", delay=delay)
                if gap and i < len(buttons) - 1:
                    await asyncio.sleep(gap)

    async def hold(self, name: str, duration: float = 1.0) -> None:
        """Press a button, hold for ``duration`` seconds, then release."""
        button = resolve(name)
        async with self.session() as controller:
            await controller.async_button(button, "press")
            try:
                await asyncio.sleep(duration)
            finally:
                await controller.async_button(button, "release")
