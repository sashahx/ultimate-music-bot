import asyncio
import json
import os
from typing import Tuple

import discord
import redis  # type: ignore[import]
import yt_dlp
from discord import Guild
from discord.ext import commands, tasks
from discord.ext.commands import Context

from utils import (
    add_song_to_playlist,
    delete_playlist,
    get_playlists,
    get_secret_value,
    get_tracks_of_playlist,
)

SONG_ROOT_PATH = os.path.join(os.getcwd(), "songs")
YOUTUBE_URL = "youtube.com"


ytdl_format_options = {
    "format": "bestaudio/best",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "outtmpl": os.path.join(SONG_ROOT_PATH, "%(title)s.%(ext)s"),
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

redis_client = redis.StrictRedis(
    port=get_secret_value("elsasticache-redis-port"),
    host=get_secret_value("elsasticache-redis-host"),
    db=0,
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)


async def download_file_by_url(url: str, guild_name: str) -> Tuple[str, str]:
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None, lambda: ytdl.extract_info(url, download=True)
    )

    song_path = ytdl.prepare_filename(response)
    splitted_song_path = song_path.split("/")
    song_name = splitted_song_path.pop()
    splitted_song_path.append(guild_name)
    guild_song_directory = os.path.join(os.path.sep, *splitted_song_path)
    if not os.path.exists(guild_song_directory):
        os.makedirs(guild_song_directory)

    splitted_song_path.append(song_name)
    splitted_song_path = os.path.join(os.path.sep, *splitted_song_path)
    os.rename(song_path, splitted_song_path)
    return (splitted_song_path, response.get("title"))


def remove_guild_files(guild_songs_directory: str) -> None:
    for filename in os.listdir(guild_songs_directory):
        file_to_delete = os.path.join(guild_songs_directory, filename)
        os.remove(file_to_delete)


async def play_from_queue(guild: Guild) -> None:
    voice_channel = guild.voice_client
    guild_name = str(guild)
    while redis_client.llen(guild_name) > 0:
        song_info = redis_client.lpop(guild_name)
        filename, _ = json.loads(song_info.decode())
        voice_channel.play(discord.FFmpegPCMAudio(source=filename))

        while (
            voice_channel.is_playing()
            or redis_client.hget("is_paused", guild_name).decode() == "paused"
        ):
            await asyncio.sleep(1)

    remove_guild_files(os.path.join(os.sep, SONG_ROOT_PATH, guild_name))


@bot.command(name="stop")  # type: ignore[misc]
async def stop(context: Context) -> None:
    voice_channel = context.guild.voice_client
    if voice_channel.is_playing() or redis_client.llen(str(context.guild)) > 0:
        redis_client.ltrim(str(context.guild), 1, 0)
        redis_client.hset("is_paused", str(context.guild), "not_paused")
        voice_channel.stop()
        await context.send("Queue cleared and stopped.")
    else:
        await context.send("The bot is not playing anything at the moment.")


@bot.command(name="skip")  # type: ignore[misc]
async def skip(context: Context) -> None:
    voice_channel = context.guild.voice_client
    if redis_client.llen(str(context.guild)) > 0 or (
        voice_channel and voice_channel.is_playing()
    ):
        voice_channel.stop()
        redis_client.hset("is_paused", str(context.guild), "not_paused")
        await context.send("Skipped the current track")
    else:
        await context.send("There is no track currently playing")


@tasks.loop(minutes=1)  # type: ignore[misc]
async def check_voice_channels() -> None:
    for voice_channel in bot.voice_clients:
        if len(voice_channel.channel.members) == 1:
            redis_client.ltrim(voice_channel.guild.name, 1, 0)
            redis_client.hset(
                "is_paused",
                voice_channel.guild.name,
                "not_paused",
            )
            await voice_channel.disconnect()

            remove_guild_files(
                os.path.join(os.sep, SONG_ROOT_PATH, voice_channel.guild.name)
            )


@bot.command(name="pause")  # type: ignore[misc]
async def pause(context: Context) -> None:
    voice_channel = context.guild.voice_client
    if voice_channel.is_playing():
        redis_client.hset("is_paused", str(context.guild), "paused")

        voice_channel.pause()
        await context.send("Music paused.")
    else:
        await context.send("There is no track currently playing.")


