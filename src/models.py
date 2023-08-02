import sqlalchemy as db
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Playlist(Base):  # type: ignore[valid-type, misc]
    __tablename__ = "playlists"
    id = db.Column(db.Integer, primary_key=True)
    guild_id = db.Column(db.BigInteger, nullable=False)
    name = db.Column(db.String, nullable=False)
    songs = relationship("Song", back_populates="playlist")


class Song(Base):  # type: ignore[valid-type, misc]
    __tablename__ = "songs"
    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey("playlists.id"))
    title = db.Column(db.String, nullable=False)
    url = db.Column(db.String, nullable=False)
    playlist = relationship("Playlist", back_populates="songs")
