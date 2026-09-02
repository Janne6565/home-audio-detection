import traceback
import asyncio
from io import BytesIO
import time, sys, os, requests, PIL, PIL.ImageOps, json
from PIL import ImageFilter, ImageEnhance, ImageDraw, Image
import websockets
import signal
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from collections import deque

POLL_INTERVAL = 10 # ms
IMAGE_DARKEN_PERC = 0.5 #

args = sys.argv

DEFAULT_URL = os.environ.get("AUDIO_WEBSOCKET_URL")

print(args)
URL = DEFAULT_URL if len(args) < 2 else args[1]
if not URL:
    raise SystemExit("Set AUDIO_WEBSOCKET_URL or pass the websocket url as the first argument")

def ease_in_out(t):
    """
    Calculate ease-in-out value for given time fraction.

    :param t: Time fraction (float between 0 and 1)
    :return: Value between 0 and 1 representing parameter at given time
    """
    if t < 0:
        return 0
    elif t > 1:
        return 1
    else:
        return t * t * (3 - 2 * t)


def transition(start_value, value_to_be, time_remaining, max_time):
    """
    Perform transition from start_value to value_to_be over specified time.

    :param start_value: Initial value
    :param value_to_be: Target value
    :param time_remaining: Remaining time
    :param max_time: Total transition time
    :return: Interpolated value based on time fraction
    """
    return start_value + ease_in_out(1 - (time_remaining / max_time)) * (value_to_be - start_value)

def crop_image(image: Image.Image):
    length_to_crop_to = min(image.size)
    center_offset = int(length_to_crop_to / 2)
    center_point = (int(image.size[0] / 2), int(image.size[1] / 2))
    return image.crop((center_point[0] - center_offset, center_point[1] - center_offset, center_point[0] + center_offset, center_point[1] + center_offset))

class SyncWebsocket:

    def __init__(self, uri, image_buffer, images_in_buffer):
        self.uri = uri
        self.received_messages = []
        self.connection = None
        self.receive_task = None
        self.image_buffer = image_buffer
        self.images_in_buffer = images_in_buffer
        self.reconnect_delay = 5  # delay before reconnecting

    async def connect(self):
        while True:
            try:
                print("Connecting:", self.uri)
                self.connection = await websockets.connect(self.uri)
                print("Connected to websocket.")
                self.receive_task = asyncio.create_task(self.receive_messages())
                await self.receive_task
            except websockets.ConnectionClosed:
                print("Connection closed, attempting to reconnect...")
            except Exception as e:
                print("Unexpected error:", e)
                traceback.print_exc()
            await asyncio.sleep(self.reconnect_delay)

    async def receive_messages(self):
        try:
            async for message in self.connection:
                try:
                    parsed = json.loads(message)
                    if parsed["type"] != "localAlbumCover":
                        self.received_messages.append(parsed)
                        continue

                    image_path = parsed["value"]
                    req = requests.get(image_path)
                    image = Image.open(BytesIO(req.content)).convert("RGB")
                    self.image_buffer[image_path] = image

                    if image_path in self.images_in_buffer:
                        print("Cover was already loaded before:", image_path)
                        self.images_in_buffer.remove(image_path)

                    self.images_in_buffer.append(image_path)
                    print("loaded image into buffer:", image_path)

                    if len(self.images_in_buffer) > 5:
                        removed = self.images_in_buffer.popleft()
                        print("Removed image from buffer:", removed)
                        del self.image_buffer[removed]

                    self.received_messages.append(parsed)
                except Exception as e:
                    print("Error occurred when trying to process message:", message)
                    print("Exception:", e)
                    traceback.print_exc()
        except websockets.ConnectionClosed:
            print("Connection closed in receive_messages, will reconnect...")
            await self.connect()
        except Exception as e:
            print("Unexpected error in receive_messages:", e)
            traceback.print_exc()
            await self.connect()

    def get_received_messages(self):
        messages = self.received_messages.copy()
        self.received_messages.clear()
        return messages

    async def send_message(self, message):
        try:
            await self.connection.send(message)
        except websockets.ConnectionClosed:
            print("Connection closed while trying to send a message, reconnecting...")
            await self.connect()
            await self.connection.send(message)

    async def disconnect(self):
        if self.connection:
            await self.connection.close()
        if self.receive_task:
            await self.receive_task
        print("Disconnected from websocket.")


