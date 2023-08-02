import json
import os
from typing import List, Optional

import boto3
import sqlalchemy as db
from sqlalchemy.orm import sessionmaker

from models import Playlist, Song


def get_secret_value(secret_name: str) -> Optional[str]:
    session = boto3.session.Session()
    client = session.client(
        service_name="secretsmanager",
        region_name="eu-north-1",
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )

    response = client.get_secret_value(SecretId=secret_name)
    result = json.loads(response["SecretString"]).get(secret_name)
    if result is None:
        raise ValueError("Got wrong secret_name value")
    return result  # type: ignore[no-any-return]


engine = db.create_engine(get_secret_value("rds-database-url"))
Session = sessionmaker(bind=engine)


def add_song_to_playlist(
    guild_id: int, playlist_name: str, title: str, url: str
) -> bool:
    with Session() as session:
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

            song = Song(title=title, url=url, playlist=playlist)
            session.add(song)
            session.commit()
            return True

        except Exception as e:
            print("Error occurred while adding the song:", e)
            session.rollback()
            return False


def delete_playlist(guild_id: int, playlist_name: str) -> bool:
    with Session() as session:
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
    with Session() as session:
        try:
            playlists = session.query(Playlist)
            playlists = playlists.filter_by(guild_id=guild_id).all()
            return playlists  # type: ignore[no-any-return]

        except Exception as e:
            print("Error occurred while getting playlist:", e)
            return []


def get_tracks_of_playlist(guild_id: int, playlist_name: str) -> List[Song]:
    with Session() as session:
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