@bot.command(name="resume")  # type: ignore[misc]
async def resume(context: Context) -> None:
    voice_channel = context.guild.voice_client
    if voice_channel.is_paused():
        redis_client.hset("is_paused", str(context.guild), "not_paused")

        voice_channel.resume()
        await context.send("Music resumed.")
    else:
        await context.send("Music is not paused.")


@bot.command(name="add_song_to_playlist")  # type: ignore[misc]
async def add_song_to_playlist_command(
    context: Context, playlist_name: str, song_url: str
) -> None:
    if YOUTUBE_URL in playlist_name:
        await context.send(
            f"Using {YOUTUBE_URL} as part of a playlist name " "is not allowed"
        )
    else:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(song_url, download=False)
        )
        song_title = response.get("title", "empty_title")
        added_successfully = add_song_to_playlist(
            guild_id=context.guild.id,
            playlist_name=playlist_name,
            title=song_title,
            url=song_url,
        )

        if added_successfully:
            await context.send(
                f"Song '{song_title}' added to playlist '{playlist_name}'"
            )
        else:
            await context.send(
                f"Failed to add the song to playlist '{playlist_name}'. Please try again later"
            )


@bot.command(name="delete_playlist")  # type: ignore[misc]
async def delete_playlist_command(context: Context, playlist_name: str) -> None:
    deleted_successfully = delete_playlist(
        guild_id=context.guild.id, playlist_name=playlist_name
    )

    if deleted_successfully:
        await context.send("Playlist deleted")
    else:
        await context.send("Failed to delete the playlist. Please try again later")


@bot.command(name="get_playlists")  # type: ignore[misc]
async def get_playlists_command(context: Context) -> None:
    playlists = get_playlists(guild_id=context.guild.id)
    if playlists:
        result = []
        for playlist in playlists:
            result.append(playlist.name)

        await context.send("Here are the playlists:")
        await context.send("\n".join(result))
    else:
        await context.send("Failed to get playlists. Please try again later")


@bot.command(name="get_tracks_of_playlist")  # type: ignore[misc]
async def get_tracks_of_playlist_command(context: Context, playlist_name: str) -> None:
    tracks = get_tracks_of_playlist(
        guild_id=context.guild.id,
        playlist_name=playlist_name,
    )

    if tracks:
        result = []
        for track in tracks:
            result.append(track.title)
        await context.send(f"Here are the tracks of a {playlist_name} playlist:")
        await context.send("\n".join(result))
    else:
        await context.send("Failed to get tracks. Please try again later")


@bot.command(name="play")  # type: ignore[misc]
async def play(context: Context, url_or_playlist: str) -> None:
    if context.guild.voice_client not in bot.voice_clients:
        await context.message.author.voice.channel.connect()
        redis_client.hset("is_paused", str(context.guild), "not_paused")

    voice_channel = context.message.guild.voice_client
    guild_name = str(context.guild)

    try:
        if YOUTUBE_URL in url_or_playlist:
            filename, song_title = await download_file_by_url(
                url_or_playlist, guild_name
            )
            redis_client.rpush(guild_name, json.dumps([filename, song_title]))
            async with context.typing():
                await context.send(f"{song_title} added to queue")

        else:
            tracks = get_tracks_of_playlist(
                guild_id=context.guild.id, playlist_name=url_or_playlist
            )
            if tracks:
                async with context.typing():
                    await context.send("Downloading the playlist")
                for track in tracks:
                    filename, song_title = await download_file_by_url(
                        track.url, guild_name
                    )
                    redis_client.rpush(guild_name, json.dumps([filename, song_title]))
            else:
                await context.send("Playlist is empty, please check your spelling")

        if not voice_channel.is_playing():
            await play_from_queue(context.guild)
    except yt_dlp.utils.DownloadError:
        await context.send(
            "Couldn't download a song, it looks like your link is broken"
        )


@bot.event  # type: ignore[misc]
async def on_ready() -> None:
    check_voice_channels.start()


if __name__ == "__main__":
    bot.run(get_secret_value("discord-bot-token"))
