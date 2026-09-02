import os, requests, json, time

IP_ADRESS = os.environ["YAMAHA_IP"]

URL_ENDPOINT = "http://" + IP_ADRESS + "/YamahaExtendedControl/"
FILE_NAME = "../yamaha.json"


cached_album = {'name': '', 'artist': '', 'albumArt': ''}
def get_album_cover(res):
    global cached_album

    album_name = res['album']
    artist = res['artist']

    if album_name == '' or artist == '':
        return None

    if album_name == cached_album['name'] and artist == cached_album['artist']:
        return cached_album['albumArt']

    try:
        query = album_name + " " + artist
        print(query)
        r = requests.get(
            "https://itunes.apple.com/search",
            params={"term": query, "entity": "album", "limit": 1}
        )
        items = r.json().get("results", [])
        if not items:
            return None

        # artworkUrl100 is 100x100 — replace with 600x600 for higher resolution
        album_art = items[0]["artworkUrl100"].replace("100x100", "600x600")

        cached_album['albumArt'] = album_art
        cached_album['artist'] = artist
        cached_album['name'] = album_name
        return album_art
    except Exception as e:
        print(e)
        return None
    

MAPPINGS = {
    'albumCover': lambda res: get_album_cover(res) if res['albumart_url'] else None,
    'albumName': lambda res: res['album'],
    'artist': lambda res: res['artist'],
    'songName': lambda res: res['track'],
    'localAlbumCover': lambda res: ("http://" + IP_ADRESS + res['albumart_url']) if res['albumart_url'] not in ['', None] else None
}


def send_request(endpoint, version="v1"):
    req = requests.get(URL_ENDPOINT + version + "/" + endpoint)
    return req.json()

def get_play_info():
    return send_request("netusb/getPlayInfo")

def get_volume_info():
    return send_request("main/getStatus")


LAST_WRITE = {}
def write_to_json(result):
    global LAST_WRITE
    if result == LAST_WRITE:
        return
    
    LAST_WRITE = result
    with open(FILE_NAME, "w+") as file:
        json.dump(result, file)


while True:
    try:
        res = get_play_info()
        new_res = {}
        print(res)
        for key in MAPPINGS:
            value = MAPPINGS[key](res)
            if value != None and value != '':
                new_res[key] = value
        volume_req = get_volume_info()
        new_res["volume"] = int(volume_req["volume"] / volume_req["max_volume"] * 100)
        write_to_json(new_res)
        time.sleep(0.2)
    except Exception as e:
        print("Ran into exception:", e)
