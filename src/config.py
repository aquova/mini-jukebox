# Mini-Jukebox
# config.py
# Written by blueberry et al., 2022
# https://github.com/StardewValleyDiscord/mini-jukebox

"""
Contents:
    Runtime
    Bot
    Tokens
    Logging
    Discord
    FFMPEG
    Jukebox
    Lyrics
    DB
    YTDL
"""

import os

import json
from typing import List

import discord
import yt_dlp


# Runtime

CURRENT_DIR = os.path.dirname(__file__)
ASSETS_PATH = os.path.join(CURRENT_DIR, "assets")

TEMP_DIR: str = "/private/temp"
"""Relative path to temporary folder used to store cached media data."""
LOG_DIR: str = "/private/logs"
"""Relative path to temporary folder used to store session logs."""
CONFIG_PATH: str = "/private/config.json"
"""Relative path to data file used for bot configuration."""
STRINGS_PATH = os.path.join(ASSETS_PATH, "strings.json")
"""Relative path to data file used for logging, formatting, reply, and flavour strings."""
PINS_PATH = os.path.join(ASSETS_PATH, "pins.json")
"""Relative path to data file used for pinned message contents in text channel."""
DATABASE_PATH: str = "/private/jukebox.db"
"""Relative path to database file used to store usage history."""
LOG_PATH: str = os.path.join(LOG_DIR, "discord.log")
"""Relative path to runtime log files."""

# Bot

COG_COMMANDS: str = "Jukebox Commands"
"""Name of commands cog."""
PACKAGE_COMMANDS: str = "jukebox_commands"
"""Name of commands package."""

# Parse config file
with open(file=CONFIG_PATH, mode="r") as config_file:
    cfg: dict = json.load(config_file)

# Tokens

TOKEN_DISCORD: str = cfg["tokens"]["discord"]
"""Token used to run Discord client."""

# Logging

LOG_SIZE_MEBIBYTES: float = cfg["logging"]["file_size_mebibytes"]
LOG_BACKUP_COUNT: int = cfg["logging"]["backup_count"]

# Discord

DISCORD_INTENTS: discord.Intents = discord.Intents(
    guilds=True,
    guild_messages=True,
    guild_reactions=True,
    message_content=True,
    members=True,
    emojis=True,
    voice_states=True
)
"""List of allowed and disallowed intents when running Discord client."""

COMMAND_PREFIX: str = cfg["discord"]["command_prefix"]
"""Prefix required for all messages sent in command channel."""

ROLE_MAINTENANCE: int = cfg["discord"]["roles"]["maintenance"]
"""Discord role ID for commands and features requiring admin privileges."""
ROLE_ADMIN: int = cfg["discord"]["roles"]["admin"]
"""Discord role ID for commands and features requiring admin privileges."""
ROLE_TRUSTED: int = cfg["discord"]["roles"]["trusted"]
"""Discord role ID for commands and features requiring elevated privileges."""
ROLE_DEFAULT: int = cfg["discord"]["roles"]["default"]
"""Discord role ID for commands requiring basic privileges."""
ROLE_LISTEN: int = cfg["discord"]["roles"]["listen"]
"""Discord role ID for a role with no privileges."""
ROLE_JUKEBOX: int = cfg["discord"]["roles"]["bonus"]
"""Discord role ID for bonus flavour role themed around the jukebox."""

CHANNEL_VOICE: int = cfg["discord"]["channels"]["voice"]
"""Discord channel ID for the voice channel used for media playback."""
CHANNEL_TEXT: int = cfg["discord"]["channels"]["text"]
"""Discord channel ID for the text channel used for command interactions."""
CHANNEL_LOG: int = cfg["discord"]["channels"]["log"]
"""Discord channel ID used to send status and event logging if configured."""
CHANNEL_BULLETIN: int = cfg["discord"]["channels"]["bulletin"]
"""Discord channel ID used to send bulletins and news updates."""

CORO_TIMEOUT: int = cfg["discord"]["coro_timeout_seconds"]
"""Duration in seconds before coroutines are timed-out."""
VOICE_TIMEOUT: int = cfg["discord"]["voice_timeout_seconds"]
"""Duration in seconds before voice connections are timed-out."""
VOICE_RECONNECT: bool = cfg["discord"]["voice_reconnect_enabled"]
"""Whether to automatically reconnect to voice channels after time-out."""

LOGGING_FILE: bool = cfg["discord"]["logging_file"]
"""Whether logging usage, events, and tracebacks to file is enabled."""
LOGGING_CHANNEL: bool = cfg["discord"]["logging_channel"] and CHANNEL_LOG is not None
"""Whether a logging channel is configured and enabled for status and commands."""
LOGGING_CONSOLE: bool = cfg["discord"]["logging_console"]
"""Whether logging status and commands to console is enabled."""

# FFMPEG

FFMPEG_BEFORE_OPTIONS: str = cfg["ffmpeg"]["before_options"]
"""Command line parameters for FFMPEG process."""
FFMPEG_OPTIONS: str = cfg["ffmpeg"]["options"]
"""Command line parameters for FFMPEG media tasks."""

# Jukebox

PLAYLIST_MULTIQUEUE: bool = cfg["jukebox"]["multiqueue_enabled"]
"""Whether multiqueue is enabled, allowing a more even playback of tracks from different users."""
PLAYLIST_STREAMING: bool = cfg["jukebox"]["streaming_enabled"]
"""Whether media data will be streamed from external sources, or preloaded and sourced from local drive."""
PLAYLIST_LOOPING: bool = cfg["jukebox"]["looping_enabled"]
"""Whether queues may be toggled to loop their tracks, reappending played tracks."""
PLAYLIST_PAUSING: bool = cfg["jukebox"]["pausing_enabled"]
"""Whether queues may be toggled to pause playback until next unpaused."""
TRACK_DURATION_LIMIT: int = cfg["jukebox"]["track_duration_limit_seconds"]
"""Duration in seconds for track runtime before being blocked from the queue."""

# Lyrics

TOKEN_LYRICS: str = cfg["tokens"]["lyrics"]
"""Personal access token for lyrics provider."""
LYRICS_LINE_LIMIT: int = cfg["lyrics"]["line_limit"]
"""Maximum number of lines to print to a chat embed."""
LYRICS_CHARACTER_LIMIT: int = cfg["lyrics"]["character_limit"]
"""Maximum number of characters to print to a chat embed."""
LYRICS_SEARCH_TIMEOUT: int = cfg["lyrics"]["response_timeout_seconds"]
"""Duration in seconds before lyrics provider requests are timed-out."""
LYRICS_VERBOSE: bool = cfg["lyrics"]["verbose"]
"""Whether lyrics provider will use verbose logging."""

# DB

# Packages

PACKAGE_CHECKS: List[str] = cfg["packages"]["check"]
"""List of package names to list on version checks."""

# YTDL

YTDL_ALLOWED_EXTRACTORS: List[str] = cfg["ytdl"]["allowed_extractors"]
"""List of permitted media extractors, used to enforce a list of trusted domains to source media from."""
YTDL_OPTIONS: dict = cfg["ytdl"]["options"]
"""Flags and values for YTDL connection process."""
YTDL_AMBIGUOUS_ATTEMPTS: int = cfg["ytdl"]["ambiguous_attempts"]
YTDL_AMBIGUOUS_RESULTS: int = cfg["ytdl"]["ambiguous_results"]
