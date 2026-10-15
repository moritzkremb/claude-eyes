"""Transcript track.

Default order: captions the creator uploaded, then local whisper.cpp, then the platform's automatic captions.
ElevenLabs Scribe is opt-in (--transcriber elevenlabs) because it uploads the audio.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .common import HOME, env_key, install_hint, log, need, read_json, run

TRANSCRIBERS = ("auto", "captions", "whisper", "elevenlabs")
SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"
SCRIBE_MODEL = "scribe_v2"
MODEL_DIRS = [HOME / "models", Path.home() / ".cache" / "whisper.cpp", Path.home() / ".cache" / "whisper",
              Path.home() / ".cache" / "hyperframes" / "whisper" / "models",
              Path("/opt/homebrew/share/whisper-cpp"), Path("/usr/local/share/whisper-cpp"),
              Path("/usr/share/whisper-cpp")]
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


def whisper_ready() -> bool:
    return bool(whisper_binary() and find_model())


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


DTW_LAG = 0.1  # DTW token times trail the spoken word onset by about 100 ms


def _dtw_preset(model: Path) -> str | None:
    name = model.stem.removeprefix("ggml-")
    name = re.sub(r"-q\d.*$", "", name).replace("-", ".")
    presets = {"tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en",
               "large.v1", "large.v2", "large.v3", "large.v3.turbo"}
    return name if name in presets else None


def whisper_words(data: dict) -> list[dict]:
    """Word timings from whisper.cpp's full JSON: tokens that start with a space begin a new word."""
    words: list[dict] = []
    for seg in data.get("transcription", []):
        for tok in seg.get("tokens", []):
            text = tok.get("text") or ""
            if text.startswith("[_") or not text.strip():
                continue
            off = tok.get("offsets") or {}
            start = tok["t_dtw"] / 100 - DTW_LAG if tok.get("t_dtw", -1) >= 0 else off.get("from", 0) / 1000
            if text.startswith(" ") or not words:
                words.append({"start": round(max(0.0, start), 2), "end": round(off.get("to", 0) / 1000, 2), "text": text.strip()})
            else:
                words[-1]["text"] += text
                words[-1]["end"] = round(off.get("to", 0) / 1000, 2)
    for i, w in enumerate(words):
        nxt = words[i + 1]["start"] if i + 1 < len(words) else w["start"] + 1
        w["end"] = round(min(max(w["end"], w["start"] + 0.1), max(nxt, w["start"])), 2)
    return [w for w in words if not re.fullmatch(r"\[.*\]|\(.*\)", w["text"])]


