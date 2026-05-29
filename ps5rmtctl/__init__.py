"""ps5rmtctl - blind PS5 remote control over PS Remote Play.

This package wraps :mod:`pyremoteplay` to send controller button input to a PS5
on the local network. It deliberately does *not* decode the video/audio stream
("blind" control), which keeps latency low and avoids the heavy ``av`` /
``aiortc`` dependencies.
"""
from __future__ import annotations

import warnings

# pyremoteplay imports its video receiver eagerly and warns when PyAV is absent.
# We never decode video, so silence that and the LibreSSL urllib3 warning to keep
# CLI output clean. Match by message (not category) so we don't have to import
# urllib3 to get the warning class — importing it is what emits the warning in
# the first place, before any filter could catch it.
warnings.filterwarnings("ignore", message="av not installed")
warnings.filterwarnings("ignore", message=r"urllib3 v2 only supports OpenSSL.*")

from .core import PS5  # noqa: E402

__all__ = ["PS5"]
__version__ = "0.1.0"
