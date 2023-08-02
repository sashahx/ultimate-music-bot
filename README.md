# Ultimate Discord Music Bot

This is a Discord bot that allows users to play and manage music in voice channels. The bot uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) to extract audio from YouTube videos and plays them in the voice channels. It also provides playlist management features that allow users to create, delete, modify and list playlists.

## Getting Started

To use the bot, you need to have the following prerequisites:

- Python 3.11 or higher
- Redis server for queuing music
- PostgreSQL database
- Discord bot token
- AWS EC2, RDS, and ElastiCache services (optional for hosting)

### Installation

1. Clone the repository:

2. Install the required dependencies:

```bash
poetry install --no-dev
```

3. Set up environment variables:

   - `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`: These are the AWS access credentials required for accessing the Secrets Manager service.
   - `discord-bot-token`: Your Discord bot token, which you can obtain by creating a new bot application in the [Discord Developer Portal](https://discord.com/developers/applications).
   - `rds-database-url`: The connection URL for your PostgreSQL database.
   - `elsasticache-redis-host` and `elsasticache-redis-port`: Your Redis endpoint host and port.

### Usage

Run the bot with the following command:

```bash
poetry run python app.py
```

The bot will connect to your Discord server and listen for commands in the channels where it has been added.

### Usage with Docker

Build the Docker image:

```bash
docker build -t discord-music-bot .
```

Create a `.env` file and set the environment variables:

```
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
```

Run the bot using Docker with the following command:

docker run --env-file .env discord-music-bot

The bot will connect to your Discord server and listen for commands in the channels where it has been added.

### Commands

The bot supports the following commands:

- `/play <url_or_playlist>`: Adds a song or a playlist to the queue and starts playing.
- `/pause`: Pauses the currently playing track.
- `/resume`: Resumes the paused track.
- `/stop`: Stops the music and clears the queue.
- `/skip`: Skips the current track.
- `/add_song_to_playlist <playlist_name> <song_url>`: Adds a song to a specific playlist.
- `/delete_playlist <playlist_name>`: Deletes a playlist.
- `/get_playlists`: Lists all the available playlists.
- `/get_tracks_of_playlist <playlist_name>`: Lists all the tracks in a specific playlist.

## Hosting on AWS

You can host the bot on AWS using the following services:

- **AWS EC2**: Set up an EC2 instance to run the bot application.
- **AWS RDS**: Create a PostgreSQL database instance and provide the connection URL as `rds-database-url` environment variable in the bot.
- **ElastiCache**: Use Elasticache to host the Redis server for queuing music.