def _whisper(media: str, vdir: Path, lang: str | None, glossary: str | None) -> tuple[list[dict], list[dict], str]:
    binary = whisper_binary()
    model = find_model()
    if not binary:
        raise SystemExit(f"whisper-cli not found ({install_hint('whisper-cpp')})")
    if not model:
        raise SystemExit("no whisper.cpp model found; run: eyes setup --download-model small.en")
    ffmpeg = need("ffmpeg", f"Install ffmpeg ({install_hint('ffmpeg')}).")
    wav = vdir / "audio16k.wav"
    run([ffmpeg, "-y", "-v", "error", "-i", media, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
    out = vdir / "whisper"
    cmd = [binary, "-m", model, "-f", wav, "-ojf", "-of", out, "-np", "-t", str(min(8, os.cpu_count() or 4))]
    if not model.stem.endswith(".en"):
        cmd += ["-l", lang if lang else "auto"]
    if glossary:
        cmd += ["--prompt", glossary]
    preset = _dtw_preset(model)
    log(f"transcribing locally with {model.name}…")
    try:
        # DTW gives accurate word timings but needs flash attention off; older builds may lack it.
        if not preset or run([*cmd, "--dtw", preset, "-nfa"], check=False).returncode != 0:
            run(cmd)
    finally:
        wav.unlink(missing_ok=True)
    data = read_json(out.with_suffix(".json"), {}) or {}
    out.with_suffix(".json").unlink(missing_ok=True)
    segments = []
    for item in data.get("transcription", []):
        text = (item.get("text") or "").strip()
        offsets = item.get("offsets") or {}
        if text and not re.fullmatch(r"\[.*\]|\(.*\)", text):
            segments.append({"start": round(offsets.get("from", 0) / 1000, 2),
                             "end": round(offsets.get("to", 0) / 1000, 2), "text": text})
    return segments, whisper_words(data), f"whisper.cpp ({model.stem.removeprefix('ggml-')})"


def _multipart(fields: dict, file_field: str, file_path: Path, mime: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        for v in value if isinstance(value, list) else [value]:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
                 f"Content-Type: {mime}\r\n\r\n".encode() + file_path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def scribe_segments(words: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Group Scribe's word timings into caption-sized lines; sound events are kept apart."""
    segments, events, cur = [], [], None
    timed = [{"start": round(w["start"], 2), "end": round(w["end"], 2), "text": w["text"].strip(),
              **({"speaker": w["speaker_id"]} if w.get("speaker_id") else {})}
             for w in words if w.get("type") == "word" and (w.get("text") or "").strip()]
    def close():
        nonlocal cur
        if cur and cur["text"].strip():
            cur["text"] = re.sub(r"\s+", " ", cur["text"]).strip()
            segments.append(cur)
        cur = None
    for w in words:
        kind, text = w.get("type"), w.get("text") or ""
        if kind == "audio_event":
            events.append({"start": round(w["start"], 2), "end": round(w["end"], 2), "text": text.strip("()[] ")})
            continue
        if kind == "spacing":
            if cur:
                cur["text"] += text
            continue
        speaker = w.get("speaker_id")
        if cur and (speaker != cur.get("speaker") or w["start"] - cur["end"] > 0.7 or cur["_n"] >= 18):
            close()
        if cur is None:
            cur = {"start": round(w["start"], 2), "end": round(w["end"], 2), "text": "", "speaker": speaker, "_n": 0}
        cur["text"] += text
        cur["end"] = round(w["end"], 2)
        cur["_n"] += 1
        if re.search(r"[.?!]$", text) and cur["_n"] >= 4:
            close()
    close()
    for s in segments:
        s.pop("_n")
    return segments, events, timed


def _elevenlabs(media: str, vdir: Path, lang: str | None, glossary: str | None) -> tuple[list[dict], list[dict], list[dict], str]:
    key = env_key("ELEVENLABS_API_KEY")
    if not key:
        raise SystemExit("ELEVENLABS_API_KEY is not set (environment or ./.env)")
    ffmpeg = need("ffmpeg", f"Install ffmpeg ({install_hint('ffmpeg')}).")
    audio = vdir / "audio-upload.mp3"
    run([ffmpeg, "-y", "-v", "error", "-i", media, "-vn", "-ac", "1", "-b:a", "64k", audio])
    fields: dict = {"model_id": SCRIBE_MODEL, "diarize": "true", "tag_audio_events": "true",
                    "timestamps_granularity": "word"}
    if lang:
        fields["language_code"] = lang
    if glossary:
        fields["keyterms"] = [t.strip() for t in glossary.split(",") if t.strip()]
    body, ctype = _multipart(fields, "file", audio, "audio/mpeg")
    request = urllib.request.Request(SCRIBE_URL, data=body, method="POST", headers={
        "xi-api-key": key, "Content-Type": ctype, "User-Agent": "claude-eyes/0.2"})
    log(f"uploading audio to ElevenLabs Scribe ({audio.stat().st_size / 1e6:.1f} MB)…")
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"ElevenLabs failed ({exc.code}): {exc.read().decode('utf-8', 'replace')[:300]}") from None
    finally:
        audio.unlink(missing_ok=True)
    segments, events, words = scribe_segments(data.get("words") or [])
    return segments, events, words, f"elevenlabs ({SCRIBE_MODEL})"


def build(media: str, vdir: Path, src: dict, meta: dict, *, lang: str | None = None, glossary: str | None = None,
          transcriber: str = "auto") -> dict:
    if transcriber not in TRANSCRIBERS:
        raise SystemExit(f"Unknown transcriber {transcriber!r}; use one of {', '.join(TRANSCRIBERS)}")
    segments, events, timings, source, note = [], [], [], None, None
    def captions() -> tuple[list[dict], str | None]:
        try:
            return parse_vtt(src["captions"]), f"{src.get('caption_kind', 'platform')} captions"
        except (OSError, ValueError) as exc:
            log(f"caption parse failed: {exc}")
            return [], None
    has_captions = bool(src.get("captions"))
    manual = has_captions and src.get("caption_kind") == "manual"
    if not meta.get("has_audio"):
        note = "no audio stream"
    elif transcriber == "elevenlabs":
        segments, events, timings, source = _elevenlabs(media, vdir, lang, glossary)
    else:
        # Creator-uploaded captions are the most accurate; automatic platform captions lose to local whisper.
        use_captions = has_captions and (transcriber == "captions" or (transcriber == "auto" and (manual or not whisper_ready())))
        if use_captions:
            segments, source = captions()
        if not segments:
            try:
                segments, timings, source = _whisper(media, vdir, lang, glossary)
            except SystemExit as exc:
                if has_captions and not use_captions:
                    segments, source = captions()
                note = None if segments else f"no transcript: {exc}"
    words = sum(len(s["text"].split()) for s in segments)
    spoken = sum(max(0.0, s["end"] - s["start"]) for s in segments)
    duration = meta.get("duration") or 0
    speakers = sorted({s["speaker"] for s in segments if s.get("speaker")})
    return {
        "source": source, "note": note, "segments": segments, "words": words,
        "words_per_minute": round(words / (spoken / 60), 1) if spoken > 5 else None,
        "speech_coverage": round(min(1.0, spoken / duration), 3) if duration else None,
        **({"speakers": speakers, "events": events} if source and source.startswith("elevenlabs") else {}),
        "word_timings": timings,
    }
