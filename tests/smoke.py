"""End-to-end smoke test: build a 3-shot video with big words on screen, index it, and query it.

Run: python tests/smoke.py  (needs ffmpeg and an installed `eyes`)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WORDS = ["ALPHA", "BRAVO", "CHARLIE"]


def eyes(*args: str, env: dict) -> str:
    result = subprocess.run(["eyes", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    print(f"$ eyes {' '.join(args)}\n{result.stdout}{result.stderr}")
    if result.returncode not in (0, 2):
        sys.exit(f"eyes {args[0]} failed with {result.returncode}")
    return result.stdout


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="eyes-smoke-"))
    env = {**os.environ, "EYES_HOME": str(work / "cache")}
    colors = [(30, 60, 160), (160, 40, 40), (30, 130, 60)]
    font = ImageFont.load_default(size=150)
    for i, (word, color) in enumerate(zip(WORDS, colors)):
        img = Image.new("RGB", (1280, 720), color)
        draw = ImageDraw.Draw(img)
        box = draw.textbbox((0, 0), word, font=font)
        draw.text(((1280 - box[2]) / 2, (720 - box[3]) / 2), word, fill="white", font=font)
        img.save(work / f"shot{i}.png")
    video = work / "smoke.mp4"
    inputs = []
    for i in range(3):
        inputs += ["-loop", "1", "-t", "3", "-i", str(work / f"shot{i}.png")]
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-f", "lavfi", "-t", "9", "-i", "sine=frequency=440",
                    "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p,fps=30[v]",
                    "-map", "[v]", "-map", "3:a", "-shortest", str(video)], check=True)

    eyes("setup", env=env)
    eyes("index", str(video), env=env)
    vdir = next((work / "cache").glob("smoke-*"))
    shots = json.loads((vdir / "shots.json").read_text(encoding="utf-8"))["shots"]
    ocr = json.loads((vdir / "ocr.json").read_text(encoding="utf-8"))
    assert len(shots) == 3, f"expected 3 shots, got {len(shots)}"
    assert (vdir / "overview.md").exists() and list((vdir / "sheets").glob("overview_*.jpg"))
    if ocr.get("engine"):
        found = eyes("search", "BRAVO", env=env)
        assert "[shown]" in found, f"{ocr['engine']} did not read BRAVO"
    eyes("frames", "smoke", "--at", "4.5", env=env)
    eyes("crop", "smoke", "4.5", "--box", "0.2,0.3,0.6,0.4", env=env)
    eyes("dna", "smoke", env=env)
    eyes("report", "smoke", env=env)
    assert (vdir / "report.html").exists() or list(vdir.glob("*.html"))
    print(f"OK: 3 shots, text engine {ocr.get('engine')}")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
