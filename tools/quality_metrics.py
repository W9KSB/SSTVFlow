"""Independent image comparison; never imports receiver code.

Use a known synthetic source as ground truth. Comparing with another decoder's
JPEG measures agreement only: its filtering, chroma, alignment and compression
are not evidence of the original transmitted pixels. No registration, resizing,
denoising or sharpening is applied to either image before measurement.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def luminance(rgb):
    return np.asarray(rgb, dtype=np.float64) @ np.array([0.299, 0.587, 0.114])


def compare_images(reference, decoded):
    reference = np.asarray(reference, dtype=np.float64)
    decoded = np.asarray(decoded, dtype=np.float64)
    if reference.shape != decoded.shape or reference.ndim != 3 or reference.shape[2] != 3:
        raise ValueError("images must have identical RGB dimensions")
    error = decoded - reference
    mse = float(np.mean(error * error))
    target_y, output_y = luminance(reference), luminance(decoded)
    y_mse = float(np.mean((target_y - output_y) ** 2))
    target_edges = np.concatenate([np.diff(target_y, axis=1).ravel(), np.diff(target_y, axis=0).ravel()])
    output_edges = np.concatenate([np.diff(output_y, axis=1).ravel(), np.diff(output_y, axis=0).ravel()])
    significant = abs(target_edges) >= 8
    edge_energy = float(np.sum(target_edges[significant] ** 2))
    return {
        "width": int(reference.shape[1]), "height": int(reference.shape[0]),
        "rgb_mse": mse, "rgb_mae": float(np.mean(abs(error))),
        "rgb_psnr_db": None if mse == 0 else float(10 * np.log10(255 ** 2 / mse)),
        "luminance_psnr_db": None if y_mse == 0 else float(10 * np.log10(255 ** 2 / y_mse)),
        "psnr_infinite": mse == 0,
        "edge_gradient_gain": None if edge_energy == 0 else float(
            np.dot(target_edges[significant], output_edges[significant]) / edge_energy),
        "edge_gradient_rmse": None if not significant.any() else float(np.sqrt(np.mean(
            (target_edges[significant] - output_edges[significant]) ** 2))),
    }


def straight_edge_drift(decoded, edge_x, row_start, row_stop, radius=5):
    """Fit the strongest vertical edge near a known boundary across row range.

    The boundary coordinate is the first pixel to its right. Report slope and
    spread, not a general-purpose slant estimate. Validity requires a strong,
    isolated vertical edge in the requested window for every selected row.
    """
    y = luminance(decoded)
    if not 0 <= row_start < row_stop <= y.shape[0] or radius < 1:
        raise ValueError("invalid edge row range or radius")
    first, last = max(0, edge_x - radius - 1), min(y.shape[1] - 1, edge_x + radius)
    if first >= last:
        raise ValueError("edge coordinate is outside the image")
    gradients = abs(np.diff(y[row_start:row_stop], axis=1)[:, first:last])
    locations = np.argmax(gradients, axis=1) + first + 1
    rows = np.arange(row_start, row_stop)
    slope, intercept = np.polyfit(rows, locations, 1) if len(rows) > 1 else (0.0, float(locations[0]))
    return {
        "expected_edge_x": edge_x, "row_start": row_start, "row_stop_exclusive": row_stop,
        "slope_pixels_per_row": float(slope),
        "fitted_drift_pixels": float(slope * (len(rows) - 1)),
        "peak_to_peak_pixels": int(np.ptp(locations)),
        "position_rmse_pixels": float(np.sqrt(np.mean((locations - edge_x) ** 2))),
        "fit_residual_rmse_pixels": float(np.sqrt(np.mean((locations - (slope * rows + intercept)) ** 2))),
        "minimum_peak_gradient": float(np.max(gradients, axis=1).min()),
        "rows_with_peak_on_search_boundary": int(np.count_nonzero(
            (locations == first + 1) | (locations == last))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("decoded", type=Path)
    parser.add_argument("--reference-kind", choices=["ground_truth", "decoded_reference"], default="ground_truth")
    parser.add_argument("--edge", type=int, action="append", default=[])
    parser.add_argument("--edge-rows", nargs=2, type=int, metavar=("START", "STOP"), default=[8, 56])
    parser.add_argument("--contact-sheet", type=Path)
    args = parser.parse_args()
    with Image.open(args.reference) as source:
        reference = source.convert("RGB")
    with Image.open(args.decoded) as source:
        decoded = source.convert("RGB")
    try:
        result = compare_images(reference, decoded)
        result["reference_kind"] = args.reference_kind
        result["interpretation"] = (
            "Fidelity against known original pixels; PSNR null means exact equality."
            if args.reference_kind == "ground_truth" else
            "Agreement with another decoder output, not fidelity to original transmitted pixels; JPEG artifacts are included."
        )
        if args.edge:
            result["straight_edges"] = [straight_edge_drift(decoded, x, *args.edge_rows) for x in args.edge]
        if args.contact_sheet:
            sheet = Image.new("RGB", (reference.width * 2, reference.height + 24), "white")
            sheet.paste(reference, (0, 24))
            sheet.paste(decoded, (reference.width, 24))
            draw = ImageDraw.Draw(sheet)
            draw.text((4, 4), "Reference: " + args.reference_kind, fill="black")
            draw.text((reference.width + 4, 4), "Decoded output", fill="black")
            sheet.save(args.contact_sheet)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
