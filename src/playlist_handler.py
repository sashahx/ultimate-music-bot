from __future__ import annotations

from typing import Optional, Tuple

from discord.ext.commands import Context

from playlist_utils import download_soundcloud_song, download_youtube_song

YOUTUBE_URL = "youtube.com"
SOUNDCLOUD_URL = "soundcloud.com"


class PlaylistHandler:
    def __init__(self, successor: Optional[PlaylistHandler] = None):
        self.successor = successor

    async def handle_request(
        self, context: Context, playlist_name: str, song_url: str
    ) -> Tuple[Optional[str], Optional[str]]:
        return None, None


class YouTubeHandler(PlaylistHandler):
    async def handle_request(
        self, context: Context, playlist_name: str, song_url: str
    ) -> Tuple[Optional[str], Optional[str]]:
        if YOUTUBE_URL in song_url:
            bucket_key, song_title = await download_youtube_song(
                song_url, str(context.guild), playlist_name
            )
            return bucket_key, song_title
        elif self.successor:
            return await self.successor.handle_request(context, playlist_name, song_url)
        else:
            return None, None


class SoundCloudHandler(PlaylistHandler):
    async def handle_request(
        self, context: Context, playlist_name: str, song_url: str
    ) -> Tuple[Optional[str], Optional[str]]:
        if SOUNDCLOUD_URL in song_url:
            bucket_key, song_title = await download_soundcloud_song(
                song_url, str(context.guild), playlist_name
            )
            return bucket_key, song_title
        elif self.successor:
            return await self.successor.handle_request(context, playlist_name, song_url)
        else:
            return None, None


class DefaultHandler(PlaylistHandler):
    pass
