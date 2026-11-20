"""Free open-source online anime meme database client and `/p` Discord slash command."""

from src.memes.catalog import (
    FALLBACK_MEMES,
    MEME_SOURCES,
    AnimeMemeService,
    MemeEntry,
    MemeSourceSpec,
    normalize_search_text,
)
from src.memes.commands import (
    AnimeMemeView,
    build_meme_embed,
    create_meme_commands,
    register_meme_commands,
)

__all__ = [
    "AnimeMemeService",
    "AnimeMemeView",
    "FALLBACK_MEMES",
    "MEME_SOURCES",
    "MemeEntry",
    "MemeSourceSpec",
    "build_meme_embed",
    "create_meme_commands",
    "normalize_search_text",
    "register_meme_commands",
]
