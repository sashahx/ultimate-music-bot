import asyncio
import io
import json
import os
import uuid
from contextlib import redirect_stdout
from typing import Tuple

import boto3
import discord
import redis  # type: ignore[import]
import yt_dlp
from discord import Guild
from discord.ext import commands, tasks
from discord.ext.commands import Context
from sclib.asyncio import SoundcloudAPI, get_resource

from utils import (
    add_song_to_playlist,
    delete_playlist,
    get_playlists,
    get_secret_value,
    get_tracks_of_playlist,
)

YOUTUBE_URL = "youtube.com"
SOUNDCLOUD_URL = "soundcloud.com"
ytdl_format_options = {
    "outtmpl": "-",
    "logtostderr": True,
    "noplaylist": True,
    "format": "bestaudio/best",
}

redis_client = redis.StrictRedis(
    port=get_secret_value("elsasticache-redis-port"),
    host=get_secret_value("elsasticache-redis-host"),
    db=0,
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)


def get_s3_song_url(uuid: str) -> str:
    return f"https://{get_secret_value('song-bucket')}.s3.{os.environ.get('AWS_REGION')}.amazonaws.com/{uuid}"


def clear_bucket_queue(prefix: str) -> None:
    s3_client = boto3.client("s3")
    objects_to_delete = s3_client.list_objects(
        Bucket=get_secret_value("song-bucket"), Prefix=prefix
    )

    for obj in objects_to_delete.get("Contents", []):
        s3_client.delete_object(Bucket=get_secret_value("song-bucket"), Key=obj["Key"])


async def download_youtube_song(
    url: str, guild_name: str, subdirectory: str
) -> Tuple[str, str]:
    song_bytes = io.BytesIO()
    with redirect_stdout(song_bytes), yt_dlp.YoutubeDL(ytdl_format_options) as ytdl:  # type: ignore[type-var]
        info_dict = ytdl.extract_info(url, download=False)
        title = info_dict.get("title", "Unknown Title")
        ytdl.download([url])

    bucket_key = f"{guild_name}/{subdirectory}/{uuid.uuid4()}"
    s3_client = boto3.client("s3")
    s3_client.put_object(
        Body=song_bytes.getvalue(),
        Bucket=get_secret_value("song-bucket"),
        Key=bucket_key,
    )
    return (bucket_key, title)


async def download_soundcloud_song(
    url: str, guild_name: str, subdirectory: str
) -> Tuple[str, str]:
    soundcloud_api = SoundcloudAPI()
    s3_client = boto3.client("s3")

    response = await soundcloud_api.resolve(url)
    stream_url = await response.get_stream_url()
    song_bytes = await get_resource(stream_url)
    bucket_key = f"{guild_name}/{subdirectory}/{uuid.uuid4()}"
    s3_client.put_object(
        Body=song_bytes, Bucket=get_secret_value("song-bucket"), Key=bucket_key
    )
    song_title = response.title
    return (bucket_key, song_title)


async def play_from_queue(guild: Guild) -> None:
    voice_channel = guild.voice_client
    guild_name = str(guild)
    while redis_client.llen(guild_name) > 0:
        song_info = redis_client.lpop(guild_name)
        song_uuid, _ = json.loads(song_info.decode())
        voice_channel.play(
            discord.FFmpegPCMAudio(get_s3_song_url(song_uuid), executable="ffmpeg")
        )
        while (
            voice_channel.is_playing()
            or redis_client.hget("is_paused", guild_name).decode() == "paused"
        ):
            await asyncio.sleep(1)

    clear_bucket_queue(f"{guild_name}/queue")


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

            clear_bucket_queue(f"{voice_channel.guild.name}/queue")


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
            f"Using {YOUTUBE_URL} as part of a playlist name is not allowed"
        )
    elif SOUNDCLOUD_URL in playlist_name:
        await context.send(
            f"Using {SOUNDCLOUD_URL} as part of a playlist name is not allowed"
        )
    else:
        bucket_key = None
        if YOUTUBE_URL in song_url:
            bucket_key, song_title = await download_youtube_song(
                song_url, str(context.guild), playlist_name
            )
        elif SOUNDCLOUD_URL in song_url:
            bucket_key, song_title = await download_soundcloud_song(
                song_url, str(context.guild), playlist_name
            )

        if bucket_key is not None:
            added_successfully = add_song_to_playlist(
                guild_id=context.guild.id,
                playlist_name=playlist_name,
                title=song_title,
                url=song_url,
                s3_bucket_uuid=bucket_key,
            )

            if added_successfully:
                await context.send(
                    f"Song '{song_title}' added to playlist '{playlist_name}'"
                )
            else:
                await context.send(
                    f"Failed to add the song to playlist '{playlist_name}'. Please try again later"
                )
        else:
            await context.send("Failed to download the track")


@bot.command(name="delete_playlist")  # type: ignore[misc]
async def delete_playlist_command(context: Context, playlist_name: str) -> None:
    deleted_successfully = delete_playlist(
        guild_id=context.guild.id, playlist_name=playlist_name
    )

    if deleted_successfully:
        clear_bucket_queue(f"{str(context.guild)}/{playlist_name}")
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
            bucket_uuid, song_title = await download_youtube_song(
                url_or_playlist, guild_name, "queue"
            )
            redis_client.rpush(guild_name, json.dumps([bucket_uuid, song_title]))
            async with context.typing():
                await context.send(f"{song_title} added to queue")
        elif SOUNDCLOUD_URL in url_or_playlist:
            bucket_uuid, song_title = await download_soundcloud_song(
                url_or_playlist, guild_name, "queue"
            )
            redis_client.rpush(guild_name, json.dumps([bucket_uuid, song_title]))
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
                    redis_client.rpush(
                        guild_name, json.dumps([track.s3_bucket_uuid, track.title])
                    )
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
