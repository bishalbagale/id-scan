from datetime import datetime
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile

from flask import Flask, jsonify
from flask_cors import CORS
from PIL import Image, ImageEnhance, ImageFilter

try:
    import zxingcpp
except ImportError:
    zxingcpp = None


app = Flask(__name__)
CORS(app)

NAPS2_PROFILE = "nScanId"
NAPS2_PATH = r"C:\Program Files\NAPS2\naps2.console.exe"
DEBUG_ENV_VAR = "MOTEL_SCANNER_DEBUG"


def debug_enabled():
    return os.environ.get(DEBUG_ENV_VAR, "").lower() in {"1", "true", "yes", "on"}


def make_temp_scan_path():
    descriptor, path = tempfile.mkstemp(prefix="motel_scan_", suffix=".png")
    os.close(descriptor)
    return path


def capture_scan(output_path):
    subprocess.run(
        [NAPS2_PATH, "-p", NAPS2_PROFILE, "-o", output_path, "--force"],
        check=True,
        capture_output=True,
        text=True,
    )


def normalize_barcode_text(text):
    return (
        text.replace("<LF>", "\n")
        .replace("<CR>", "\n")
        .replace("<RS>", "\n")
        .replace("\r", "\n")
    )


def extract_tag(tag, text):
    normalized = normalize_barcode_text(text)
    for line in normalized.splitlines():
        if line.startswith(tag):
            return line[len(tag):].strip()

    match = re.search(rf"{re.escape(tag)}([^\n]+)", normalized)
    return match.group(1).strip() if match else ""


def parse_aamva_text(raw_data):
    clean_data = normalize_barcode_text(raw_data)
    zip_code = extract_tag("DAK", clean_data)
    return {
        "firstName": extract_tag("DAC", clean_data) or extract_tag("DCT", clean_data),
        "lastName": extract_tag("DCS", clean_data) or extract_tag("DAB", clean_data),
        "address": extract_tag("DAG", clean_data),
        "city": extract_tag("DAI", clean_data),
        "state": extract_tag("DAJ", clean_data),
        "zip": zip_code[:5] if zip_code else "",
        "licenseNumber": extract_tag("DAQ", clean_data),
    }


def expanded_box(box, width, height, padding=8):
    left, top, right, bottom = box
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(width, right + padding),
        min(height, bottom + padding),
    )


def crop_to_card(gray_image):
    mask = gray_image.point(lambda pixel: 255 if pixel > 25 else 0)
    box = mask.getbbox()
    if not box:
        return gray_image
    return gray_image.crop(expanded_box(box, gray_image.width, gray_image.height, 10))


def crop_regions(gray_image):
    card = crop_to_card(gray_image)
    width, height = card.size
    regions = [("card", card)]

    if width >= 100 and height >= 100:
        regions.extend(
            [
                ("card_top_half", card.crop((0, 0, width, int(height * 0.48)))),
                (
                    "barcode_upper_center",
                    card.crop(
                        (
                            int(width * 0.18),
                            0,
                            int(width * 0.88),
                            int(height * 0.34),
                        )
                    ),
                ),
                (
                    "barcode_upper_band",
                    card.crop(
                        (
                            int(width * 0.12),
                            0,
                            int(width * 0.92),
                            int(height * 0.28),
                        )
                    ),
                ),
                (
                    "barcode_right_band",
                    card.crop(
                        (
                            int(width * 0.62),
                            int(height * 0.18),
                            int(width * 0.98),
                            int(height * 0.90),
                        )
                    ),
                ),
                (
                    "barcode_bottom_band",
                    card.crop(
                        (
                            int(width * 0.12),
                            int(height * 0.66),
                            int(width * 0.92),
                            int(height * 0.98),
                        )
                    ),
                ),
                (
                    "barcode_left_band",
                    card.crop(
                        (
                            int(width * 0.02),
                            int(height * 0.18),
                            int(width * 0.38),
                            int(height * 0.90),
                        )
                    ),
                ),
            ]
        )

    return regions


def image_variants(image):
    gray = image.convert("L")
    contrast = ImageEnhance.Contrast(gray).enhance(2.0)
    median = contrast.filter(ImageFilter.MedianFilter(size=3))

    variants = [
        ("gray_full", gray),
        ("contrast_full", contrast),
        ("contrast_median3_full", median),
    ]

    for region_name, region in crop_regions(gray):
        region_contrast = ImageEnhance.Contrast(region).enhance(2.0)
        region_high_contrast = ImageEnhance.Contrast(region).enhance(3.0)
        region_median = region_contrast.filter(ImageFilter.MedianFilter(size=3))
        variants.extend(
            [
                (f"gray_{region_name}", region),
                (f"contrast_{region_name}", region_contrast),
                (f"contrast3_{region_name}", region_high_contrast),
                (f"contrast_median3_{region_name}", region_median),
            ]
        )

    seen = set()
    unique_variants = []
    for name, variant in variants:
        if name not in seen and variant.width > 0 and variant.height > 0:
            seen.add(name)
            unique_variants.append((name, variant))
    return unique_variants


