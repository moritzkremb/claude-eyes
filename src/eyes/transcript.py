"""Transcript track: platform captions first, then local whisper.cpp. Nothing is uploaded."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .common import HOME, log, need, read_json, run

MODEL_DIRS = [HOME / "models", Path.home() / ".cache" / "whisper.cpp", Path.home() / ".cache" / "whisper",
              Path.home() / ".cache" / "hyperframes" / "whisper" / "models",
              Path("/opt/homebrew/share/whisper-cpp"), Path("/usr/local/share/whisper-cpp")]
MODEL_PREFERENCE = ["large-v3-turbo", "large-v3", "medium", "small", "base", "tiny"]
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"


def find_model() -> Path | None:
    override = os.environ.get("EYES_WHISPER_MODEL")
    if override:
        path = Path(override).expanduser()
        return path if path.is_file() else None
    found = [p for d in MODEL_DIRS if d.is_dir() for p in d.glob("ggml-*.bin") if p.stat().st_size > 10_000_000]
    def rank(p: Path) -> int:
        name = p.stem.removeprefix("ggml-")
        for i, key in enumerate(MODEL_PREFERENCE):
            if name.startswith(key):
                return i
        return len(MODEL_PREFERENCE)
    return min(found, key=rank) if found else None


def whisper_binary() -> str | None:
    return shutil.which("whisper-cli") or shutil.which("whisper-cpp")


def _seconds(stamp: str) -> float:
    parts = stamp.replace(",", ".").split(":")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def parse_vtt(path: str) -> list[dict]:
    """Collapse YouTube's rolling auto-caption cues into plain timed lines."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    segments, last_line = [], None
    for block in re.split(r"\n\s*\n", text):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        timing = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if timing is None:
            continue
        start_s, _, rest = lines[timing].partition("-->")
        start, end = _seconds(start_s.strip()), _seconds(rest.strip().split()[0])
        for raw in lines[timing + 1:]:
            clean = re.sub(r"<[^>]+>", "", raw).replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<").strip()
            if not clean or clean == last_line:
                continue
            last_line = clean
            segments.append({"start": round(start, 2), "end": round(end, 2), "text": clean})
    for a, b in zip(segments, segments[1:]):
        if a["end"] > b["start"]:
            a["end"] = max(a["start"], b["start"])
    return segments


def _whisper(media: str, vdir: Path, lang: str | None, glossary: str | None) -> tuple[list[dict], str]:
    binary = whisper_binary()
    model = find_model()
    if not binary:
        raise SystemExit("whisper-cli not found (brew install whisper-cpp)")
    if not model:
        raise SystemExit("no whisper.cpp model found; run: eyes setup --download-model small.en")
    ffmpeg = need("ffmpeg", "Install ffmpeg (brew install ffmpeg).")
    wav = vdir / "audio16k.wav"
    run([ffmpeg, "-y", "-v", "error", "-i", media, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
    out = vdir / "whisper"
    cmd = [binary, "-m", model, "-f", wav, "-oj", "-of", out, "-np", "-t", str(min(8, os.cpu_count() or 4))]
    if not model.stem.endswith(".en"):
        cmd += ["-l", lang if lang else "auto"]
    if glossary:
        cmd += ["--prompt", glossary]
    log(f"transcribing locally with {model.name}…")
    try:
        run(cmd)
    finally:
        wav.unlink(missing_ok=True)
    data = read_json(out.with_suffix(".json"), {}) or {}
    segments = []
    for item in data.get("transcription", []):
        text = (item.get("text") or "").strip()
        offsets = item.get("offsets") or {}
        if text and not re.fullmatch(r"\[.*\]|\(.*\)", text):
            segments.append({"start": round(offsets.get("from", 0) / 1000, 2),
                             "end": round(offsets.get("to", 0) / 1000, 2), "text": text})
    return segments, f"whisper.cpp ({model.stem.removeprefix('ggml-')})"


def build(media: str, vdir: Path, src: dict, meta: dict, *, lang: str | None = None, glossary: str | None = None) -> dict:
    segments, source, note = [], None, None
    if src.get("captions"):
        try:
            segments = parse_vtt(src["captions"])
            source = f"{src.get('caption_kind', 'platform')} captions"
        except (OSError, ValueError) as exc:
            note = f"caption parse failed: {exc}"
    if not segments and meta.get("has_audio"):
        try:
            segments, source = _whisper(media, vdir, lang, glossary)
        except SystemExit as exc:
            note = f"no transcript: {exc}"
    elif not meta.get("has_audio"):
        note = "no audio stream"
    words = sum(len(s["text"].split()) for s in segments)
    spoken = sum(max(0.0, s["end"] - s["start"]) for s in segments)
    duration = meta.get("duration") or 0
    return {
        "source": source, "note": note, "segments": segments, "words": words,
        "words_per_minute": round(words / (spoken / 60), 1) if spoken > 5 else None,
        "speech_coverage": round(min(1.0, spoken / duration), 3) if duration else None,
    }
