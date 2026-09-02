# home-audio-detection

Two Raspberry Pis that together show the cover of whatever is currently playing on a
64x64 LED matrix.

The **hub** runs three "what is playing right now" detectors. Each polls a different
source and writes the current track to a JSON file, which a websocket server then
publishes. The **display Pi** subscribes to that server, downloads the cover art and
draws it on the panel with a cross-fade and a volume bar.

| Script | Source | Needs |
| --- | --- | --- |
| `shazam.py` | a USB microphone, listening to the room | `pyaudio`, `pydub`, `shazamio`, `numpy`, `ffmpeg` |
| `yamaha.py` | a Yamaha MusicCast receiver over its Extended Control HTTP API | `requests` |
| `spotify.py` | the Spotify Web API (currently playing) | `spotipy` |

The layout mirrors the home directories on the Pis, so a path here is the path there.

```
detection/            hub,        ~/python_spotify_websocket_server/
  shazam.py
  yamaha.py
  spotify.py
led-matrix/           display Pi, ~/led-matrix/
  main.py             drives the panel, PIL over rgbmatrix
service-controller/   display Pi, ~/service-controller/
  main.py             starts and stops the panel service on remote command
systemd/              the unit files, as deployed
  hub/
  display/
```

Output shape, written to `../shazam.json`, `../yamaha.json`, `../spotify.json`:

```json
{
  "albumCover": "https://…",
  "localAlbumCover": "https://…",
  "albumName": "…",
  "artist": "…",
  "songName": "…"
}
```

An empty object `{}` means nothing is playing.

## Configuration

Copy `.env.example` to `.env` and fill it in. `spotify.py` needs Spotify application
credentials, `yamaha.py` needs the receiver's LAN address. `shazam.py` needs no
configuration but does need `input_device_index` to point at the right capture device;
check `arecord -l` and the PyAudio device list, the two do not necessarily agree.

On the display Pi, both scripts need the address of the hub's websocket server:
`AUDIO_WEBSOCKET_URL` for the panel and `SERVICE_CONTROLLER_WEBSOCKET_URL` for the
controller. Both also still accept the url as a command line argument, which takes
precedence over the environment.

## How `shazam.py` decides that the room is quiet

It records `AUDIO_DURATION` seconds, computes the RMS amplitude normalised to 0..1 full
scale, and skips the recognition call entirely when that falls below `QUIET_THRESHOLD`.

Two things are easy to get wrong here, and both were live bugs:

- **Widen the samples before squaring.** `np.square()` on an int16 array overflows for
  any sample above 181, so the result is not a loudness measure at all. It has to be cast
  to float first.
- **Keep the units consistent.** The threshold is on a 0..1 scale, so the RMS has to be
  divided by `np.iinfo(np.int16).max` before the comparison.

Measured on the actual hardware: a quiet room sits at about `0.00032`, music over the
receiver at `0.0063` to `0.0145`. The default threshold of `0.001` sits deliberately close
to the noise floor so that quiet music still gets through.

This is a *silence* gate, not a *music* gate. Conversation or a television will clear it,
so an occasional wrong match during the day is expected.

## Running them

Everything runs as a systemd unit; `systemd/` holds them as deployed, so the paths in
them are the real ones (`/home/janne/...`) and need adjusting for another machine.

Note that the units predate this repository and still expect the hub address to be
baked into the scripts. Since it now comes from the environment, a fresh deployment
needs it added, either as a drop-in or inline:

```ini
[Service]
Environment=AUDIO_WEBSOCKET_URL=ws://your-hub:9000/audio
```

Two more notes worth carrying over:

- Set `PYTHONUNBUFFERED=1` in the unit. Without it Python block-buffers stdout into the
  journal, and logs arrive in bursts up to half an hour late, which makes anything
  timing-related impossible to debug.
- The four hub units have no `After=network-online.target`. A detector that crashes at
  boot because the network is not up yet burns through the systemd restart limit in
  about five seconds and then stays dead until someone notices. The two display units
  do have it.
- `spotify-websocket-server.service` is dead legacy: its `server.py` no longer exists,
  the websocket server it once started now runs as the Docker container in
  `webserver-home.service`. It is kept here only because it is still enabled on the
  host and fails at every boot.

## Known issues

- `spotify.py` imports `websockets` but never uses it. On a host without that module
  installed the script dies on import.
- `shazamio` deprecated `recognize_song` in favour of `recognize`, but the replacement
  does not accept a pydub `AudioSegment`, so the migration means passing bytes or a file
  path rather than renaming the call.
- `led-matrix/main.py` downloads a cover with a blocking `requests.get` inside the
  asyncio receive loop, and does so before checking whether the image is already
  buffered, so duplicates are fetched again and the display stalls during a burst.
- The volume bar's opacity is interpolated against `grow_time` even while it is using
  `appear_time` or `disappear_time`, and its width only advances once the opacity
  transition has finished, so it never grows while fading in.
