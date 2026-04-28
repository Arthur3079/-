"""GramGPT-style «combine» — multi-account Telegram automation on top of Sonya.

The existing :mod:`sonya` package implements the single-account OFM-chatter
(modules 4 Neuro-Chatting and 5 NeuroDialogs from the GramGPT feature set).

:mod:`sonya.combine` is where the remaining modules live:

- ``accounts``  — module 1 Account Manager
- ``warming``   — module 2 Account Warming
- ``commenting``— module 3 Neuro-Commenting
- ``reactions`` — module 6 Mass Reactions
- ``parsers``   — module 7 Parsers (users / channels / chats / messages)
- ``analytics`` — module 8 Analytics

Sprint 0 ships just the data layer plus a skeleton Telethon client pool; each
subsequent sprint fills in one module end-to-end (domain + REST routes + UI).
"""

from __future__ import annotations

__all__: list[str] = []