class LedMatrix:
    DEFAULT_MATRIX_OPTIONS = {
        "rows": 64,
        "cols": 64,
        "chain_length": 1,
        "parallel": 1,
        "hardware_mapping": "adafruit-hat-pwm",
        "led_rgb_sequence": "RGB",
        "brigthness": 100,
        "pwm_dither_bits": 1,
        "slowdown_gpio": 3
    }

    DEFAULT_DISPLAY_OPTIONS = {
        "image": {
            "transition_time": 2 # Seconds
        },
        "volume_bar": {
            "appear_time": 1, # Seconds
            "disappear_time": 2,
            "grow_time": 1
        }
    }

    matrix = None

    current_image = None
    image_transitioning_to = None
    image_transition_time_remaining = 0

    current_volume = 0
    volume_transitioning_to = 0
    volume_transition_time_remaining = 0

    current_volume_opacity = 0
    volume_opacity_transitioning_to = 0
    volume_opacity_transition_time_remaining = 0

    last_vals = None

    def load_options(self):
        options = RGBMatrixOptions()
        options.rows = 64
        options.cols = 64
        options.chain_length = 1
        options.parallel = 1
        options.hardware_mapping = "adafruit-hat-pwm"
        options.led_rgb_sequence = "RGB"
        options.brightness = 65
        options.pwm_dither_bits = 1
        options.gpio_slowdown = 4

        return options

    def __init__(self, image_buffer, options=None):
        loaded_options = self.load_options()
        self.current_image = PIL.Image.new("RGB", (loaded_options.cols, loaded_options.rows), "black")
        if options == None:
            options = {}

        self.image_buffer = image_buffer

        self.MATRIX_OPTIONS = loaded_options

        self.matrix = RGBMatrix(options=loaded_options)

        self.DISPLAY_OPTIONS = self.DEFAULT_DISPLAY_OPTIONS | options


    def set_image(self, image):
        self.current_image = self.get_current_background_image()
        self.image_transitioning_to = image
        self.image_transition_time_remaining = self.DISPLAY_OPTIONS["image"]["transition_time"]

    def enhance_image(self, image):
        sharpened_image = image.filter(ImageFilter.SHARPEN)

        contrasted_image = ImageEnhance.Contrast(sharpened_image).enhance(1.5)

        darkened_image = PIL.Image.blend(contrasted_image, PIL.Image.new("RGB", contrasted_image.size, "black"), IMAGE_DARKEN_PERC)

        return darkened_image

    def load_image(self, image_path):
        try:
            if image_path not in self.image_buffer:
                print("Couldnt load image: " + image_path + " not found in image_buffer")
                print(self.image_buffer)
                return

            image = self.image_buffer[image_path]

            enhanced_image = self.enhance_image(image)
            enhanced_image.thumbnail((self.MATRIX_OPTIONS.cols, self.MATRIX_OPTIONS.rows))

            self.set_image(crop_image(enhanced_image).resize((self.MATRIX_OPTIONS.cols, self.MATRIX_OPTIONS.rows)))
        except Exception as e:
            print("Error occured when trying to load image:", image_path)
            print(e)

    def set_volume(self, new_volume):
        new_volume = float(new_volume) / 100.0
        if self.current_volume == new_volume:
            return
        self.current_volume = self.get_current_volume_bar_width()
        self.volume_transitioning_to = new_volume
        self.volume_transition_time_remaining = self.DISPLAY_OPTIONS["volume_bar"]["grow_time"]

        if self.volume_opacity_transition_time_remaining == 0 or self.volume_opacity_transitioning_to == 0:
            self.current_volume_opacity = self.get_current_volume_bar_opacity()
            self.volume_opacity_transitioning_to = 1
            self.volume_opacity_transition_time_remaining = self.DISPLAY_OPTIONS["volume_bar"]["appear_time"]

    def get_current_volume_bar_width(self):
        if self.volume_transition_time_remaining == 0:
            return self.current_volume
        return transition(self.current_volume, self.volume_transitioning_to, self.volume_transition_time_remaining, self.DISPLAY_OPTIONS["volume_bar"]["grow_time"])

    def get_current_volume_bar_opacity(self):
        if self.volume_opacity_transition_time_remaining == 0:
            return self.current_volume_opacity
        return transition(self.current_volume_opacity, self.volume_opacity_transitioning_to, self.volume_opacity_transition_time_remaining, self.DISPLAY_OPTIONS["volume_bar"]["grow_time"])


    def tick_volume(self, time_delta):
        if self.volume_opacity_transition_time_remaining > 0:
            self.volume_opacity_transition_time_remaining = max(0, self.volume_opacity_transition_time_remaining - time_delta)
            if self.volume_opacity_transition_time_remaining == 0:
                self.current_volume_opacity = self.volume_opacity_transitioning_to
                self.volume_opacity_transitioning_to = None
        else:
            if self.volume_transition_time_remaining > 0:
                self.volume_transition_time_remaining = max(0, self.volume_transition_time_remaining - time_delta)
                if self.volume_transition_time_remaining == 0:
                    self.current_volume = self.volume_transitioning_to
                    self.volume_opacity_transitioning_to = 0
                    self.volume_opacity_transition_time_remaining = self.DISPLAY_OPTIONS["volume_bar"]["disappear_time"]


    def tick_image(self, time_delta):
        if self.image_transition_time_remaining == None or self.image_transition_time_remaining == 0:
            return

        self.image_transition_time_remaining = max(0, self.image_transition_time_remaining - time_delta)
        if self.image_transition_time_remaining == 0:
            self.current_image = self.image_transitioning_to
            self.image_transitioning_to = None


    def tick(self, time_delta):
        self.tick_image(time_delta)
        self.tick_volume(time_delta)


    def get_current_background_image(self):
        base_image = self.current_image.convert("RGB")
        if self.image_transitioning_to == None or self.image_transition_time_remaining == 0:
            return base_image
        else:
            return PIL.Image.blend(
                base_image, self.image_transitioning_to.convert("RGB"), transition(0, 1, self.image_transition_time_remaining, self.DISPLAY_OPTIONS["image"]["transition_time"])
            )


    def get_image(self):
        background = self.get_current_background_image().convert("RGBA")
        volume_opacity = self.get_current_volume_bar_opacity()
        if volume_opacity == 0:
            return background

        volume_image = background.copy()
        volume_draw = ImageDraw.Draw(volume_image)
        line_color = (255, 255, 255, 255)
        volume_draw.line([(0, background.size[1]), (background.size[0] * self.get_current_volume_bar_width(), background.size[1])], fill=line_color, width=5)
        return Image.blend(background, volume_image, volume_opacity)


    def reload_image(self):
        vals = {
            "cImage":self.current_image, "tImage": self.image_transitioning_to, "tImageTime": self.image_transition_time_remaining,
            "cVolume": self.current_volume, "tVolume": self.volume_transitioning_to, "tVolumeTime": self.volume_transition_time_remaining,
            "tVolumeOpacity": self.volume_opacity_transitioning_to, "tVolumeOpacityTime": self.volume_opacity_transition_time_remaining, "cVolumeOpacity": self.current_volume_opacity
        }
        if vals != self.last_vals:
            current_image = self.get_image()
            self.matrix.SetImage(current_image.convert("RGB"))
            self.last_vals = vals

