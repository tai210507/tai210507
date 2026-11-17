#!/usr/bin/env python3
"""Render the profile's pixel title as an animated WebP.

Requires Python 3 + Pillow, FFmpeg, and Node.js + sharp.
Usage: python scripts/render_typewriter.py /path/to/original-recording.mp4
The user-supplied recording is intentionally kept outside this repository.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SIZE = (1200, 900)
FRAME_COUNT = 65
FRAME_MS = 100
LETTER_LEFTS = (194, 362, 530, 698, 866)
NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)


def visible_letters(frame):
    """A 300 ms lead-in, 300 ms per letter, then a five-second hold."""
    return min(5, frame // 3)


def make_overlay(source, count, cursor_on):
    root = ET.fromstring(source)
    title = next(g for g in root.iter(f"{{{NS}}}g")
                 if g.attrib.get("aria-label") == "FAITT")
    for layer in title:
        for pixel in list(layer):
            x = int(pixel.attrib["x"])
            letter = max(i for i, left in enumerate(LETTER_LEFTS) if x >= left)
            if letter >= count:
                layer.remove(pixel)
    if cursor_on:
        x = LETTER_LEFTS[0] if count == 0 else LETTER_LEFTS[0] + count * 168 - 12
        ET.SubElement(title, f"{{{NS}}}rect", {
            "x": str(x), "y": "356", "width": "8", "height": "192",
            "fill": "#E8B77D", "stroke": "#08070A", "stroke-width": "2",
        })
    return ET.tostring(root, encoding="unicode")


def render_overlays(source, directory):
    jobs = []
    for count in range(6):
        for cursor_on in (False, True):
            jobs.append({
                "svg": make_overlay(source, count, cursor_on),
                "path": str(directory / f"{count}-{int(cursor_on)}.png"),
            })
    node = os.environ.get("CODEX_PRIMARY_RUNTIME_NODE", "node")
    renderer = r"""
const fs = require('fs');
const sharp = require(require.resolve('sharp', {
  paths: [process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES || process.cwd()]
}));
const jobs = JSON.parse(fs.readFileSync(0, 'utf8'));
(async () => {
  for (const job of jobs) {
    await sharp(Buffer.from(job.svg)).png().toFile(job.path);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run([node, "-e", renderer], input=json.dumps(jobs),
                   text=True, check=True)
    return {(count, cursor): Image.open(directory / f"{count}-{int(cursor)}.png").convert("RGBA")
            for count in range(6) for cursor in (False, True)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_video", type=Path)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "assets/interstellar-typewriter-banner.webp")
    parser.add_argument("--proof", type=Path,
                        help="Optional contact sheet for checking all title states")
    args = parser.parse_args()
    overlay_source = (ROOT / "assets/interstellar-pixel-overlay.svg").read_text()

    with tempfile.TemporaryDirectory(prefix="faitt-typewriter-") as temp:
        directory = Path(temp)
        raw = directory / "background.rgb"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "24",
            "-i", str(args.source_video), "-vf",
            "crop=1536:1152:512:64,scale=1200:900:flags=lanczos,fps=10",
            "-frames:v", str(FRAME_COUNT), "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-y", str(raw),
        ], check=True)
        frame_bytes = SIZE[0] * SIZE[1] * 3
        if raw.stat().st_size != FRAME_COUNT * frame_bytes:
            raise ValueError("The recording must include 6.5 seconds starting at 00:24")
        overlays = render_overlays(overlay_source, directory)
        frames = []
        with raw.open("rb") as stream:
            first = None
            for index in range(FRAME_COUNT):
                background = Image.frombytes("RGB", SIZE, stream.read(frame_bytes))
                if first is None:
                    first = background.copy()
                # Join the background loop before the title restarts.
                if index >= FRAME_COUNT - 5:
                    background = Image.blend(background, first, (index - 59) / 5)
                count = visible_letters(index)
                cursor = count < 5 or ((index - 15) // 5) % 2 == 0
                frame = Image.alpha_composite(background.convert("RGBA"), overlays[count, cursor])
                frames.append(frame.convert("RGB"))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        frames[0].save(args.output, format="WEBP", save_all=True,
                       append_images=frames[1:], duration=FRAME_MS, loop=0,
                       quality=88, method=6, allow_mixed=True)
        if args.proof:
            indices = (0, 3, 6, 9, 12, 15)
            proof = Image.new("RGB", (1200, 960), "#09090B")
            draw = ImageDraw.Draw(proof)
            for cell, index in enumerate(indices):
                x, y = (cell % 3) * 400, (cell // 3) * 480
                proof.paste(frames[index].resize((400, 300)), (x, y + 26))
                draw.text((x + 12, y + 8), f"{index * FRAME_MS} ms: {'FAITT'[:visible_letters(index)] or 'cursor'}", fill="#FFF0D9")
            proof.crop((0, 0, 1200, 806)).save(args.proof)
        print(json.dumps({"output": str(args.output), "frames": len(frames),
                          "duration_ms": FRAME_COUNT * FRAME_MS,
                          "size_bytes": args.output.stat().st_size}))


if __name__ == "__main__":
    main()
