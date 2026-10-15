"""Source ingest: download URLs with yt-dlp, fingerprint local files, probe streams."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

from .common import HOME, file_fingerprint, install_hint, is_url, log, need, read_json, run, slug, write_json

YTDLP_HINT = f"Install yt-dlp ({install_hint('yt-dlp')}) to index URLs, or pass a local file."


def ytdlp_cmd() -> list[str]:
    """yt-dlp on PATH (often newer), else the copy installed with eyes."""
    path = shutil.which("yt-dlp")
    if path:
        return [path]
    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    raise SystemExit(f"yt-dlp not found. {YTDLP_HINT}")


def _pick_caption(info: dict, lang: str | None) -> tuple[str, str] | None:
    """Captions in the spoken language: manual first, then auto. YouTube lists '-orig' tracks for
    many dubbed languages, so the video's declared language decides which one is original."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    spoken = (info.get("language") or "").split("-")[0].lower() or None
    wanted = [l for l in dict.fromkeys([lang, spoken, "en"]) if l]
    for want in wanted:
        for key in manual:
            if key.lower() == want or key.lower().startswith(want + "-"):
                return key, "manual"
        for key in (f"{want}-orig", want):
            if key in auto:
                return key, "auto"
    return None


def ingest(source: str, *, lang: str | None = None, quality: int = 720, force: bool = False) -> tuple[str, Path, dict]:
    if is_url(source):
        return _ingest_url(source, lang=lang, quality=quality, force=force)
    return _ingest_local(source)


def _ingest_url(url: str, *, lang: str | None, quality: int, force: bool) -> tuple[str, Path, dict]:
    ytdlp = ytdlp_cmd()
    log("reading metadata with yt-dlp…")
    info = json.loads(run([*ytdlp, "-J", "--no-playlist", "--no-warnings", "--", url]).stdout)
    vid = slug(f"{info.get('extractor_key', 'web')}-{info['id']}", 60)
    vdir = HOME / vid
    vdir.mkdir(parents=True, exist_ok=True)
    src = read_json(vdir / "source.json", {}) or {}
    media = Path(src["media"]) if src.get("media") else None
    if force:
        src = {k: v for k, v in src.items() if k not in ("captions", "caption_kind")}
    if not media or not media.exists():
        log(f"downloading video (≤{quality}p)…")
        fmt = f"bv*[height<={quality}]+ba/b[height<={quality}]/bv*+ba/b"
        run([*ytdlp, "--no-playlist", "--no-warnings", "-f", fmt, "--merge-output-format", "mp4",
             "-o", str(vdir / "video.%(ext)s"), "--", url])
        found = sorted(p for p in vdir.glob("video.*") if p.suffix not in (".part", ".ytdl", ".vtt"))
        if not found:
            raise SystemExit("yt-dlp finished but no video file was written.")
        media = found[0]
    captions, caption_kind = src.get("captions"), src.get("caption_kind")
    if not captions or not Path(captions).exists():
        captions, caption_kind = None, None
        choice = _pick_caption(info, lang)
        if choice:
            key, caption_kind = choice
            log(f"fetching {caption_kind} captions ({key})…")
            for old in vdir.glob("captions*.vtt"):
                old.unlink()
            run([*ytdlp, "--skip-download", "--no-playlist", "--no-warnings",
                 "--write-subs" if caption_kind == "manual" else "--write-auto-subs",
                 "--sub-langs", key, "--sub-format", "vtt/best", "--convert-subs", "vtt",
                 "-o", str(vdir / "captions.%(ext)s"), "--", url], check=False)
            vtts = sorted(vdir.glob("captions*.vtt"))
            captions = str(vtts[0]) if vtts else None
            if not captions:
                caption_kind = None
    entry = {
        "id": vid, "kind": "url", "source": url, "url": info.get("webpage_url") or url,
        "title": info.get("title"), "uploader": info.get("uploader") or info.get("channel"),
        "upload_date": info.get("upload_date"), "description": (info.get("description") or "")[:2000],
        "media": str(media), "captions": captions, "caption_kind": caption_kind,
    }
    write_json(vdir / "source.json", entry)
    return vid, vdir, entry


def _ingest_local(path_text: str) -> tuple[str, Path, dict]:
    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")
    vid = f"{slug(path.stem)}-{file_fingerprint(path)}"
    vdir = HOME / vid
    vdir.mkdir(parents=True, exist_ok=True)
    entry = {"id": vid, "kind": "local", "source": str(path), "title": path.stem,
             "media": str(path), "captions": None, "caption_kind": None}
    write_json(vdir / "source.json", entry)
    return vid, vdir, entry


def probe(media: str) -> dict:
    ffprobe = need("ffprobe", f"Install ffmpeg ({install_hint('ffmpeg')}).")
    data = json.loads(run([ffprobe, "-v", "error", "-print_format", "json", "-show_format",
                           "-show_streams", media]).stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float((data.get("format") or {}).get("duration") or (video or {}).get("duration") or 0)
    width = int(video.get("width") or 0) if video else 0
    height = int(video.get("height") or 0) if video else 0
    rotation = 0
    for side in (video or {}).get("side_data_list", []) or []:
        if "rotation" in side:
            rotation = abs(int(side["rotation"])) % 360
    if rotation in (90, 270):
        width, height = height, width
    fps = 0.0
    if video and video.get("avg_frame_rate") and video["avg_frame_rate"] != "0/0":
        num, _, den = video["avg_frame_rate"].partition("/")
        fps = float(num) / float(den or 1)
    return {"duration": duration, "width": width, "height": height, "fps": round(fps, 3),
            "vcodec": (video or {}).get("codec_name"), "has_video": bool(video), "has_audio": bool(audio),
            "orientation": "vertical" if height > width else "square" if height == width else "horizontal"}
