# Mini-Jukebox
# jukebox_commands.py
# Written by blueberry et al., 2022
# https://github.com/StardewValleyDiscord/mini-jukebox

"""
Contents:
    Votes
        Values
        Constants
        Init
        Utility functions
        Runtime events
    Command use restrictions
    Commands
        Constants
        Init
        Default user commands
        Trusted user commands
        Admin commands
        Vote finalisers
        Command utilities
    Utility functions
    Discord.py boilerplate
"""
from http.client import responses
from importlib import reload
from math import ceil
from typing import List, Dict, Union

import aiohttp
import discord
import yt_dlp
from bs4 import BeautifulSoup
from datetime import datetime

from discord import utils
from discord.ext import commands
from discord.ext.commands import Context

import config
import jukebox_checks
import jukebox_impl
import strings
from jukebox_checks import is_admin, is_trusted, is_default, is_voice_only
from jukebox_impl import jukebox, JukeboxItem


class Vote:
    # Values

    votes: Dict[discord.Message, "Vote"] = {}

    # Constants

    VOTE_SKIP: int = 1
    VOTE_DELETE: int = 2
    VOTE_WIPE: int = 3
    VOTE_RATIO: float = 0.3

    # Init

    def __init__(self, vote_type: int, allow_no: bool, extra_data: any = None, end_func: any = None) -> None:
        self.vote_type: int = vote_type
        self.allow_no: bool = allow_no
        self.vote_data: any = extra_data
        self.end_func: any = end_func

    # Utility functions

    @classmethod
    async def start_vote(cls, ctx: Context, vote, start_msg: str) -> None:
        if any(v.vote_type == vote.vote_type for v in Vote.votes.values()):
            msg: str = strings.get("info_vote_in_progress")
            await ctx.reply(content=msg)
            return

        msg: str = strings.get("info_vote_start").format(start_msg)
        vote_message: discord.Message = await ctx.reply(content=msg)
        cls.votes[vote_message] = vote
        await vote_message.add_reaction(strings.emoji_vote_yes)
        if vote.allow_no:
            await vote_message.add_reaction(strings.emoji_vote_no)

    @classmethod
    async def check_vote(cls, reaction: discord.Reaction) -> None:
        vote: Vote = cls.votes.get(reaction.message)
        if vote:
            vote_count = reaction.count - 1  # We subtract 1 to discount this bots original reaction
            required_count = Vote.required_votes()
            vote_succeeded = reaction.emoji == strings.emoji_vote_yes and vote_count >= required_count
            vote_failed = vote.allow_no and reaction.emoji == strings.emoji_vote_no and vote_count > required_count
            if vote_succeeded or vote_failed:
                end_msg = strings.get("info_vote_success" if vote_succeeded else "info_vote_failure").format(
                    "{0}",
                    vote_count,
                    required_count,
                    reaction.emoji)
                cls.votes.pop(reaction.message)
                await vote.end_func(
                    ctx=reaction.message,
                    vote=vote,
                    success=vote_succeeded,
                    end_msg=end_msg)

    @classmethod
    async def clear_votes(cls) -> None:
        for message in cls.votes.keys():
            await message.edit(
                content=strings.get("info_vote_expire"),
                delete_after=10)
        cls.votes.clear()

    @classmethod
    def required_votes(cls) -> int:
        return ceil(jukebox.num_listeners() * cls.VOTE_RATIO)

    # Runtime events

    @staticmethod
    async def on_reaction_add(reaction: discord.Reaction, user: discord.User) -> None:
        # Update votes based on reactions, ignoring reactions from users not in the designated text channel
        if reaction.message.channel.id == config.CHANNEL_TEXT \
                and not user.bot \
                and isinstance(user, discord.Member) \
                and jukebox.is_in_voice_channel(member=user):
            await Vote.check_vote(reaction=reaction)


# Commands