def decoder_configs():
    return [
        ("local_average", zxingcpp.Binarizer.LocalAverage),
        ("global_histogram", zxingcpp.Binarizer.GlobalHistogram),
        ("fixed_threshold", zxingcpp.Binarizer.FixedThreshold),
        ("bool_cast", zxingcpp.Binarizer.BoolCast),
    ]


def barcode_error_metadata(barcode):
    return {
        "format": str(getattr(barcode, "format", "")),
        "error": str(getattr(barcode, "error", "")),
        "position": str(getattr(barcode, "position", "")),
    }


def decode_pdf417(variants):
    if zxingcpp is None:
        raise RuntimeError("zxing-cpp is not installed")

    attempted = []
    barcode_errors = []
    for variant_name, variant_image in variants:
        for config_name, binarizer in decoder_configs():
            attempt_name = f"{variant_name}:{config_name}"
            attempted.append(attempt_name)
            results = zxingcpp.read_barcodes(
                variant_image,
                formats=zxingcpp.BarcodeFormat.PDF417,
                binarizer=binarizer,
            )
            if results:
                return results[0], attempt_name, attempted, barcode_errors

    for variant_name, variant_image in variants:
        for config_name, binarizer in decoder_configs():
            results = zxingcpp.read_barcodes(
                variant_image,
                formats=zxingcpp.BarcodeFormat.PDF417,
                binarizer=binarizer,
                return_errors=True,
            )
            for barcode in results:
                if getattr(barcode, "error", None):
                    barcode_errors.append(
                        {
                            "attempt": f"{variant_name}:{config_name}",
                            **barcode_error_metadata(barcode),
                        }
                    )

    return None, None, attempted, barcode_errors


def debug_directory():
    desktop = Path.home() / "Desktop"
    base = desktop if desktop.exists() else Path.home()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = base / "MotelScannerDebug" / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def dump_debug_files(scan_path, variants, metadata):
    if not debug_enabled():
        return None

    output_dir = debug_directory()
    if os.path.exists(scan_path):
        shutil.copy2(scan_path, output_dir / "original.png")

    for variant_name, variant_image in variants:
        variant_image.save(output_dir / f"{variant_name}.png")

    with open(output_dir / "metadata.json", "w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)

    return str(output_dir)


def error_response(error_code, message, status_code, debug_path=None):
    payload = {
        "status": "error",
        "errorCode": error_code,
        "message": message,
    }
    if debug_path:
        payload["debugPath"] = debug_path
    return jsonify(payload), status_code


@app.route("/scan", methods=["POST"])
def scan_and_decode():
    temp_image_path = make_temp_scan_path()
    variants = []

    try:
        capture_scan(temp_image_path)

        with Image.open(temp_image_path) as scanned_image:
            scanned_image.load()
            variants = image_variants(scanned_image)
            barcode, decode_variant, attempted, barcode_errors = decode_pdf417(variants)

        if barcode is None:
            debug_path = dump_debug_files(
                temp_image_path,
                variants,
                {
                    "errorCode": "BARCODE_NOT_FOUND",
                    "attemptedVariants": attempted,
                    "barcodeErrors": barcode_errors,
                },
            )
            return error_response(
                "BARCODE_NOT_FOUND",
                "PDF417 barcode was not decoded. Check scan quality and scanner settings.",
                400,
                debug_path,
            )

        extracted_data = parse_aamva_text(barcode.text)
        if not any(extracted_data.values()):
            debug_path = dump_debug_files(
                temp_image_path,
                variants,
                {
                    "errorCode": "AAMVA_PARSE_FAILED",
                    "decodeVariant": decode_variant,
                },
            )
            return error_response(
                "AAMVA_PARSE_FAILED",
                "Barcode decoded, but no expected AAMVA fields were extracted.",
                422,
                debug_path,
            )

        return jsonify(
            {
                "status": "success",
                "data": extracted_data,
                "decodeVariant": decode_variant,
            }
        )

    except subprocess.CalledProcessError as exc:
        return error_response(
            "SCANNER_COMMAND_FAILED",
            f"NAPS2 scan command failed with exit code {exc.returncode}.",
            500,
        )
    except Exception as exc:
        debug_path = dump_debug_files(
            temp_image_path,
            variants,
            {
                "errorCode": "SERVER_ERROR",
                "exceptionType": type(exc).__name__,
            },
        )
        return error_response("SERVER_ERROR", str(exc), 500, debug_path)
    finally:
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)


if __name__ == "__main__":
    app.run(port=5000)