def shutdown_hook(a, b):
    global matrix
    print("Triggering shutdown hook")
    matrix.set_image(PIL.Image.new("RGB", (matrix.MATRIX_OPTIONS.cols, matrix.MATRIX_OPTIONS.rows), "black"))
    matrix.set_volume(0)
    time_remaining = max(matrix.DISPLAY_OPTIONS["volume_bar"]["disappear_time"] * 2 + matrix.DISPLAY_OPTIONS["volume_bar"]["grow_time"], matrix.DISPLAY_OPTIONS["image"]["transition_time"])
    last_tick = time.time()
    while time_remaining > 0:
        current_time = time.time()
        diff = current_time - last_tick
        matrix.tick(current_time - last_tick)
        matrix.reload_image()
        last_tick = current_time
        time_remaining -= diff
        time.sleep(POLL_INTERVAL / 2000)

    print("SHUTTING DOWN")
    exit(0)


CALLBACKS = {
    "volume": lambda matrix, value: matrix.set_volume(value),
    "localAlbumCover": lambda matrix, value: matrix.load_image(value),
}

async def main():
    global matrix, CALLBACKS

    image_buffer = {}
    images_in_buffer = deque()
    print("Using url:", URL)
    client = SyncWebsocket(URL, image_buffer, images_in_buffer)
    matrix = LedMatrix(image_buffer)

    signal.signal(signal.SIGTERM, shutdown_hook)

    # Connect to the websocket
    connect_task = asyncio.create_task(client.connect())

    try:
        last_tick = time.time()
        while True:
            try:
                time_delta = time.time() - last_tick
                last_tick = time.time()
                received_messages = client.get_received_messages()
                if received_messages:
                    for message in received_messages:
                        if message["type"] not in CALLBACKS:
                            continue

                        CALLBACKS[message["type"]](matrix, message["value"])

                matrix.tick(time_delta)
                matrix.reload_image()

                await asyncio.sleep(POLL_INTERVAL / 2000)
            except Exception as e:
                print("Error in main loop:", e)
                traceback.print_exc()
    finally:
        await client.disconnect()



asyncio.run(main())
