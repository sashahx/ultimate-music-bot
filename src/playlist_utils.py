import asyncio
import io
import json
import os
import uuid
from contextlib import redirect_stdout
from typing import List, Optional, Tuple

import boto3
import discord
import sqlalchemy as db
import yt_dlp
from botocore.client import BaseClient
from discord import Guild
from redis import Redis  # type: ignore[import]
from sclib.asyncio import SoundcloudAPI, get_resource
from sqlalchemy.orm import sessionmaker

from models import Playlist, Song

ytdl_format_options = {
    "outtmpl": "-",
    "logtostderr": True,
    "noplaylist": True,
    "format": "bestaudio/best",
}


def get_secret_value(secret_name: str) -> Optional[str]:
    session = boto3.session.Session()
    client = session.client(
        service_name="secretsmanager",
        region_name=os.environ.get("AWS_REGION"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )

    response = client.get_secret_value(SecretId=secret_name)
    result = json.loads(response["SecretString"]).get(secret_name)
    if result is None:
        raise ValueError("Got wrong secret_name value")
    return result  # type: ignore[no-any-return]


engine = db.create_engine(get_secret_value("rds-database-url"))
session_factory = sessionmaker(bind=engine)


def get_s3_client() -> BaseClient:
    return boto3.client("s3")


def get_s3_song_url(uuid: str) -> str:
    return f"https://{get_secret_value('song-bucket')}.s3.{os.environ.get('AWS_REGION')}.amazonaws.com/{uuid}"


def clear_bucket_queue(prefix: str) -> None:
    s3_client = get_s3_client()
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
    s3_client = get_s3_client()
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
    s3_client = get_s3_client()

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
    redis_client = get_redis_client()
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


def get_redis_client() -> Redis:
    return Redis(
        port=get_secret_value("elsasticache-redis-port"),
        host=get_secret_value("elsasticache-redis-host"),
        db=0,
    )


def add_song_to_playlist(
    guild_id: int, playlist_name: str, title: str, url: str, s3_bucket_uuid: str
) -> bool:
    with session_factory() as session:
        try:
            playlist = (
                session.query(Playlist)
                .filter_by(guild_id=guild_id, name=playlist_name)
                .first()
            )
            if not playlist:
                playlist = Playlist(guild_id=guild_id, name=playlist_name)
                session.add(playlist)
                session.commit()

            song = Song(
                title=title, url=url, playlist=playlist, s3_bucket_uuid=s3_bucket_uuid
            )
            session.add(song)
            session.commit()
            return True

        except Exception as e:
            print("Error occurred while adding the song:", e)
            session.rollback()
            return False


def delete_playlist(guild_id: int, playlist_name: str) -> bool:
    with session_factory() as session:
        try:
            playlist = (
                session.query(Playlist)
                .filter_by(guild_id=guild_id, name=playlist_name)
                .first()
            )
            if playlist:
                for song in playlist.songs:
                    session.delete(song)
                session.delete(playlist)
                session.commit()
            return True

        except Exception as e:
            print("Error occurred while deleting the playlist:", e)
            session.rollback()
            return False


def get_playlists(guild_id: int) -> List[Playlist]:
    with session_factory() as session:
        try:
            playlists = session.query(Playlist)
            playlists = playlists.filter_by(guild_id=guild_id).all()
            return playlists  # type: ignore[no-any-return]

        except Exception as e:
            print("Error occurred while getting playlist:", e)
            return []


def get_tracks_of_playlist(guild_id: int, playlist_name: str) -> List[Song]:
    with session_factory() as session:
        try:
            playlist = (
                session.query(Playlist)
                .filter_by(guild_id=guild_id, name=playlist_name)
                .first()
            )
            if playlist:
                return playlist.songs  # type: ignore[no-any-return]
            else:
                return []

        except Exception as e:
            print("Error occurred while getting tracks of the playlist:", e)
            return []
