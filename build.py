from dotenv import load_dotenv
load_dotenv()

import json
import requests
import os
import shutil
from PIL import Image
import base64
import hashlib
import concurrent.futures
import subprocess
import time

# Настройки GitHub (замените на свои данные)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")  # Берётся из переменной окружения
REPO = "1NFERR/PawTotems"         # Например, "myrp/myrp.github.io"
BRANCH = "main"                          # Ветка репозитория

# Локальные пути
base_folder = os.path.join("PawTotems-git", "PawTotems", "assets", "minecraft", "optifine", "cit")
uuid_nick_file = "uuid_nick.json"

# Color maps from JavaScript's ears_v0_pixel_values
ears_v0_pixel_values = {
    0x3F23D8: "blue",
    0x23D848: "green",
    0xD82350: "red",
    0xB923D8: "purple",
    0x23D8C6: "cyan",
    0xD87823: "orange",
    0xD823B7: "pink",
    0xD823FF: "purple2",
    0xFEFDF2: "white",
    0x5E605A: "gray",
}

# Mode mappings from JavaScript
ears_mode_from_color = {
    "blue": "above",
    "green": "sides",
    "purple": "behind",
    "cyan": "around",
    "orange": "floppy",
    "pink": "cross",
    "purple2": "out",
    "white": "tall",
    "gray": "tall_cross"
}

ears_anchor_from_color = {
    "green": "front",
    "red": "back"
}

protrusions_from_color = {
    "green": "claws",
    "purple": "horn",
    "cyan": "both"
}

tail_mode_from_color = {
    "blue": "down",
    "green": "back",
    "purple": "up",
    "orange": "vertical"
}

wings_mode_from_color = {
    "pink": "symmetric_dual",
    "green": "symmetric_single",
    "cyan": "asymmetric_single_l",
    "orange": "asymmetric_single_r"
}

def git_commit_and_push(commit_message):
    repo_dir = "PawTotems-git"
    try:
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", commit_message], cwd=repo_dir, check=True)
        subprocess.run(["git", "push", "-f", "origin", "main"], cwd=repo_dir, check=True)
        print("Изменения успешно загружены на GitHub.")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при выполнении Git-команды: {e}")

def resize_texture_to_32x32(texture_path):
    """Обрабатывает текстуру до размера 32x32, добавляя пустое пространство с альфа-каналом."""
    with Image.open(texture_path) as img:
        if img.size != (20, 16):
            print(f"Текстура имеет размер {img.size}, ожидается 20x16. Пропускаем обработку.")
            return
        # Если текстура уже 32x32, ничего не делаем
        if img.size == (32, 32):
            print(f"Текстура уже имеет размер {img.size}. Пропускаем обработку.")
            return
        
        new_img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        # Центрируем текстуру
        new_img.paste(img, (0, 16))
        # Сохраняем
        new_img.save(texture_path)
        
# Helper function to convert RGBA pixel to RGB value as in abgrToRgb
def get_rgb(pixel):
    r, g, b, _ = pixel
    return (r << 16) | (g << 8) | b

# pixelValToUnit function translated from JavaScript
def pixel_val_to_unit(val):
    if val == 0:
        return 0
    j = val - 128
    if j < 0:
        j -= 1
    else:
        j += 1
    return j / 128.0

# Функция извлечения информации о настройках Ears Mod и текстур хвоста/крыльев
# Парсинг закодированных данных из скина
def extract_ears_data(skin_image):
    rectangles = [
        [8, 0, 16, 8], [0, 8, 8, 8], [16, 8, 16, 8], [4, 16, 8, 4],
        [20, 16, 16, 4], [44, 16, 8, 4], [0, 20, 56, 12], [20, 48, 8, 4],
        [36, 48, 8, 4], [16, 52, 32, 12]
    ]
    predef_keys = ["END", "wing", "erase", "cape"]
    MAGIC = 0xEA1FA1FA
    pixels = skin_image.load()
    bi = 0
    read = 0
    for minx, miny, dx, dy in rectangles:
        for x in range(minx, minx + dx):
            for y in range(miny, miny + dy):
                try:
                    v = pixels[x, y][3]
                except IndexError:
                    print(f"Pixel out of bounds: ({x},{y})")
                    return None
                if v > 0:
                    v = 0x7F - (v & 0x7F)
                    bi |= v << (read * 7)
                    read += 1
    data_bytes = []
    while bi > 0:
        data_bytes.append(bi & 0xFF)
        bi //= 256
    data_bytes.reverse()
    if len(data_bytes) < 4:
        return None
    magic = (data_bytes[0] << 24) | (data_bytes[1] << 16) | (data_bytes[2] << 8) | data_bytes[3]
    if magic != MAGIC:
        return None
    data_iter = iter(data_bytes[4:])
    version = next(data_iter)
    alfalfa = {"version": version, "raw": data_bytes, "entries": {}}
    if version != 1:
        print(f"Unknown Alfalfa version: {version}")
        return alfalfa
    while True:
        try:
            index = next(data_iter)
            if index < 64:
                k = predef_keys[index] if index < len(predef_keys) else f"!unk{index}"
            else:
                cp = [index]
                while True:
                    val = next(data_iter)
                    if (val & 0x80) == 0:
                        cp.append(val)
                    else:
                        cp.append(val & 0x7F)
                        break
                k = "".join(chr(c) for c in cp)
            if k == "END":
                break
            entry_data = []
            while True:
                length = next(data_iter)
                for _ in range(length):
                    entry_data.append(next(data_iter))
                if length < 255:
                    break
            alfalfa["entries"][k] = base64.b64encode(bytes(entry_data)).decode()
        except StopIteration:
            break
        except Exception as e:
            print(f"Error parsing Alfalfa: {e}")
            return None
    return alfalfa

# Извлечение настроек Ears Mod
def get_ears_setting(skin_image, setting_name):
    pixels = skin_image.load()
    try:
        magic = [pixels[0, 32][i] for i in range(3)]
    except IndexError:
        return None
    
    if magic == [0x3F, 0x23, 0xD8]:
        return _get_ears_setting_v0(skin_image, setting_name)
    elif magic == [0xEA, 0x25, 0x01]:
        return _get_ears_setting_v1(skin_image, setting_name)
    else:
        return None
    
