import asyncio
import websockets
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
import json, os, time


FILE_NAME = "../spotify.json"

# Set up your Spotify API credentials
SPOTIPY_CLIENT_ID = os.environ["SPOTIPY_CLIENT_ID"]
SPOTIPY_CLIENT_SECRET = os.environ["SPOTIPY_CLIENT_SECRET"]
SPOTIPY_REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI", "http://localhost:8888/callback/")
SCOPE = "user-read-playback-state"

# Set up your WebSocket server details
SERVER_ADDRESS = "0.0.0.0"
SERVER_PORT = 4000

# Spotify OAuth authorization flow
sp_oauth = SpotifyOAuth(
	SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI, scope=SCOPE
)

last_values = {}

values_looking_at = {
	"albumCover": lambda playback: playback["item"]["album"]["images"][0]["url"],
	"localAlbumCover": lambda playback: playback["item"]["album"]["images"][0]["url"],
    "albumName": lambda playback: playback["item"]["album"]["name"],
	"artist": lambda playback: playback["item"]["artists"][0]["name"],
	"songName": lambda playback: playback["item"]["name"],
	"volume": lambda playback: playback["device"]["volume_percent"],
}

def write(data):
    with open(FILE_NAME, "w") as file:
        json.dump(data, file)

while True:
    try:
        sp = Spotify(auth_manager=sp_oauth)
        playback = sp.current_playback()
        if playback is None or not playback["is_playing"]:
            last_values = {}
            write({})
            time.sleep(1)
            continue
        for value in values_looking_at:
            current_value = values_looking_at[value](playback)
            if current_value != last_values.get(value):
                last_values[value] = current_value
                write(last_values)
        time.sleep(1)
    except Exception as e:
        print(e)
        time.sleep(5)
