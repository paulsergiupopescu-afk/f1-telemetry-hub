"""Import Brendon Leigh's image-based PDF setup cards into structured JSON.

This is a development-time importer. The application reads the generated JSON and
does not need PDF or OCR dependencies at runtime.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re
import subprocess
import tempfile

import fitz
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "setup_packages" / "1.5"
OUTPUT = ROOT / "assets" / "brendon_leigh_setups_v1_5.json"
CACHE = ROOT / "setup_packages" / "ocr_cache_v1_5"
TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
VARIANTS = {
    "race": (.17, .055, .50, .435),
    "qualifying": (.67, .055, .985, .435),
    "intermediates": (.17, .54, .50, .925),
    "wets": (.67, .54, .985, .925),
}


def track_name(path: Path) -> str:
    name = re.sub(r"(?i)^F1\s*26\s+", "", path.stem)
    name = re.sub(r"(?i)\s+(complete|compete).*?$", "", name).strip()
    return {
        "Baku": "Azerbaijan", "Jeddah": "Saudi Arabia", "Silverstone": "Britain",
        "Spa": "Belgium", "Spain": "Barcelona", "Texas": "Texas",
        "Vegas": "Las Vegas", "Madring": "Madrid",
    }.get(name, name)


def text_mask(image: Image.Image) -> Image.Image:
    image = image.convert("RGB").resize((image.width * 2, image.height * 2))
    source = image.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue = source[x, y]
            bright = max(red, green, blue)
            white_text = bright > 175 and min(red, green, blue) > 125
            red_text = red > 150 and red > green * 1.45 and red > blue * 1.25
            source[x, y] = (0, 0, 0) if white_text or red_text else (255, 255, 255)
    return image


def ocr(image: Image.Image, temp: Path, key: str) -> str:
    path = temp / f"{key}.png"
    text_mask(image).save(path)
    result = subprocess.run(
        [str(TESSERACT), str(path), "stdout", "--psm", "6"],
        check=True, capture_output=True, text=True, encoding="utf-8")
    return result.stdout


def values(line: str) -> list[float]:
    # The setup font makes red zero look like O and red five look like S.
    line = re.sub(r"-\s*[OQ](?=\s|$)", "-0", line, flags=re.I)
    line = re.sub(r"-\s*S(?=\s*REAR|\s*RIGHT|\s|$)", "-5 ", line, flags=re.I)
    return [float(value) for value in re.findall(r"\d+(?:\.\d+)?", line)]


def group(text: str, marker: str, count: int) -> list[float]:
    line = next((line for line in text.upper().splitlines() if marker in line), "")
    found = values(line)
    if len(found) < count:
        raise ValueError(f"{marker}: expected {count}, got {found!r} from {line!r}")
    return found[-count:]


def parse(text: str) -> dict:
    aero = group(text, "AERODYNAMICS", 2)
    transmission = group(text, "TRANSMISSION", 2)
    suspension = group(text, "SUSPENSION", 2)
    rollbars = group(text, "ROLLBARS", 2)
    try:
        ride_height = group(text, "HEIGHT", 2)
    except ValueError:
        lines = text.upper().splitlines()
        rollbar_index = next(i for i, line in enumerate(lines) if "ROLLBARS" in line)
        ride_height = values(next(line for line in lines[rollbar_index + 1:] if line.strip()))[-2:]
        if len(ride_height) < 2:
            raise ValueError(f"Ride height not recognized after roll bars: {ride_height!r}")
    brakes = group(text, "BRAKES", 2)
    pressure_lines = [values(line) for line in text.upper().splitlines()
                      if "LEFT" in line and "RIGHT" in line]
    if len(pressure_lines) < 2 or any(len(row) < 2 for row in pressure_lines[-2:]):
        raise ValueError(f"Tyre pressures not recognized: {pressure_lines!r}")
    front_tyres, rear_tyres = pressure_lines[-2][-2:], pressure_lines[-1][-2:]
    camber_line = next((line for line in text.upper().splitlines()
                        if "CAMBER" in line), "CAMBER/TOE ALL LEFT")
    camber_toe = camber_line.split("CAMBER/TOE", 1)[-1].strip() or "ALL LEFT"
    brake_line = next(line for line in text.upper().splitlines() if "BRAKES" in line)
    brake_numbers = values(brake_line)
    brake_pressure = brake_numbers[0]
    brake_bias = brake_numbers[1:]
    result = {
        "front_wing": int(aero[0]), "rear_wing": int(aero[1]),
        "on_throttle_diff": int(transmission[0]),
        "off_throttle_diff": int(transmission[1]),
        "camber_toe": camber_toe,
        "front_suspension": int(suspension[0]), "rear_suspension": int(suspension[1]),
        "front_anti_roll_bar": int(rollbars[0]), "rear_anti_roll_bar": int(rollbars[1]),
        "front_ride_height": int(ride_height[0]), "rear_ride_height": int(ride_height[1]),
        "brake_pressure": int(brake_pressure),
        "brake_bias": [int(value) for value in brake_bias],
        "front_left_pressure": front_tyres[0], "front_right_pressure": front_tyres[1],
        "rear_left_pressure": rear_tyres[0], "rear_right_pressure": rear_tyres[1],
    }
    validate(result)
    return result


def validate(setup: dict) -> None:
    ranges = {
        "front_wing": (0, 50), "rear_wing": (0, 50),
        "on_throttle_diff": (10, 100), "off_throttle_diff": (10, 100),
        "front_suspension": (1, 41), "rear_suspension": (1, 41),
        "front_anti_roll_bar": (1, 21), "rear_anti_roll_bar": (1, 21),
        "front_ride_height": (15, 50), "rear_ride_height": (30, 60),
        "brake_pressure": (80, 100), "front_left_pressure": (20, 30),
        "front_right_pressure": (20, 30), "rear_left_pressure": (19, 27),
        "rear_right_pressure": (19, 27),
    }
    invalid = {key: value for key, value in setup.items() if key in ranges and
               not ranges[key][0] <= float(value) <= ranges[key][1]}
    if not setup["brake_bias"] or any(not 50 <= value <= 70 for value in setup["brake_bias"]):
        invalid["brake_bias"] = setup["brake_bias"]
    if invalid:
        raise ValueError(f"Values outside game ranges: {invalid}")


def render_pdf(path: Path) -> Image.Image:
    document = fitz.open(path)
    pixmap = document[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def import_panel(path: Path, variant: str, box: tuple[float, ...], temp: Path):
    cache_path = CACHE / f"{path.stem}-{variant}.txt"
    if cache_path.exists():
        raw = cache_path.read_text(encoding="utf-8")
    else:
        page = render_pdf(path)
        width, height = page.size
        crop = page.crop((int(box[0] * width), int(box[1] * height),
                          int(box[2] * width), int(box[3] * height)))
        raw = ocr(crop, temp, f"{path.stem}-{variant}")
        CACHE.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(raw, encoding="utf-8")
    return track_name(path), variant, parse(raw), raw


def main() -> None:
    if not TESSERACT.exists():
        raise SystemExit(f"Tesseract not found: {TESSERACT}")
    pdfs = sorted(path for path in SOURCE.glob("*.pdf")
                  if not path.name.lower().startswith("please read"))
    imported: dict[str, dict] = {}
    failures = []
    with tempfile.TemporaryDirectory(prefix="brendon-setup-import-") as folder:
        temp = Path(folder)
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = {pool.submit(import_panel, pdf, variant, box, temp):
                    (pdf, variant) for pdf in pdfs for variant, box in VARIANTS.items()}
            for future in as_completed(jobs):
                pdf, variant = jobs[future]
                try:
                    track, variant, setup, _raw = future.result()
                    imported.setdefault(track, {})[variant] = setup
                    print(f"OK {track:14} {variant}")
                except Exception as exc:
                    failures.append(f"{pdf.name} [{variant}]: {exc}")
                    print(f"FAIL {pdf.name} [{variant}]: {exc}")
    if failures:
        raise SystemExit("\n".join(failures))
    payload = {
        "schema_version": 1, "author": "Brendon Leigh", "package_version": "1.5",
        "source_date": "2026-07-16", "tracks": dict(sorted(imported.items())),
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Imported {len(imported)} tracks / {sum(len(x) for x in imported.values())} setup variants")
    print(OUTPUT)


if __name__ == "__main__":
    main()
