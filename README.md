# home-audio-detection

Three small "what is playing right now" detectors that run on a Raspberry Pi home hub.
Each one polls a different source and writes the current track to a JSON file one
directory up; a separate service reads those files and drives a 64x64 LED matrix that
shows the album cover.

| Script | Source | Needs |
| --- | --- | --- |
| `shazam.py` | a USB microphone, listening to the room | `pyaudio`, `pydub`, `shazamio`, `numpy`, `ffmpeg` |
| `yamaha.py` | a Yamaha MusicCast receiver over its Extended Control HTTP API | `requests` |
| `spotify.py` | the Spotify Web API (currently playing) | `spotipy` |

The layout mirrors the home directories on the Pis, so a path here is the path there.

```
detection/          on the hub, under ~/python_spotify_websocket_server/
  shazam.py
  yamaha.py
  spotify.py
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

## Known issues

- `spotify.py` imports `websockets` but never uses it. On a host without that module
  installed the script dies on import.
- `shazamio` deprecated `recognize_song` in favour of `recognize`, but the replacement
  does not accept a pydub `AudioSegment`, so the migration means passing bytes or a file
  path rather than renaming the call.