def _get_ears_setting_v1(skin_image, setting_name):
    pixels = skin_image.load()
    class BitStream:
        def __init__(self):
            self.bi = 0
            self.len = 0
        def write(self, bits, val):
            self.bi = (self.bi << bits) | (val & ((1 << bits) - 1))
            self.len += bits
        def read(self, bits):
            if bits <= self.len:
                self.len -= bits
                return (self.bi >> self.len) & ((1 << bits) - 1)
            self.write(bits, 0)
            return self.read(bits)
        def readBool(self):
            return self.read(1) == 1
        def readSAMUnit(self, bits):
            neg = self.readBool()
            val = self.read(bits)
            max_val = (1 << bits) - 1
            f = val / max_val
            return -f if neg else f
        def readUnit(self, bits):
            val = self.read(bits)
            max_val = (1 << bits) - 1
            return val / max_val
    
    bis = BitStream()
    for y in range(4):
        for x in range(4):
            if x == 0 and y == 0:
                continue
            try:
                bis.write(8, pixels[x, 32 + y][0])
                bis.write(8, pixels[x, 32 + y][1])
                bis.write(8, pixels[x, 32 + y][2])
            except IndexError:
                return None
    
    _ = bis.read(8)  # Version byte, unused
    ears = bis.read(6)
    ears_modes = ["none", "above", "sides", "behind", "around", "floppy", "cross", "out", "tall", "tall_cross"]
    ears_anchors = ["center", "front", "back"]
    ears_mode = "none" if ears == 0 else ears_modes[min(((ears - 1) // 3) + 1, len(ears_modes) - 1)]
    ears_anchor = "center" if ears == 0 else ears_anchors[min((ears - 1) % 3, len(ears_anchors) - 1)]
    
    protrusions_modes = ["none", "horn", "claws", "both"]
    protrusions = protrusions_modes[min(bis.read(2), len(protrusions_modes) - 1)]
    
    tail_modes = ["none", "down", "back", "up", "vertical"]
    tail_mode = tail_modes[min(bis.read(3), len(tail_modes) - 1)]
    tail_segments = 1
    tail_bend_1 = tail_bend_2 = tail_bend_3 = tail_bend_4 = 0
    if tail_mode != "none":
        tail_segments = bis.read(2) + 1
        tail_bend_1 = round(bis.readSAMUnit(6) * 90)
        if tail_segments > 1:
            tail_bend_2 = round(bis.readSAMUnit(6) * 90)
        if tail_segments > 2:
            tail_bend_3 = round(bis.readSAMUnit(6) * 90)
        if tail_segments > 3:
            tail_bend_4 = round(bis.readSAMUnit(6) * 90)
    
    raw_snout_width = bis.read(3)
    if raw_snout_width > 0:
        snout_enabled = True
        snout_width = raw_snout_width
        snout_height = bis.read(2) + 1
        snout_length = bis.read(3) + 1
        snout_offset = min(bis.read(3), 8 - snout_height)
    else:
        snout_enabled = False
        snout_width = snout_height = snout_length = snout_offset = 1  # Minimum values as in JS
    
    chest_size = round(bis.readUnit(5) * 100)
    chest = (chest_size > 0)
    
    wing_modes = ["none", "symmetric_dual", "symmetric_single", "asymmetric_single_l", "asymmetric_single_r"]
    wings_mode = wing_modes[min(bis.read(3), len(wing_modes) - 1)]
    wings_animation = "normal" if (wings_mode != "none" and bis.readBool()) else "none"
    
    cape = bis.readBool()
    emissive = bis.readBool()
    
    settings = {
        "enabled": True,  # Since V1 data is present
        "ears_mode": ears_mode,
        "ears_anchor": ears_anchor,
        "protrusions": protrusions,
        "tail_mode": tail_mode,
        "tail_segments": tail_segments,
        "tail_bend_1": tail_bend_1,
        "tail_bend_2": tail_bend_2,
        "tail_bend_3": tail_bend_3,
        "tail_bend_4": tail_bend_4,
        "snout": snout_enabled,
        "snout_width": snout_width,
        "snout_height": snout_height,
        "snout_length": snout_length,
        "snout_offset": snout_offset,
        "chest": chest,
        "chest_size": chest_size,
        "wings_mode": wings_mode,
        "wings_animation": wings_animation,
        "cape": cape,
        "emissive": emissive
    }
    
    return settings if setting_name is None else settings.get(setting_name)

def _get_ears_setting_v0(skin_image, setting_name):
    pixels = skin_image.load()
    # Extract the 4x4 pixel area starting at (0,32)
    pixels_area = [[pixels[x, 32 + y] for x in range(4)] for y in range(4)]
    
    # Get color names for each relevant pixel
    def get_color_name(pixel):
        rgb = get_rgb(pixel)
        return ears_v0_pixel_values.get(rgb, "none")
    
    # Ears mode and anchor (pixels[1,32] and [2,32])
    color = get_color_name(pixels_area[0][1])  # (1,32)
    ears_mode = ears_mode_from_color.get(color, "none")
    if ears_mode == "none":
        ears_anchor = "center"
    elif ears_mode == "behind":
        ears_mode = "out"  # Remapped as in JS
        ears_anchor = "back"
    else:
        color = get_color_name(pixels_area[0][2])  # (2,32)
        ears_anchor = ears_anchor_from_color.get(color, "center")
    
    # Protrusions (pixels[3,32])
    color = get_color_name(pixels_area[0][3])  # (3,32)
    protrusions = protrusions_from_color.get(color, "none")
    
    # Tail mode (pixels[0,33])
    color = get_color_name(pixels_area[1][0])  # (0,33)
    tail_mode = tail_mode_from_color.get(color, "none")
    
    # Tail bends and segments (pixels[1,33])
    color = get_color_name(pixels_area[1][1])  # (1,33)
    if color != "blue":
        r, g, b, a = pixels_area[1][1]
        tail_bend_1 = round(pixel_val_to_unit(255 - a) * 90)
        tail_bend_2 = round(pixel_val_to_unit(r) * 90)
        tail_bend_3 = round(pixel_val_to_unit(g) * 90)
        tail_bend_4 = round(pixel_val_to_unit(b) * 90)
        tail_segments = 1 + (tail_bend_2 != 0) + (tail_bend_3 != 0) + (tail_bend_4 != 0)
    else:
        tail_bend_1 = tail_bend_2 = tail_bend_3 = tail_bend_4 = 0
        tail_segments = 1
    
    # Snout (pixels[2,33] and [3,33])
    color = get_color_name(pixels_area[1][2])  # (2,33)
    if color != "blue":
        r, g, b = pixels_area[1][2][0], pixels_area[1][2][1], pixels_area[1][2][2]
        snout_width = min(7, r)
        snout_height = min(4, g)
        snout_length = min(8, b)
        snout_offset = min(8 - snout_height, pixels_area[1][3][1])  # G of (3,33)
        snout = (snout_width > 0) and (snout_height > 0) and (snout_length > 0)
    else:
        snout = False
        snout_width = snout_height = snout_length = snout_offset = 0
    snout_width = max(1, snout_width)
    snout_height = max(1, snout_height)
    snout_length = max(1, snout_length)
    
    # Chest and cape (pixels[3,33])
    color = get_color_name(pixels_area[1][3])  # (3,33)
    if color != "blue":
        r, _, b = pixels_area[1][3][0], pixels_area[1][3][1], pixels_area[1][3][2]
        chest_size = round(min(1, r / 128.0) * 100)
        chest = chest_size > 0
        cape = (b & 16) != 0
    else:
        chest_size = 0
        chest = False
        cape = False
    
    # Wings mode (pixels[0,34])
    color = get_color_name(pixels_area[2][0])  # (0,34)
    wings_mode = wings_mode_from_color.get(color, "none")
    
    # Wings animation (pixels[1,34])
    color = get_color_name(pixels_area[2][1])  # (1,34)
    wings_animation = "none" if color == "red" else "normal"
    
    # Emissive (pixels[2,34])
    color = get_color_name(pixels_area[2][2])  # (2,34)
    emissive = (color == "red")
    
    # Compile settings dictionary
    settings = {
        "enabled": True,  # Since V0 data is present
        "ears_mode": ears_mode,
        "ears_anchor": ears_anchor,
        "protrusions": protrusions,
        "tail_mode": tail_mode,
        "tail_segments": tail_segments,
        "tail_bend_1": tail_bend_1,
        "tail_bend_2": tail_bend_2,
        "tail_bend_3": tail_bend_3,
        "tail_bend_4": tail_bend_4,
        "snout": snout,
        "snout_width": snout_width,
        "snout_height": snout_height,
        "snout_length": snout_length,
        "snout_offset": snout_offset,
        "chest": chest,
        "chest_size": chest_size,
        "wings_mode": wings_mode,
        "wings_animation": wings_animation,
        "cape": cape,
        "emissive": emissive
    }
    
    return settings if setting_name is None else settings.get(setting_name)

# Удаление закодированной информации из скина
def remove_encoded_data(skin_image):
    if skin_image.mode != "RGBA":
        skin_image = skin_image.convert("RGBA")
    pixels = skin_image.load()
    rects = [
        (0, 8, 32, 16), (8, 0, 24, 8), (4, 16, 12, 20), (0, 20, 56, 32),
        (44, 16, 52, 20), (20, 48, 28, 52), (36, 48, 44, 52), (16, 52, 48, 64), (20, 16, 36, 20)
    ]
    for left, top, right, bottom in rects:
        for x in range(left, right):
            for y in range(top, bottom):
                r, g, b, _ = pixels[x, y]
                pixels[x, y] = (r, g, b, 255)
    return skin_image

# Генерация файла модели model.json
def generate_model_file(settings, texture_key, skin_image, nick_folder):
    # Извлечение параметров из settings
    arms_thin = settings.get("arms_thin", True)
    ears_mode = settings.get("ears_mode", "none")
    ears_anchor = settings.get("ears_anchor", "center")
    snout = settings.get("snout", False)
    w = settings.get("snout_width", 4)  # Ширина морды
    h = settings.get("snout_height", 2)  # Высота морды
    L = settings.get("snout_length", 1)  # Длина морды
    snout_offset = settings.get("snout_offset", 0)  # Смещение морды по Y, по умолчанию 0
    wings_mode = settings.get("wings_mode", "none")
    tail_exists = settings.get("tail_exists", True)
    tail_mode = settings.get("tail_mode", "none")
    tail_segments = settings.get("tail_segments", 1)
    cape = False

    # Базовая структура model.json
    model = {
        "textures": {
            "0": "./skin",
            "1": f"./{texture_key}" if texture_key and tail_exists else "./wing"
        },
        "elements": [
            # Head
            {
                "rotation": {"origin": [6, -4, 10], "angle": 0, "axis": "x"},
                "name": "Head",
                "from": [4, 8, 6],
                "to": [12, 16, 14],
                "faces": {
                    "east": {"uv": [0, 2, 2, 4], "texture": "#0"},
                    "south": {"uv": [6, 2, 8, 4], "texture": "#0"},
                    "north": {"uv": [2, 2, 4, 4], "texture": "#0"},
                    "west": {"uv": [4, 2, 6, 4], "texture": "#0"},
                    "up": {"uv": [4, 2, 2, 0], "texture": "#0"},
                    "down": {"uv": [6, 0, 4, 2], "texture": "#0"}
                }
            },
            # Hat Layer
            {
                "rotation": {"origin": [6, -4, 10], "angle": 0, "axis": "x"},
                "name": "Hat Layer",
                "from": [3.5, 7.5, 5.5],
                "to": [12.5, 16.5, 14.5],
                "faces": {
                    "east": {"uv": [8, 2, 10, 4], "texture": "#0"},
                    "south": {"uv": [14, 2, 16, 4], "texture": "#0"},
                    "north": {"uv": [10, 2, 12, 4], "texture": "#0"},
                    "west": {"uv": [12, 2, 14, 4], "texture": "#0"},
                    "up": {"uv": [12, 2, 10, 0], "texture": "#0"},
                    "down": {"uv": [14, 0, 12, 2], "texture": "#0"}
                }
            },
            # Body
            {
                "rotation": {"origin": [6, -4, 10], "angle": 0, "axis": "x"},
                "name": "Body",
                "from": [4, -4, 8],
                "to": [12, 8, 12],
                "faces": {
                    "east": {"uv": [4, 5, 5, 8], "texture": "#0"},
                    "south": {"uv": [8, 5, 10, 8], "texture": "#0"},
                    "north": {"uv": [5, 5, 7, 8], "texture": "#0"},
                    "west": {"uv": [7, 5, 8, 8], "texture": "#0"},
                    "up": {"uv": [7, 5, 5, 4], "texture": "#0"},
                    "down": {"uv": [9, 4, 7, 5], "texture": "#0"}
                }
            },
            # Body Layer
            {
                "rotation": {"origin": [6, -4, 10], "angle": 0, "axis": "x"},
                "name": "Body Layer",
                "from": [3.75, -4.25, 7.75],
                "to": [12.25, 8.25, 12.25],
                "faces": {
                    "east": {"uv": [4, 9, 5, 12], "texture": "#0"},
                    "south": {"uv": [8, 9, 10, 12], "texture": "#0"},
                    "north": {"uv": [5, 9, 7, 12], "texture": "#0"},
                    "west": {"uv": [7, 9, 8, 12], "texture": "#0"},
                    "up": {"uv": [7, 9, 5, 8], "texture": "#0"},
                    "down": {"uv": [9, 8, 7, 9], "texture": "#0"}
                }
            }
        ],
        "display": {
            "head": {"translation": [0, 14.5, 0], "scale": [0.5, 0.5, 0.5]},
            "firstperson_righthand": {"rotation": [1.75, 124, 0], "translation": [10.25, -2.25, -10.75], "scale": [0.5, 0.5, 0.5]},
            "thirdperson_lefthand": {"rotation": [75, 45, 0], "translation": [0, 1.75, 2.25], "scale": [0.375, 0.375, 0.375]},
            "firstperson_lefthand": {"rotation": [1.75, 124, 0], "translation": [10.25, -2.25, -10.75], "scale": [0.5, 0.5, 0.5]},
            "thirdperson_righthand": {"rotation": [75, 45, 0], "translation": [0, 1.75, 2.25], "scale": [0.375, 0.375, 0.375]},
            "ground": {"translation": [0, 4.5, 0], "scale": [0.5, 0.5, 0.5]},
            "gui": {"rotation": [-180, 45, -180], "translation": [-0.25, 1.5, -2.5], "scale": [0.5, 0.5, 0.5]},
            "fixed": {"rotation": [-90, 0, 0], "translation": [0, 0, -15]}
        }
    }

    # Руки в зависимости от arms_thin
    if arms_thin:
        model["elements"].extend([
            # Right Arm
            {
                "rotation": {"origin": [0, -4, 0], "angle": 45, "axis": "x"},
                "name": "Right Arm",
                "from": [12, -1, -2],
                "to": [15, 11, 2],
                "faces": {
                    "east": {"uv": [10, 5, 11, 8], "texture": "#0"},
                    "south": {"uv": [12.75, 5, 13.5, 8], "texture": "#0"},
                    "north": {"uv": [11, 5, 11.75, 8], "texture": "#0"},
                    "west": {"uv": [11.75, 5, 12.75, 8], "texture": "#0"},
                    "up": {"uv": [11.75, 5, 11, 4], "texture": "#0"},
                    "down": {"uv": [12.5, 4, 11.75, 5], "texture": "#0"}
                }
            },
            # Right Arm Layer
            {
                "rotation": {"origin": [0, -4, 0], "angle": 45, "axis": "x"},
                "name": "Right Arm Layer",
                "from": [11.75, -1.25, -2.25],
                "to": [15.25, 11.25, 2.25],
                "faces": {
                    "east": {"uv": [10, 9, 11, 12], "texture": "#0"},
                    "south": {"uv": [12.75, 9, 13.5, 12], "texture": "#0"},
                    "north": {"uv": [11, 9, 11.75, 12], "texture": "#0"},
                    "west": {"uv": [11.75, 9, 12.75, 12], "texture": "#0"},
                    "up": {"uv": [11.75, 9, 11, 8], "texture": "#0"},
                    "down": {"uv": [12.5, 8, 11.75, 9], "texture": "#0"}
                }
            },
            # Left Arm
            {
                "rotation": {"origin": [0, -4, 0], "angle": 45, "axis": "x"},
                "name": "Left Arm",
                "from": [1, -1, -2],
                "to": [4, 11, 2],
                "faces": {
                    "east": {"uv": [8, 13, 9, 16], "texture": "#0"},
                    "south": {"uv": [10.75, 13, 11.5, 16], "texture": "#0"},
                    "north": {"uv": [9, 13, 9.75, 16], "texture": "#0"},
                    "west": {"uv": [9.75, 13, 10.75, 16], "texture": "#0"},
                    "up": {"uv": [9.75, 13, 9, 12], "texture": "#0"},
                    "down": {"uv": [10.5, 12, 9.75, 13], "texture": "#0"}
                }
            },
            # Left Arm Layer
            {
                "rotation": {"origin": [0, -4, 0], "angle": 45, "axis": "x"},
                "name": "Left Arm Layer",
                "from": [0.75, -1.25, -2.25],
                "to": [4.25, 11.25, 2.25],
                "faces": {
                    "east": {"uv": [12, 13, 13, 16], "texture": "#0"},
                    "south": {"uv": [14.75, 13, 15.5, 16], "texture": "#0"},
                    "north": {"uv": [13, 13, 13.75, 16], "texture": "#0"},
                    "west": {"uv": [13.75, 13, 14.75, 16], "texture": "#0"},
                    "up": {"uv": [13.75, 13, 13, 12], "texture": "#0"},
                    "down": {"uv": [14.5, 12, 13.75, 13], "texture": "#0"}
                }
            }
        ])
    else:
        model["elements"].extend([
            # Right Arm (Wide)
            {
                "rotation": {"origin": [0, -4, 0], "angle": 45, "axis": "x"},
                "name": "Right Arm",
                "from": [12, -1, -2],
                "to": [16, 11, 2],
                "faces": {
                    "east": {"uv": [10, 5, 11, 8], "texture": "#0"},
                    "south": {"uv": [13, 5, 14, 8], "texture": "#0"},
                    "north": {"uv": [11, 5, 12, 8], "texture": "#0"},
                    "west": {"uv": [12, 5, 13, 8], "texture": "#0"},
                    "up": {"uv": [12, 5, 11, 4], "texture": "#0"},
                    "down": {"uv": [13, 4, 12, 5], "texture": "#0"}
                }
            },
            # Right Arm Layer (Wide)
            {
                "rotation": {"origin": [0, -4, 0], "angle": 45, "axis": "x"},
                "name": "Right Arm Layer",
                "from": [11.75, -1.25, -2.25],
                "to": [16.25, 11.25, 2.25],
                "faces": {
                    "east": {"uv": [10, 9, 11, 12], "texture": "#0"},
                    "south": {"uv": [13, 9, 14, 12], "texture": "#0"},
                    "north": {"uv": [11, 9, 12, 12], "texture": "#0"},
                    "west": {"uv": [12, 9, 13, 12], "texture": "#0"},
                    "up": {"uv": [12, 9, 11, 8], "texture": "#0"},
                    "down": {"uv": [13, 8, 12, 9], "texture": "#0"}
                }
            },
            # Left Arm (Wide)
            {
                "rotation": {"origin": [0, -4, 0], "angle": 45, "axis": "x"},
                "name": "Left Arm",
                "from": [0, -1, -2],
                "to": [4, 11, 2],
                "faces": {
                    "east": {"uv": [8, 13, 9, 16], "texture": "#0"},
                    "south": {"uv": [11, 13, 12, 16], "texture": "#0"},
                    "north": {"uv": [9, 13, 10, 16], "texture": "#0"},
                    "west": {"uv": [10, 13, 11, 16], "texture": "#0"},
                    "up": {"uv": [10, 13, 9, 12], "texture": "#0"},
                    "down": {"uv": [11, 12, 10, 13], "texture": "#0"}
                }
            },
            # Left Arm Layer (Wide)
            {
                "rotation": {"origin": [0, -4, 0], "angle": 45, "axis": "x"},
                "name": "Left Arm Layer",
                "from": [-0.25, -1.25, -2.25],
                "to": [4.25, 11.25, 2.25],
                "faces": {
                    "east": {"uv": [12, 13, 13, 16], "texture": "#0"},
                    "south": {"uv": [15, 13, 16, 16], "texture": "#0"},
                    "north": {"uv": [13, 13, 14, 16], "texture": "#0"},
                    "west": {"uv": [14, 13, 15, 16], "texture": "#0"},
                    "up": {"uv": [14, 13, 13, 12], "texture": "#0"},
                    "down": {"uv": [15, 12, 14, 13], "texture": "#0"}
                }
            }
        ])

    # Ноги
    model["elements"].extend([
        # Right Leg
        {
            "rotation": {"origin": [10, -4, 10], "angle": -22.5, "axis": "y"},
            "name": "Right Leg",
            "from": [7.9, -8.00122, -0.0698],
            "to": [11.9, -4.00122, 11.9302],
            "faces": {
                "east": {"uv": [0, 5, 1, 8], "texture": "#0", "rotation": 270},
                "south": {"uv": [2, 5, 1, 4], "texture": "#0"},
                "north": {"uv": [3, 4, 2, 5], "texture": "#0", "rotation": 180},
                "west": {"uv": [2, 5, 3, 8], "texture": "#0", "rotation": 90},
                "up": {"uv": [1, 5, 2, 8], "texture": "#0", "rotation": 180},
                "down": {"uv": [3, 5, 4, 8], "texture": "#0"}
            }
        },
        # Right Leg Layer
        {
            "rotation": {"origin": [17, -4, 10], "angle": -22.5, "axis": "y"},
            "name": "Right Leg Layer",
            "from": [8.18284, -8.25, 2.42878],
            "to": [12.68284, -3.75, 14.92878],
            "faces": {
                "east": {"uv": [0, 9, 1, 12], "texture": "#0", "rotation": 270},
                "south": {"uv": [2, 9, 1, 8], "texture": "#0"},
                "north": {"uv": [3, 8, 2, 9], "texture": "#0", "rotation": 180},
                "west": {"uv": [2, 9, 3, 12], "texture": "#0", "rotation": 90},
                "up": {"uv": [1, 9, 2, 12], "texture": "#0", "rotation": 180},
                "down": {"uv": [3, 9, 4, 12], "texture": "#0"}
            }
        },
        # Left Leg
        {
            "rotation": {"origin": [6, -4, 10], "angle": 22.5, "axis": "y"},
            "name": "Left Leg",
            "from": [4.1, -8.00122, -0.0698],
            "to": [8.1, -4.00122, 11.9302],
            "faces": {
                "east": {"uv": [4, 13, 5, 16], "texture": "#0", "rotation": 270},
                "south": {"uv": [6, 13, 5, 12], "texture": "#0"},
                "north": {"uv": [7, 12, 6, 13], "texture": "#0", "rotation": 180},
                "west": {"uv": [6, 13, 7, 16], "texture": "#0", "rotation": 90},
                "up": {"uv": [5, 13, 6, 16], "texture": "#0", "rotation": 180},
                "down": {"uv": [7, 13, 8, 16], "texture": "#0"}
            }
        },
        # Left Leg Layer
        {
            "rotation": {"origin": [6, -4, 10], "angle": 22.5, "axis": "y"},
            "name": "Left Leg Layer",
            "from": [3.85, -8.25, -0.25],
            "to": [8.35, -3.75, 12.25],
            "faces": {
                "east": {"uv": [0, 13, 1, 16], "texture": "#0", "rotation": 270},
                "south": {"uv": [2, 13, 1, 12], "texture": "#0"},
                "north": {"uv": [3, 12, 2, 13], "texture": "#0", "rotation": 180},
                "west": {"uv": [2, 13, 3, 16], "texture": "#0", "rotation": 90},
                "up": {"uv": [1, 13, 2, 16], "texture": "#0", "rotation": 180},
                "down": {"uv": [3, 13, 4, 16], "texture": "#0"}
            }
        }
    ])

    # Уши (функции add_*_ears предполагаются определёнными где-то ещё)
    if ears_mode != "none":
        if ears_mode == "around":
            add_around_ears(model, ears_anchor)
        elif ears_mode == "behind":
            add_behind_ears(model, ears_anchor)
        elif ears_mode == "out":
            add_out_ears(model, ears_anchor)

    if tail_mode != "none":
        # Базовые параметры хвоста из эталона
        origin = [8, 2.05, 16]
        from_pos = [7.95, -6.95, 12]
        to_pos = [8.05, 1.05, 24]
        faces = {
            "east": {"uv": [16, 4, 14, 7], "texture": "#0" if not tail_exists or not texture_key else "#1", "rotation": 90},
            "west": {"uv": [14, 4, 16, 7], "texture": "#0" if not tail_exists or not texture_key else "#1", "rotation": 270}
        }

        # Генерация сегментов хвоста
        for i in range(min(tail_segments, 4)):  # Ограничиваем 4 сегментами, как в настройках
            tail_element = {
                "rotation": {"origin": origin, "angle": 0, "axis": "z"},  # Устанавливаем angle=0 как в эталоне
                "name": "Tail",
                "from": from_pos,
                "to": to_pos,
                "faces": faces
            }
            model["elements"].append(tail_element)

    # Морда
    if snout:
        # Extract snout_offset from settings, default to 0 if not provided
        snout_offset = settings.get("snout_offset", 0)

        X_from = 8 - (w // 2)
        X_to = X_from + w
        if w % 2 == 1:
            X_to -= 1
        Y_from = 8 + snout_offset  # Apply snout_offset to shift Y-position
        Y_to = Y_from + h          # Y_to adjusts based on the new Y_from
        Z_from = 6 - L
        Z_to_snout = Z_from + 1
        Z_from_center = Z_to_snout
        Z_to_center = Z_from_center + (L - 1)
        uv_scale = 0.25
        snout_down_uv = [0, 1, w * uv_scale, 1 + h * uv_scale]
        snout_center_down_uv = [0, 1 + h * uv_scale, w * uv_scale, 1 + h * uv_scale * 2]
        model["elements"].extend([
            {
                "name": "Snout",
                "from": [X_from, Y_from, Z_from],
                "to": [X_to, Y_to, Z_to_snout],
                "faces": {
                    "east": {"uv": [1.75, 0, 2, h * uv_scale], "texture": "#0"},
                    "north": {"uv": [0, 0.5, w * uv_scale, 0.5 + h * uv_scale], "texture": "#0"},
                    "west": {"uv": [1.75, 0, 2, h * uv_scale], "texture": "#0"},
                    "up": {"uv": [0, 0.25, w * uv_scale, 0.5], "texture": "#0"},
                    "down": {"uv": snout_down_uv, "texture": "#0"}
                }
            },
            {
                "name": "SnoutCenter",
                "from": [X_from, Y_from, Z_from_center],
                "to": [X_to, Y_to, Z_to_center],
                "faces": {
                    "east": {"uv": [1.75, 1, 2, 1 + h * uv_scale], "texture": "#0"},
                    "west": {"uv": [1.75, 1, 2, 1 + h * uv_scale], "texture": "#0"},
                    "up": {"uv": [0, 0, w * uv_scale, 0.25], "texture": "#0"},
                    "down": {"uv": snout_center_down_uv, "texture": "#0"}
                }
            }
        ])
        
    # Хвост/крылья с обновлёнными UV-координатами для текстуры 32x32
    if tail_exists and wings_mode != "none":
        if wings_mode == "symmetric_single":
            model["elements"].append({
                "name": "55",
                "from": [8, -6, 12],
                "to": [8.1, 10, 32],
                "faces": {
                    "east": {"uv": [10, 8, 0, 16], "texture": "#1"},
                    "west": {"uv": [0, 8, 10, 16], "texture": "#1"}
                }
            })
        elif wings_mode == "symmetric_dual":
            model["elements"].extend([
                {
                    "rotation": {"origin": [2.15, 2, 21.25], "angle": -22.5, "axis": "y"},
                    "name": "55",
                    "from": [2.1, -6, 11.25],
                    "to": [2.2, 10, 31.25],
                    "faces": {
                        "east": {"uv": [10, 8, 0, 16], "texture": "#1"},
                        "west": {"uv": [0, 8, 10, 16], "texture": "#1"}
                    }
                },
                {
                    "rotation": {"origin": [13.85, 2, 21.25], "angle": 22.5, "axis": "y"},
                    "name": "55",
                    "from": [13.8, -6, 11.25],
                    "to": [13.9, 10, 31.25],
                    "faces": {
                        "east": {"uv": [10, 8, 0, 16], "texture": "#1"},
                        "west": {"uv": [0, 8, 10, 16], "texture": "#1"}
                    }
                }
            ])

    # Плащ
    if cape:
        model["elements"].extend([
            {
                "rotation": {"origin": [0, -8, 2], "angle": 0, "axis": "y"},
                "name": "9",
                "from": [0, 8, 9.9],
                "to": [4, 16, 10],
                "faces": {
                    "south": {"uv": [3, 8, 5, 9], "texture": "#0", "rotation": 270},
                    "north": {"uv": [9, 8, 11, 9], "texture": "#0", "rotation": 270}
                }
            },
            {
                "rotation": {"origin": [0, -8, 2], "angle": 0, "axis": "y"},
                "name": "10",
                "from": [12, 8, 9.9],
                "to": [16, 16, 10],
                "faces": {
                    "south": {"uv": [3, 4, 5, 5], "texture": "#0", "rotation": 270},
                    "north": {"uv": [9, 4, 11, 5], "texture": "#0", "rotation": 270}
                }
            },
            {
                "rotation": {"origin": [0, -8, 2], "angle": 0, "axis": "y"},
                "name": "11",
                "from": [0, 16, 9.9],
                "to": [16, 24, 10],
                "faces": {
                    "south": {"uv": [14, 7, 16, 11], "texture": "#0", "rotation": 270},
                    "north": {"uv": [6, 0, 10, 2], "texture": "#0"}
                }
            }
        ])

    # Группы
    model["groups"] = [
        {"color": 0, "children": [0, 1], "origin": [0, 24, 0], "name": "Head"},
        {"color": 0, "children": [2, 3], "origin": [0, 24, 0], "name": "Body"},
        {"color": 0, "children": [4, 5], "origin": [5, 22, 0], "name": "RightArm"},
        {"color": 0, "children": [6, 7], "origin": [-5 if arms_thin else -4, 22, 0], "name": "LeftArm"},
        {"color": 0, "children": [8, 9], "origin": [1.9, 12, 0], "name": "RightLeg"},
        {"color": 0, "children": [10, 11], "origin": [-1.9, 12, 0], "name": "LeftLeg"}
    ]
    model["credit"] = "By1NFERR"

    # Запись в файл
    with open(os.path.join(nick_folder, "model.json"), "w", encoding="utf-8") as f:
        json.dump(model, f, separators=(',', ':'))
    print("Generated model file 'model.json'.")

# Вспомогательные функции для добавления ушей
def add_around_ears(model, ears_anchor):
    z_shift = {"center": 9.9, "front": 6, "back": 14}[ears_anchor]
    model["elements"].extend([
        {
            "rotation": {"origin": [0, -8, 2], "angle": 0, "axis": "y"},
            "name": "9",
            "from": [0, 8, z_shift],
            "to": [4, 16, z_shift + 0.1],
            "faces": {
                "south": {"uv": [3, 8, 5, 9], "texture": "#0", "rotation": 270},
                "north": {"uv": [9, 8, 11, 9], "texture": "#0", "rotation": 270}
            }
        },
        {
            "rotation": {"origin": [0, -8, 2], "angle": 0, "axis": "y"},
            "name": "10",
            "from": [12, 8, z_shift],
            "to": [16, 16, z_shift + 0.1],
            "faces": {
                "south": {"uv": [3, 4, 5, 5], "texture": "#0", "rotation": 270},
                "north": {"uv": [9, 4, 11, 5], "texture": "#0", "rotation": 270}
            }
        },
        {
            "rotation": {"origin": [0, -8, 2], "angle": 0, "axis": "y"},
            "name": "11",
            "from": [0, 16, z_shift],
            "to": [16, 24, z_shift + 0.1],
            "faces": {
                "south": {"uv": [14, 7, 16, 11], "texture": "#0", "rotation": 270},
                "north": {"uv": [6, 0, 10, 2], "texture": "#0"}
            }
        }
    ])
    
def add_behind_ears(model, ears_anchor):
    z_shift = {"center": 9.9, "front": 6, "back": 14}[ears_anchor]
    model["elements"].extend([
        {
            "rotation": {"origin": [0, 4, 18], "angle": 0, "axis": "y"},
            "name": "7",
            "from": [4, 8, z_shift],
            "to": [4.1, 16, z_shift + 8],
            "faces": {
                "east": {"uv": [14, 9, 16, 11], "texture": "#0", "rotation": 270},
                "west": {"uv": [8, 0, 10, 2], "texture": "#0"}
            }
        },
        {
            "rotation": {"origin": [16, 4, 18], "angle": 0, "axis": "y"},
            "name": "8",
            "from": [11.9, 8, z_shift],
            "to": [12, 16, z_shift + 8],
            "faces": {
                "east": {"uv": [6, 0, 8, 2], "texture": "#0"},
                "west": {"uv": [14, 7, 16, 8.75], "texture": "#0", "rotation": 270}
            }
        }
    ])
    
def add_out_ears(model, ears_anchor):
    z_shift = {"center": 9.9, "front": 6, "back": 14}[ears_anchor]
    model["elements"].extend([
        {
            "rotation": {"origin": [0, 4, 18], "angle": 0, "axis": "y"},
            "name": "7",
            "from": [4, 8, z_shift],
            "to": [4.1, 16, z_shift + 8],
            "faces": {
                "east": {"uv": [14, 9, 16, 11], "texture": "#0", "rotation": 270},
                "west": {"uv": [8, 0, 10, 2], "texture": "#0"}
            }
        },
        {
            "rotation": {"origin": [16, 4, 18], "angle": 0, "axis": "y"},
            "name": "8",
            "from": [11.9, 8, z_shift],
            "to": [12, 16, z_shift + 8],
            "faces": {
                "east": {"uv": [6, 0, 8, 2], "texture": "#0"},
                "west": {"uv": [14, 7, 16, 8.75], "texture": "#0", "rotation": 270}
            }
        }
    ])

# Функции работы с GitHub
def get_current_build():
    """Получает текущий номер сборки из dynamicmcpack.repo.build."""
    url = f"https://api.github.com/repos/{REPO}/contents/dynamicmcpack.repo.build?ref={BRANCH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        content = base64.b64decode(response.json()['content']).decode()
        return int(content.strip())
    return 1

def git_blob_hash(content_bytes):
    header = f"blob {len(content_bytes)}\0".encode("utf-8")
    return hashlib.sha1(header + content_bytes).hexdigest()

def read_uuid_nick_file():
    """Читает файл uuid_nick.json."""
    with open(uuid_nick_file, "r", encoding="utf-8") as file:
        return json.load(file)

def get_nick_from_uuid(uuid):
    """Получает текущий ник игрока по UUID через API Mojang."""
    url = f"https://api.mojang.com/user/profile/{uuid}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()["name"]
    return None


def download_skin(uuid, temp_file_path):
    """Скачивает скин игрока по UUID."""
    url = f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid}"
    response = requests.get(url)
    if response.status_code == 200:
        textures = json.loads(base64.b64decode(response.json()["properties"][0]["value"]))
        skin_url = textures["textures"]["SKIN"]["url"]
        skin_response = requests.get(skin_url)
        with open(temp_file_path, "wb") as file:
            file.write(skin_response.content)
        return True
    return False

def create_model_properties(nick, folder_path):
    # Формируем содержимое с явными Unix-окончаниями строк
    content = f"items=totem_of_undying\nmodel=model\nnbt.display.Name=ipattern:*{nick}*".encode('utf-8')
    file_path = os.path.join(folder_path, "model.properties")
    
    # Записываем в бинарном режиме, чтобы избежать преобразований
    with open(file_path, "wb") as file:
        file.write(content)
    print(f"Файл {file_path} записан")
    
    # Проверяем записанное содержимое
    #with open(file_path, "rb") as file:
    #    written_content = file.read()
    #    if not written_content:
    #        print(f"Ошибка: Файл {file_path} пустой после записи")
    #    elif written_content != content:
    #        print(f"Ошибка: Содержимое {file_path} не совпадает:\nОжидалось:\n{content!r}\nЗаписано:\n{written_content!r}")
    #    else:
    #        print(f"Файл {file_path} успешно записан")
    
    # Для отладки: вычисляем и выводим хэш сразу после записи
    #calculated_hash = calculate_sha1(file_path)
    #print(f"SHA-1 хэш для {file_path}: {calculated_hash}")
    
def process_player(uuid, nick):
    # Создаем папку для ника, если ее нет
    nick_folder = os.path.join(base_folder, nick.lower())
    if not os.path.exists(nick_folder):
        os.makedirs(nick_folder)
    
    # Путь к временному файлу
    temp_file_path = os.path.join(nick_folder, "temp.png")
    
    # Скачиваем скин
    if download_skin(uuid, temp_file_path):
        # Открываем изображение скина
        skin_image = Image.open(temp_file_path).convert("RGBA")
        settings = get_ears_setting(skin_image, None)
        
        # Проверяем наличие хвоста/крыльев в области (16, 0, 24, 8)
        tail_region = skin_image.crop((16, 0, 24, 8))
        tail_exists = any(pixel[3] < 255 for pixel in tail_region.getdata())
        arms_thin = (skin_image.getpixel((54, 20))[:3] == (0, 0, 0))

        # Обновляем настройки, если они есть
        if settings:
            settings["arms_thin"] = arms_thin
            settings["tail_exists"] = tail_exists
            
        texture_key = None
        if tail_exists:
            # Извлекаем данные о хвосте/крыльях, если они есть
            ears_data = extract_ears_data(skin_image)
            if ears_data and "entries" in ears_data:
                if "tail" in ears_data["entries"]:
                    texture_key = "tail"
                elif "wing" in ears_data["entries"]:
                    texture_key = "wing"
                if texture_key:
                    data_b64 = ears_data["entries"][texture_key]
                    texture_data = base64.b64decode(data_b64)
                    with open(os.path.join(nick_folder, f"{texture_key}.png"), "wb") as f:
                        f.write(texture_data)
                    resize_texture_to_32x32(os.path.join(nick_folder, f"{texture_key}.png"))
            
            # Удаляем закодированные данные и сохраняем очищенный скин
            clean_img = remove_encoded_data(skin_image)
            clean_img.save(os.path.join(nick_folder, "skin.png"))
        else:
            # Если хвоста/крыльев нет, просто переименовываем temp.png в skin.png
            skin_file_path = os.path.join(nick_folder, "skin.png")
            if os.path.exists(skin_file_path):
                os.remove(skin_file_path)  # Удаляем существующий файл "skin.png"
            os.rename(temp_file_path, skin_file_path)

        # Генерируем model.json независимо от наличия хвоста/крыльев
        if settings is None:
            #print(f"В скине не найдены данные Ears Mod.")
            settings = {"arms_thin": arms_thin}
            generate_model_file(settings, None, skin_image, nick_folder)
        else:
            if texture_key:
                generate_model_file(settings, texture_key, skin_image, nick_folder)
            else:
                generate_model_file(settings, None, skin_image, nick_folder)

        print(settings)
        
        create_model_properties(nick, nick_folder)
        
        # Удаляем временный файл, если он остался (только если был обработан)
        if tail_exists and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
    else:
        print(f"Не удалось скачать скин для UUID {uuid}")

# Функции для Dynamic repo
def calculate_sha1(file_path):
    """Вычисляет SHA-1 хэш файла."""
    sha1 = hashlib.sha1()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha1.update(chunk)
    return sha1.hexdigest()

def generate_dynamic_repo_files():
    repo_folder = "PawTotems-git"
    files_dict = {}
    package_root = os.path.join("PawTotems-git", "PawTotems")

    additional_files = ["pack.png", "pack.mcmeta"]
    for file_name in additional_files:
        file_path = os.path.join(package_root, file_name)
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            if size == 0:
                print(f"Предупреждение: Файл {file_path} пустой")
            files_dict[file_name] = {"hash": calculate_sha1(file_path), "size": size}
    
    for root, _, files in os.walk(base_folder):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(file_path, package_root).replace("\\", "/")
            size = os.path.getsize(file_path)
            if size == 0:
                print(f"Предупреждение: Файл {file_path} пустой")
            files_dict[rel_path] = {"hash": calculate_sha1(file_path), "size": size}

    content_generic = {
        "formatVersion": 1,
        "content": {
            "parent": "",
            "remote_parent": "PawTotems",
            "files": files_dict
        }
    }
    content_generic_str = json.dumps(content_generic)  # Для хэша
    content_hash = hashlib.sha1(content_generic_str.encode()).hexdigest()

    repo_json = {
        "formatVersion": 1,
        "build": new_build,
        "name": "PawTotems",
        "contents": [
            {
                "id": "pack",
                "url": "content.json",
                "hash": content_hash,
                "required": True,
                "name": "PawTotems"
            }
        ]
    }

    with open(os.path.join(repo_folder, "content.json"), "w", encoding="utf-8") as f:
        json.dump(content_generic, f)
    with open(os.path.join(repo_folder, "dynamicmcpack.repo.json"), "w", encoding="utf-8") as f:
        json.dump(repo_json, f)
    with open(os.path.join(repo_folder, "dynamicmcpack.repo.build"), "w", encoding="utf-8") as f:
        f.write(str(new_build))

def process_player_wrapper(uuid, nick, max_retries=3, delay=1):
    """Обертка для обработки игрока с обработкой исключений и повторными попытками."""
    for attempt in range(1, max_retries + 1):
        try:
            process_player(uuid, nick)
            return  # Успешное выполнение — выходим из функции
        except Exception as e:
            print(f"Ошибка в обработке игрока {uuid} на попытке {attempt}: {e}")
            if attempt < max_retries:
                print(f"Повторная попытка через {delay} секунд...")
                time.sleep(delay)
            else:
                print(f"Не удалось обработать игрока {uuid} после {max_retries} попыток.")
                
def main():
    global new_build
    uuid_nick_data = read_uuid_nick_file()

    # Создаем пул потоков с заданным количеством рабочих (например, 10)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for uuid, nick in uuid_nick_data.items():
            current_nick = get_nick_from_uuid(uuid)
            if current_nick and current_nick != nick:
                old_folder = os.path.join(base_folder, nick.lower())
                if os.path.exists(old_folder):
                    shutil.rmtree(old_folder)
                uuid_nick_data[uuid] = current_nick
                with open(uuid_nick_file, "w", encoding="utf-8") as f:
                    json.dump(uuid_nick_data, f)
            # Добавляем задачу в пул потоков
            futures.append(executor.submit(process_player_wrapper, uuid, current_nick or nick))

        # Ожидаем завершения всех задач
        for future in concurrent.futures.as_completed(futures):
            future.result()  # Получаем результат или исключение

    # Обновляем Dynamic repo
    current_build = get_current_build()
    new_build = current_build + 1
    generate_dynamic_repo_files()
    commit_message = f"update"
    git_commit_and_push(commit_message)
    print(f"Сборка обновлена до {new_build}. Все файлы загружены.")

if __name__ == "__main__":
    if not os.path.exists(base_folder):
        os.makedirs(base_folder)
    main()
