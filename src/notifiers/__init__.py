"""Notificadores (borda de I/O): só enviam; o texto vem pronto de `src.transformers.notification`."""

from .telegram import TelegramError, TelegramSettings, send_messages, settings_from_env

__all__ = ["TelegramError", "TelegramSettings", "send_messages", "settings_from_env"]
