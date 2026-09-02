from pydub import AudioSegment
from shazamio import Shazam
import time, sounddevice, asyncio, json, pyaudio
import numpy as np

FILE_NAME = "../shazam.json"
AUDIO_DURATION = 7
# Normalised RMS (0..1 full scale) below which a recording counts as silence.
# Measured 2026-09-03: quiet room ~0.00032, music over the Yamaha ~0.0081.
QUIET_THRESHOLD = 0.001
def calculate_rms(audio_data):
    # Calculate RMS amplitude, normalised to 0..1 full scale.
    # int16 has to be widened before squaring, otherwise np.square overflows.
    samples = audio_data.astype(np.float64) / np.iinfo(np.int16).max
    rms = np.sqrt(np.mean(np.square(samples)))
    return rms

def record_audio(duration_seconds=5, sample_rate=16000, channels=1, sample_width=2, quiet_threshold=QUIET_THRESHOLD):
    p = pyaudio.PyAudio()
    
    # Explicit USB mic device (card 1 usually index 1 or 2; confirm with device list below)
    input_device_index = 1  # Adjust if needed
    
    stream = p.open(
        format=p.get_format_from_width(sample_width),
        channels=channels,
        rate=sample_rate,
        input=True,
        input_device_index=input_device_index,  # Key: specify device!
        frames_per_buffer=512,  # Smaller to reduce overflow risk
    )

    print("Recording...")

    frames = []

    # Record (smaller chunks help)
    for i in range(0, int(sample_rate / 512 * duration_seconds)):
        data = stream.read(512, exception_on_overflow=False)  # Ignore overflow, continue
        frames.append(data)

    stream.stop_stream()
    stream.close()
    p.terminate()

    audio_segment = AudioSegment(
        b"".join(frames),
        frame_rate=sample_rate,
        sample_width=sample_width,
        channels=channels,
    )
    audio_segment.export("./shazam_exported.mp3", format="mp3")
    
    rms_amplitude = calculate_rms(np.frombuffer(audio_segment.raw_data, dtype=np.int16))

    print("RMS Amplitude:", rms_amplitude)

    if rms_amplitude < quiet_threshold:
        print("Audio too quiet.")
        return None
    return audio_segment

result = None
async def main(audio_segment: AudioSegment):
    global result
    shazam = Shazam()
    result = await shazam.recognize_song(audio_segment)

last_found = None
last_written = None


def write_json(data):
    """Serialise first, then write.

    Building the payload before opening the file means a failure while
    assembling it can no longer leave a truncated, unparseable file behind.
    Identical payloads are skipped so an idle loop stops rewriting the SD card
    every ten seconds.
    """
    global last_written
    payload = json.dumps(data)
    if payload == last_written:
        return
    with open(FILE_NAME, "w") as f:
        f.write(payload)
    last_written = payload


def extract_album_name(track):
    for section in track.get("sections", []):
        if section.get("type") != "SONG":
            continue
        for metadata in section.get("metadata", []):
            if metadata.get("title", "").upper() == "ALBUM" or metadata.get("type", "").upper() == "ALBUM":
                return metadata.get("text", "")
    return ""


def build_track_info(result):
    track = result["track"]
    return {
        "albumCover": track["images"]["coverarthq"],
        "localAlbumCover": track["images"]["coverarthq"],
        "albumName": extract_album_name(track),
        "artist": track["subtitle"],
        "songName": track["title"],
    }


if __name__ == "__main__":
    while True:
        try:
            audio_segment = record_audio(duration_seconds=AUDIO_DURATION)

            matched = False
            if audio_segment is not None:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(main(audio_segment))
                if len(result["matches"]) == 1:
                    try:
                        track_info = build_track_info(result)
                    except KeyError as e:
                        print("Ran into issue when trying to access song informations", e)
                    else:
                        print(track_info)
                        try:
                            write_json(track_info)
                            last_found = time.time()
                            matched = True
                        except Exception as e:
                            print("Ran into unexpected exception (possible json file not writable):", e)

            if not matched:
                # Reached for silence as well as for an unrecognised recording,
                # so the stale entry is cleared either way.
                if last_found is None or time.time() - last_found > 30:
                    write_json({})

            time.sleep(10)
        except KeyboardInterrupt:
            print("Exiting...")
            break
        except Exception as e:
            print("Ran into error", e)
            time.sleep(10)
