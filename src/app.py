import json

import discord
import yt_dlp
from discord.ext import commands, tasks
from discord.ext.commands import Context

from playlist_handler import DefaultHandler, SoundCloudHandler, YouTubeHandler
from playlist_utils import (
    add_song_to_playlist,
    clear_bucket_queue,
    delete_playlist,
    get_playlists,
    get_redis_client,
    get_secret_value,
    get_tracks_of_playlist,
    play_from_queue,
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)


@bot.command(name="stop")  # type: ignore[misc]
async def stop(context: Context) -> None:
    voice_channel = context.guild.voice_client
    redis_client = get_redis_client()
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
    redis_client = get_redis_client()
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
    redis_client = get_redis_client()
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
    redis_client = get_redis_client()
    if voice_channel.is_playing():
        redis_client.hset("is_paused", str(context.guild), "paused")

        voice_channel.pause()
        await context.send("Music paused.")
    else:
        await context.send("There is no track currently playing.")


@bot.command(name="resume")  # type: ignore[misc]
async def resume(context: Context) -> None:
    voice_channel = context.guild.voice_client
    redis_client = get_redis_client()
    if voice_channel.is_paused():
        redis_client.hset("is_paused", str(context.guild), "not_paused")
        voice_channel.resume()
        await context.send("Music resumed.")
    else:
        await context.send("Music is not paused.")


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


@bot.command(name="add_song_to_playlist")  # type: ignore[misc]
async def add_song_to_playlist_command(
    context: Context, playlist_name: str, song_url: str
) -> None:
    handler_chain = YouTubeHandler(SoundCloudHandler(DefaultHandler()))
    bucket_key, song_title = await handler_chain.handle_request(
        context, playlist_name, song_url
    )

    if bucket_key is not None and song_title is not None:
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


@bot.command(name="play")  # type: ignore[misc]
async def play(context: Context, url_or_playlist: str) -> None:
    redis_client = get_redis_client()
    if context.guild.voice_client not in bot.voice_clients:
        await context.message.author.voice.channel.connect()
        redis_client.hset("is_paused", str(context.guild), "not_paused")

    voice_channel = context.message.guild.voice_client
    guild_name = str(context.guild)
    handler_chain = YouTubeHandler(SoundCloudHandler(DefaultHandler()))
    try:
        bucket_uuid, song_title = await handler_chain.handle_request(
            context, "queue", url_or_playlist
        )

        if bucket_uuid is not None:
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
