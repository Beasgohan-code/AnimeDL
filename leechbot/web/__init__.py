# AnimeDL — leech module. Based on LeechBot (MIT License) — see LICENSES/LeechBot-LICENSE.

"""
Web dashboard module for LeechBot.

Provides a REST API + WebSocket server for the HTML dashboard.
"""

from .server import start_web_server, broadcast_update

__all__ = ["start_web_server", "broadcast_update"]
