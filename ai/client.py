"""Shared Anthropic client."""

import anthropic

from core import config

_client = None


def get():
    global _client
    if _client is None:
        # Resolves ANTHROPIC_API_KEY, then an `ant auth login` profile.
        _client = anthropic.Anthropic()
    return _client


def settings():
    return config.load()["ai"]


def enabled():
    return settings()["enabled"]