class Commands(commands.Cog, name=config.COG_COMMANDS):
    # Values

    is_blocking_commands: bool = False

    # Constants

    ERROR_BAD_PARAMS: str = "Bad command paramters: {0}"

    # Init

    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot

    # Default user commands

    @commands.command(name="add", aliases=["a"])
    @commands.check(is_default)
    @commands.check(is_voice_only)
    async def add(self, ctx: Context, *, query: str = None) -> None:
        msg: str = None
        starting_from_empty: bool = jukebox.is_empty()
        # Assume number values are user error
        if query and query.isdigit():
            raise commands.errors.BadArgument(self.ERROR_BAD_PARAMS.format(query))
        async with ctx.typing():
            try:
                # Parameterless 'add' tries to resume the last-playing track if paused
                if not query:
                    # Playing an empty queue does nothing
                    if starting_from_empty:
                        emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_record"))
                        msg = strings.get("jukebox_empty").format(emoji)
                    else:
                        current = jukebox.current_track()
                        # Users can only play the jukebox if they're in the voice channel
                        if not jukebox.is_in_voice_channel(member=ctx.author):
                            msg = strings.get("error_command_voice_only").format(
                                self.bot.get_channel(id=config.CHANNEL_VOICE).mention)
                        # Playing a populated queue will continue from the current track
                        else:
                            msg = strings.get("jukebox_playing").format(
                                current.title,
                                format_duration(sec=current.duration),
                                current.added_by.mention,
                                strings.emoji_play)
                            # Join voice and start playing
                            await self.ensure_voice()
                            jukebox.play()
                # Otherwise, try to play a track based on the given URL or search query
                else:
                    # Fetch metadata for tracks
                    playlist_info: List[dict]
                    playlist_title: str
                    response_url: str
                    num_failed: int
                    playlist_info, playlist_title, response_url, num_failed = await jukebox_impl.YTDLSource.get_playlist_info(
                        query=query,
                        loop=self.bot.loop)
                    if not response_url:
                        msg = strings.get("error_track").format(query)
                    elif not any(playlist_info):
                        msg = strings.get("error_track_one" if num_failed < 2 else "error_track_all")
                    else:
                        extractor: str = playlist_info[0].get("extractor").split(sep=":")[0] \
                            if playlist_info[0] and "extractor" in playlist_info[0].keys() \
                            else None
                        if not extractor:
                            msg = strings.get("error_extractor_not_found").format(query)
                        elif extractor not in config.YTDL_ALLOWED_EXTRACTORS:
                            msg = strings.get("error_domain_not_whitelisted").format(extractor)
                        else:
                            # Check for excessively large track lists
                            playlist_duration: int = sum([int(track.get("duration", 0)) for track in playlist_info])
                            playlist_filesize: float = bytes_to_mib(sum([track.get("filesize", 0) for track in playlist_info]))
                            playlist_oversize: bool = playlist_duration > config.PLAYLIST_DURATION_WARNING \
                                or playlist_filesize > config.PLAYLIST_FILESIZE_WARNING \
                                or len(playlist_info) > config.PLAYLIST_LENGTH_WARNING
                            # Post a notice if delays are expected
                            if not config.PLAYLIST_STREAMING and playlist_oversize:
                                temp_msg: str = strings.get("info_large_download").format(
                                    len(playlist_info),
                                    format_duration(sec=playlist_duration, is_playlist=True),
                                    playlist_filesize
                                    if playlist_filesize > 0
                                    else strings.get("info_unknown"))
                                await ctx.reply(content=temp_msg)
                            # Prepare the playlist audio files
                            playlist_items = await jukebox_impl.YTDLSource.get_playlist_files(
                                playlist_info=playlist_info,
                                is_streaming=config.PLAYLIST_STREAMING,
                                added_by=ctx.author)
                    # If no messages (errors) were made, start populating the jukebox queue with these tracks
                    if not msg:
                        for playlist_item in playlist_items:
                            jukebox.append(item=playlist_item)
                        index: int = jukebox.get_index_of_item(playlist_items[0])
                        # Start the jukebox
                        if starting_from_empty and jukebox.is_in_voice_channel(ctx.author):
                            # Join voice and start playing if not currently playing and command user is in voice
                            current: JukeboxItem = playlist_items[0]
                            if len(playlist_items) == 1:
                                msg = strings.get("jukebox_added_playing").format(
                                    current.title,
                                    format_duration(sec=current.duration),
                                    strings.emoji_play)
                            else:
                                msg = strings.get("jukebox_added_playlist").format(
                                    playlist_title,
                                    format_duration(sec=playlist_duration, is_playlist=True),
                                    current.title,
                                    len(playlist_items),
                                    format_duration(sec=current.duration),
                                    strings.emoji_play)
                            await self.ensure_voice()
                            jukebox.play()
                        elif len(playlist_items) == 1:
                            msg = strings.get("jukebox_added_one").format(
                                playlist_item.title,
                                format_duration(sec=playlist_item.duration),
                                index + 1,
                                strings.emoji_keycap)
                        else:
                            digit = len(playlist_items) \
                                if len(playlist_items) < len(strings.emoji_digits) \
                                else len(strings.emoji_digits) - 1
                            msg = strings.get("jukebox_added_many").format(
                                playlist_title,
                                format_duration(sec=playlist_duration, is_playlist=True),
                                index + 1,
                                len(playlist_items),
                                strings.emoji_digits[digit])
                        if 0 < num_failed < len(playlist_info):
                            # Add additional info for when one or more tracks in a playlist failed to download
                            msg += "\n" + strings.get("error_track_some").format(num_failed)
            except yt_dlp.DownloadError:
                # Suppress and message download errors
                msg = strings.get("error_download")
            if msg:
                await ctx.reply(content=msg)

    @commands.command(name="skip", aliases=["s"])
    @commands.check(is_default)
    @commands.check(is_voice_only)
    async def skip(self, ctx: Context, skip_count: int = 1) -> None:
        msg: str = None
        async with ctx.typing():
            if jukebox.is_empty():
                emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_record"))
                msg = strings.get("jukebox_empty").format(emoji)
            else:
                tracks: List[JukeboxItem] = jukebox.get_range(index_start=0, index_end=skip_count)
                if all(track.added_by is ctx.message.author for track in tracks) or await is_admin(ctx=ctx, send_message=False) \
                        or Vote.required_votes() <= 1:
                    await self._after_skip_vote(
                        ctx=ctx,
                        extra_data=tracks)
                elif await is_trusted(ctx=ctx, send_message=False):
                    vote_msg: str = strings.get("info_vote_skip").format(
                        skip_count,
                        ctx.message.author.mention)
                    vote: Vote = Vote(
                        vote_type=Vote.VOTE_SKIP,
                        allow_no=False,
                        extra_data=tracks,
                        end_func=self._after_skip_vote)
                    await Vote.start_vote(
                        ctx=ctx,
                        vote=vote,
                        start_msg=vote_msg)
                else:
                    msg = strings.get("error_privileges_other").format(
                        ctx.guild.get_role(role_id=config.ROLE_TRUSTED).mention,
                        ctx.command)
            if msg:
                await ctx.reply(content=msg)

    @commands.command(name="delete", aliases=["d"])
    @commands.check(is_default)
    @commands.check(is_voice_only)
    async def delete(self, ctx: Context, index: int = 1) -> None:
        index -= 1
        track: JukeboxItem = jukebox.get_item_by_index(index=index)
        if not track:
            raise commands.errors.BadArgument(self.ERROR_BAD_PARAMS.format(index))
        msg: str = None
        async with ctx.typing():
            if jukebox.is_empty():
                emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_record"))
                msg = strings.get("jukebox_empty").format(emoji)
            elif track.added_by.id == ctx.author.id or await is_admin(ctx=ctx, send_message=False) \
                    or Vote.required_votes() <= 1:
                await self._after_delete_vote(
                    ctx=ctx,
                    extra_data=index)
            elif await is_trusted(ctx=ctx, send_message=False):
                vote_msg: str = strings.get("info_vote_delete").format(
                    track.title,
                    ctx.message.author.mention,
                    track.added_by.mention)
                vote: Vote = Vote(
                        vote_type=Vote.VOTE_DELETE,
                        allow_no=False,
                        extra_data=index,
                        end_func=self._after_delete_vote)
                await Vote.start_vote(
                    ctx=ctx,
                    vote=vote,
                    start_msg=vote_msg)
            else:
                msg = strings.get("error_privileges_other").format(
                    ctx.guild.get_role(role_id=config.ROLE_TRUSTED).mention,
                    ctx.command)
        if msg:
            await ctx.reply(content=msg)

    @commands.command(name="wipe", aliases=["w"])
    @commands.check(is_default)
    @commands.check(is_voice_only)
    async def wipe(self, ctx: Context, *, query: str = None) -> None:
        msg: str = None
        async with ctx.typing():
            try:
                # Accept users by fuzzy query
                if not query:
                    query = ctx.author.id
                user: discord.User = await commands.UserConverter().convert(
                    ctx=ctx,
                    argument=str(query))
                # Wipe all tracks from a user in the given queue
                queue: List[JukeboxItem] = jukebox.get_queue(user_id=user.id)
                if not any(queue):
                    emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_record"))
                    msg = strings.get("jukebox_empty").format(emoji)
                # For multiqueue, we can assume all tracks in a user's queue are their own
                tracks: List[JukeboxItem] = [track for track in queue if track.added_by.id == user.id] \
                    if not config.PLAYLIST_MULTIQUEUE \
                    else [*queue]  # Use a copy of the tracks to avoid issues when removing
                if not any(tracks):
                    # Ignore calls to wipe an empty queue
                    msg = strings.get("info_wipe_failure")
                elif user.id == ctx.author.id or await is_admin(ctx=ctx, send_message=False) \
                        or all(track.added_by.id == ctx.author.id for track in tracks) \
                        or Vote.required_votes() <= 1:
                    # For queue-owner and admin calls, wipe the queue immediately
                    await self._after_wipe_vote(
                        ctx=ctx,
                        extra_data=tracks)
                elif await is_trusted(ctx=ctx, send_message=False):
                    # For non-queue-owner calls, start a vote to wipe the target user's queue
                    vote_msg: str = strings.get("info_vote_wipe").format(
                        len(tracks),
                        ctx.message.author.mention,
                        tracks[0].added_by.mention)
                    vote: Vote = Vote(
                        vote_type=Vote.VOTE_WIPE,
                        allow_no=False,
                        extra_data=tracks,
                        end_func=self._after_wipe_vote)
                    await Vote.start_vote(
                        ctx=ctx,
                        vote=vote,
                        start_msg=vote_msg)
                else:
                    msg = strings.get("error_privileges_other").format(
                        ctx.guild.get_role(role_id=config.ROLE_TRUSTED).mention,
                        ctx.command)
            except commands.UserNotFound:
                msg = strings.get("error_user_not_found").format(query)
            if msg:
                await ctx.reply(content=msg)

    @commands.command(name="queue", aliases=["q"])
    @commands.check(is_default)
    async def print_all(self, ctx: Context, page_num: Union[str, int] = "1") -> None:
        async with ctx.typing():
            msg: str = None
            embed: discord.Embed = None
            if jukebox.is_empty():
                emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_record"))
                msg = strings.get("jukebox_empty").format(emoji)
            else:
                queue: List[JukeboxItem] = jukebox.get_all()

                # Pagination is bounded to length of the playlist
                pagination_count: int = 10
                page_max: int = ceil(len(queue) / pagination_count)
                page_num = int(page_num)
                if page_num * pagination_count > len(queue):
                    page_num = page_max
                if page_num < 1:
                    page_num = 1
                page_num -= 1

                # Print playlist by elements for the selected (or default) page
                msg_lines: List[str] = []
                current: JukeboxItem = queue[0]

                # aggregated tracks
                index_start: int = pagination_count * page_num
                index_end: int = index_start + pagination_count
                tracks: List[JukeboxItem] = jukebox.get_range(index_start=index_start, index_end=index_end)
                track_msgs: List[str] = [strings.get("jukebox_item").format(
                    index_start + i + 1,
                    format_duration(sec=item.duration),
                    item.added_by.mention,
                    item.title)
                        for i, item in enumerate(iterable=tracks)]

                # currently-playing track
                title: str = strings.get("jukebox_title").format(
                    strings.get("status_playing").format(current.title, strings.emoji_play)
                    if jukebox.voice_client and jukebox.voice_client.is_playing()
                    else strings.get("status_paused").format(current.title, strings.emoji_pause))

                # all other queued tracks on the current page
                msg_lines.append("\n".join(iter(track_msgs)))

                # queue loop status
                msg_lines.append("\n" + strings.get("status_looping").format(strings.get("on")
                                                                             if jukebox.is_repeating
                                                                             else strings.get("off"),
                                                                             strings.emoji_repeat))
                # queue summary
                header: str = strings.get("jukebox_header")
                footer: str = strings.get("jukebox_footer").format(
                    len(queue),
                    format_duration(sec=sum([i.duration for i in queue]), is_playlist=True),
                    page_num + 1,
                    page_max)

                emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_jukebox"))
                embed = discord.Embed(
                    title=title,
                    description="\n".join(msg_lines),
                    colour=ctx.guild.get_role(config.ROLE_JUKEBOX).colour,
                    url=current.url
                    if current
                    else discord.Embed.Empty)
                embed \
                    .set_author(name=header) \
                    .set_footer(text=footer) \
                    .set_thumbnail(url=emoji.url)

            if msg or embed:
                if hasattr(ctx, "reply"):
                    await ctx.reply(content=msg, embed=embed)
                else:
                    await ctx.send(content=msg, embed=embed)

    @commands.command(name="current", aliases=["e"])
    @commands.check(is_default)
    async def print_current(self, ctx: Context) -> None:
        msg: str = None
        embed: discord.Embed = None
        async with ctx.typing():
            current: JukeboxItem = jukebox.current_track()
            if not current:
                emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_record"))
                msg = strings.get("jukebox_empty").format(emoji)
            else:
                # Show info about the currently-playing track
                msg_lines: List[str] = []

                # currently-playing track
                title: str = strings.get("jukebox_title").format(
                    strings.get("status_playing").format(current.title, strings.emoji_play)
                    if jukebox.voice_client and jukebox.voice_client.is_playing()
                    else strings.get("status_paused").format(current.title, strings.emoji_pause))

                # added-by user
                msg_lines.append(strings.get("jukebox_added_by").format(
                    current.added_by.mention,
                    format_duration(sec=current.duration)))

                # queue summary
                emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_record"))
                header: str = strings.get("jukebox_header")
                embed = discord.Embed(
                    title=title,
                    description="\n".join(msg_lines),
                    colour=ctx.guild.get_role(config.ROLE_JUKEBOX).colour,
                    url=current.url
                    if current
                    else discord.Embed.Empty)
                embed \
                    .set_author(name=header) \
                    .set_thumbnail(url=emoji.url)

            if msg or embed:
                if hasattr(ctx, "reply"):
                    await ctx.reply(content=msg, embed=embed)
                else:
                    await ctx.send(content=msg, embed=embed)

    @commands.command(name="lyrics", aliases=["l"])
    @commands.check(is_default)
    @commands.check(is_voice_only)
    async def lyrics(self, ctx: Context, *, query: str = None) -> None:
        msg: str = None
        embed: discord.Embed = None
        if query and query.isdigit():
            # Number queries are treated as a search by index
            index: int = int(query)
            # Treat user search queries as 1-indexed
            if index < 1 or index > jukebox.num_tracks():
                raise commands.errors.BadArgument(self.ERROR_BAD_PARAMS.format(query))
            query = jukebox.get_item_by_index(index=index - 1).title
        async with ctx.typing():
            if not query:
                if jukebox.is_empty():
                    emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_record"))
                    msg = strings.get("jukebox_empty").format(emoji)
                else:
                    query = jukebox.current_track().title
            if not msg:
                query_url: str = "https://search.azlyrics.com/search.php?q={0}&x={1}".format(query, config.TOKEN_LYRICS)
                timeout = aiohttp.ClientTimeout(total=config.HTTP_SEARCH_TIMEOUT)
                result_url: str = None
                async with aiohttp.ClientSession() as session:
                    async with session.get(url=query_url, timeout=timeout) as response:
                        if response.status != 200:
                            msg = strings.get("error_http_status_code").format(
                                f"{response.status} {responses[response.status]}")
                        else:
                            try:
                                html_text: str = await response.text()
                                html = BeautifulSoup(markup=html_text, features="html.parser")
                                result_url = html \
                                    .find(class_="container main-page", recursive=True) \
                                    .find(href=True, recursive=True) \
                                    .attrs.get("href")
                            except AttributeError:
                                pass
                    if not result_url:
                        msg = strings.get("error_lyrics_not_found").format(query)
                    else:
                        async with session.get(url=result_url, timeout=timeout) as response:
                            if not response.ok:
                                msg = strings.get("error_http_status_code").format(
                                    f"{response.status} {responses[response.status]}")
                            else:
                                html_text: str = await response.text()
                                html = BeautifulSoup(markup=html_text, features="html.parser")
                                html_heading = html.find(class_="lyricsh", recursive=True)
                                header: str = html_heading.find(name="b", recursive=True).text
                                html_subheading = html_heading.parent.find(name="b", recursive=False)
                                title: str = html_subheading.text
                                text: str = html_subheading.find_next_sibling(name="div").text
                                text = text[:1750] + "..." \
                                    if len(text) > 1750 \
                                    else text
                                emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_record"))
                                embed = discord.Embed(
                                    title=title,
                                    description=text,
                                    colour=ctx.guild.get_role(config.ROLE_JUKEBOX).colour,
                                    url=result_url)
                                embed \
                                    .set_author(name=header) \
                                    .set_footer(
                                        text=response.url.host,
                                        icon_url="https://images.azlyrics.com/az_logo_tr.png") \
                                    .set_thumbnail(url=emoji.url)

            if msg or embed:
                await ctx.reply(
                    content=msg,
                    embed=embed)

    @commands.command(name="shuffle", aliases=["f"])
    @commands.check(is_default)
    @commands.check(is_voice_only)
    async def shuffle(self, ctx: Context) -> None:
        async with ctx.typing():
            msg: str = None
            queue: List[JukeboxItem] = jukebox.get_queue(ctx.author.id)
            if not any(queue):
                emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_record"))
                msg = strings.get("jukebox_empty").format(emoji)
            elif len(queue) == 1:
                msg = strings.get("jukebox_shuffled_one").format(
                    strings.emoji_refresh)
            else:
                shuffle_count: int = jukebox.shuffle(user_id=queue[0].added_by.id)
                msg = strings.get("jukebox_shuffled").format(
                    queue[0].title,
                    shuffle_count,
                    strings.emoji_shuffle)
            if msg:
                await ctx.reply(content=msg)

    # Trusted user commands

    @commands.command(name="pause", aliases=["p"])
    @commands.check(is_trusted)
    @commands.check(is_voice_only)
    async def toggle_pause(self, ctx: Context) -> None:
        async with ctx.typing():
            msg: str = None
            current: JukeboxItem = jukebox.current_track()
            if not current:
                # Empty jukebox queue does nothing when paused
                emoji: discord.Emoji = utils.get(jukebox.bot.emojis, name=strings.get("emoji_id_record"))
                msg = strings.get("jukebox_empty").format(emoji)
            elif jukebox.voice_client and jukebox.voice_client.is_playing():
                # Pause the audio stream if playing
                jukebox.pause()
                msg = strings.get("jukebox_paused").format(
                    current.title,
                    format_duration(sec=current.duration),
                    current.added_by.mention,
                    strings.emoji_pause)
            else:
                # Playing a populated queue will continue from the current track
                msg = strings.get("jukebox_playing").format(
                    current.title,
                    format_duration(sec=current.duration),
                    current.added_by.mention,
                    strings.emoji_play)
                # Join voice and start playing
                await self.ensure_voice()
                if jukebox.voice_client.is_paused():
                    jukebox.resume()
                else:
                    jukebox.play()
        if msg:
            await ctx.reply(content=msg)

    @commands.command(name="loop", aliases=["o"])
    @commands.check(is_trusted)
    @commands.check(is_voice_only)
    async def toggle_loop(self, ctx: Context) -> None:
        jukebox.repeat()
        msg: str = strings.get("status_looping").format(
            strings.get("on")
            if jukebox.is_repeating
            else strings.get("off"),
            strings.emoji_repeat)
        if msg:
            await ctx.reply(content=msg)

    # Admin commands

    @commands.command(name="refresh", aliases=["z"])
    @commands.check(is_admin)
    async def refresh_commands(self, ctx: Context) -> None:
        print("Refreshing commands. [{0}#{1} ({2})]".format(
            ctx.author.name,
            ctx.author.discriminator,
            ctx.author.id))
        self.bot.reload_extension(name=config.PACKAGE_COMMANDS)
        await ctx.message.add_reaction(strings.emoji_confirm)

    @commands.command(name="exit", aliases=["x"])
    @commands.check(is_admin)
    async def exit(self, ctx: Context) -> None:
        print("Exiting voice with {3} listeners. [{0}#{1} ({2})]".format(
            ctx.author.name,
            ctx.author.discriminator,
            ctx.author.id,
            jukebox.num_listeners()))
        jukebox.stop()
        if jukebox.voice_client:
            await jukebox.voice_client.disconnect()
        await ctx.message.add_reaction(strings.emoji_confirm)

    @commands.command(name="cleartracks", aliases=["c"], hidden=True)
    @commands.check(is_admin)
    async def clear_tracks(self, ctx: Context) -> None:
        print("Clearing {3} tracks. [{0}#{1} ({2})]".format(
            ctx.author.name,
            ctx.author.discriminator,
            ctx.author.id,
            jukebox.num_tracks()))
        jukebox.clear()
        await ctx.message.add_reaction(strings.emoji_confirm)

    @commands.command(name="clearvotes", aliases=["v"], hidden=True)
    @commands.check(is_admin)
    async def clear_votes(self, ctx: Context) -> None:
        print("Clearing {3} votes. [{0}#{1} ({2})]".format(
            ctx.author.name,
            ctx.author.discriminator,
            ctx.author.id,
            len(Vote.votes)))
        await Vote.clear_votes()
        await ctx.message.add_reaction(strings.emoji_confirm)

    @commands.command(name="block", aliases=["b"])
    @commands.check(is_admin)
    async def block_commands(self, ctx: Context) -> None:
        print("Blocking commands. [{0}#{1} ({2})]".format(
            ctx.author.name,
            ctx.author.discriminator,
            ctx.author.id))
        Commands.is_blocking_commands = True
        await ctx.message.add_reaction(strings.emoji_lock_on)

    @commands.command(name="unblock", aliases=["n"])
    @commands.check(is_admin)
    async def unblock_commands(self, ctx: Context) -> None:
        print("Unblocking commands. [{0}#{1} ({2})]".format(
            ctx.author.name,
            ctx.author.discriminator,
            ctx.author.id))
        Commands.is_blocking_commands = False
        await ctx.message.add_reaction(strings.emoji_lock_off)

    @commands.command(name="mango", aliases=["m"])
    @commands.check(is_admin)
    async def activate_mango(self, ctx: Context) -> None:
        print("Activating mango. [{0}#{1} ({2})]".format(
            ctx.author.name,
            ctx.author.discriminator,
            ctx.author.id))
        await ctx.message.add_reaction(strings.emoji_mango)

    @commands.command(name="str", aliases=[], hidden=True)
    @commands.check(is_admin)
    async def test_string(self, ctx: Context, string: str) -> None:
        msg: str = strings.get(string)
        await ctx.reply(content="{0}: {1}".format(string, msg)
                        if msg
                        else strings.get("error_string_not_found").format(string))

    # Vote finalisers

    async def _after_skip_vote(self, ctx: Context, vote: Vote = None, success: bool = True, extra_data: any = None, end_msg: str = "{0}") -> None:
        msg: str = None
        if success:
            tracks: List[JukeboxItem] = vote.vote_data if vote else extra_data
            jukebox.remove_many(tracks=tracks)
            msg = strings.get("info_skip_success").format(
                len(tracks),
                strings.emoji_next)
        else:
            msg = strings.get("info_skip_failure")
        if msg:
            await ctx.reply(content=end_msg.format(msg))
        await self._after_vote(ctx=ctx)

    async def _after_delete_vote(self, ctx: Context, vote: Vote = None, success: bool = True, extra_data: any = None, end_msg: str = "{0}") -> None:
        msg: str = None
        if success:
            index: int = vote.vote_data if vote else extra_data
            item: JukeboxItem = jukebox.get_item_by_index(index=index)
            if item:
                jukebox.remove(
                    item=item,
                    is_deleting=jukebox.is_repeating)
                msg = strings.get("info_delete_success").format(
                    item.title,
                    format_duration(sec=item.duration),
                    item.added_by.mention,
                    index + 1,
                    strings.emoji_next)
        else:
            msg = strings.get("info_skip_failure")
        if msg:
            await ctx.reply(content=end_msg.format(msg))
        await self._after_vote(ctx=ctx)

    async def _after_wipe_vote(self, ctx: Context, vote: Vote = None, success: bool = True, extra_data=None, end_msg="{0}") -> None:
        msg: str = None
        if success:
            tracks = vote.vote_data if vote else extra_data
            num_tracks: int = len(tracks)
            jukebox.remove_many(tracks=tracks)
            msg = strings.get("info_wipe_success").format(
                num_tracks,
                tracks[0].added_by.mention,
                strings.emoji_next)
        else:
            msg = strings.get("info_skip_failure")
        if msg:
            await ctx.reply(content=end_msg.format(msg))
        await self._after_vote(ctx=ctx)

    async def _after_vote(self, ctx: Context):
        if any(Vote.votes):
            msg: str = strings.get("info_vote_collection_modified").format(len(Vote.votes))
            await ctx.send(content=msg)
            await Vote.clear_votes()

    # Command utilities

    async def ensure_voice(self) -> None:
        voice_channel: discord.VoiceChannel = self.bot.get_channel(id=config.CHANNEL_VOICE)
        if not isinstance(jukebox.voice_client, discord.VoiceClient) \
                or not jukebox.voice_client.is_connected() \
                or not jukebox.voice_client.channel \
                or not jukebox.voice_client.channel.id == voice_channel.id:
            # Assert that the bot has a voice connection
            try:
                if jukebox.voice_client:
                    await jukebox.voice_client.disconnect(force=True)
            finally:
                jukebox.voice_client = await voice_channel.connect(
                    timeout=config.VOICE_TIMEOUT,
                    reconnect=config.VOICE_RECONNECT)
        if not jukebox.voice_client:
            raise Exception(strings.get("error_voice_not_found"))

    async def after_play(self) -> None:
        # Clear votes
        await Vote.clear_votes()
        # Post now-playing update
        ctx: Context = jukebox.voice_client.channel.guild.get_channel(config.CHANNEL_TEXT)
        await self.print_current(ctx=ctx)


# Utility functions


def bytes_to_mib(b: int) -> float:
    return b / 1048576


def format_duration(sec: int, is_playlist: bool = False) -> str:
    return datetime.utcfromtimestamp(sec) \
        .strftime(strings.get("datetime_format_playlist")
                  if is_playlist
                  else strings.get("datetime_format_track"))


# Discord.py boilerplate


def setup(bot) -> None:
    cog: Commands = Commands(bot)
    bot.add_cog(cog)
    bot.add_listener(Vote.on_reaction_add)
    jukebox.on_track_end_func = cog.after_play
    reload(strings)
    reload(jukebox_checks)
