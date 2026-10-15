"""Shared helpers: cache layout, subprocess calls, time formatting, library lookup."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ.get("EYES_HOME", Path.home() / ".cache" / "eyes")).expanduser()
LIBRARY = HOME / "library.json"
SCRIPT_DIR = Path(__file__).parent.resolve()


def log(message: str) -> None:
    print(f"[eyes] {message}", file=sys.stderr, flush=True)


INSTALL = {  # macOS, Linux, Windows
    "ffmpeg": ("brew install ffmpeg", "sudo apt install ffmpeg", "winget install ffmpeg"),
    "yt-dlp": ("brew install yt-dlp", "pipx install yt-dlp", "winget install yt-dlp"),
    "whisper-cpp": ("brew install whisper-cpp", "build whisper.cpp from github.com/ggml-org/whisper.cpp",
                    "download whisper.cpp from github.com/ggml-org/whisper.cpp/releases"),
    "tesseract": ("brew install tesseract", "sudo apt install tesseract-ocr", "winget install UB-Mannheim.TesseractOCR"),
}


def install_hint(tool: str) -> str:
    mac, linux, windows = INSTALL[tool]
    return mac if sys.platform == "darwin" else windows if sys.platform == "win32" else linux


def need(binary: str, hint: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise SystemExit(f"{binary} not found. {hint}")
    return path


def env_key(name: str) -> str | None:
    """An API key from the environment, else from a .env file in the working directory."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and key.strip() == name:
                return value.strip().strip("'\"") or None
    except OSError:
        pass
    return None


def run(cmd: list, *, check: bool = True, text: bool = True, input=None) -> subprocess.CompletedProcess:
    result = subprocess.run([str(c) for c in cmd], capture_output=True, text=text, input=input,
                            **({"encoding": "utf-8", "errors": "replace"} if text else {}))
    if check and result.returncode != 0:
        err = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise SystemExit(f"{Path(str(cmd[0])).name} failed ({result.returncode}): {err.strip()[-1500:]}")
    return result


def ffmpeg_input_args() -> list[str]:
    """Hardware decode on macOS speeds up full-video passes; frames are copied back automatically."""
    return ["-hwaccel", "videotoolbox"] if sys.platform == "darwin" else []


def fmt(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    h, rest = divmod(whole, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_precise(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m}:{s:04.1f}"


def parse_time(value: str | float | None) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise SystemExit(f"Bad time {value!r}; use SS, M:SS or H:MM:SS") from None
    if len(nums) > 3 or any(n < 0 for n in nums):
        raise SystemExit(f"Bad time {value!r}; use SS, M:SS or H:MM:SS")
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def parse_range(value: str) -> tuple[float, float]:
    if "-" not in value:
        raise SystemExit(f"Bad range {value!r}; use START-END, e.g. 1:05-1:30")
    a, b = value.split("-", 1)
    start, end = parse_time(a), parse_time(b)
    if end <= start:
        raise SystemExit(f"Range end must be after start: {value}")
    return start, end


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:limit].strip("-")) or "video"


def is_url(source: str) -> bool:
    return bool(re.match(r"^https?://", source.strip(), re.I))


def file_fingerprint(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1(str(size).encode())
    with path.open("rb") as stream:
        digest.update(stream.read(1 << 20))
        if size > 2 << 20:
            stream.seek(-(1 << 20), os.SEEK_END)
            digest.update(stream.read(1 << 20))
    return digest.hexdigest()[:8]


def load_library() -> dict:
    return read_json(LIBRARY, {}) or {}


def save_library_entry(vid: str, entry: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    with open(HOME / ".library.lock", "w") as lock:
        try:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        except ImportError:
            pass
        lib = load_library()
        lib[vid] = {**lib.get(vid, {}), **entry}
        write_json(LIBRARY, lib)


def resolve(ref: str) -> Path:
    """Find an indexed video by id, id prefix, original source, or local path."""
    lib = load_library()
    if ref in lib:
        return HOME / ref
    candidate = Path(ref).expanduser()
    if candidate.exists():
        target = str(candidate.resolve())
        for vid, entry in lib.items():
            if entry.get("source") == target:
                return HOME / vid
    for vid, entry in lib.items():
        if entry.get("source") == ref or entry.get("url") == ref:
            return HOME / vid
    needle = ref.lower()
    matches = ([vid for vid in lib if vid.startswith(needle)] or [vid for vid in lib if needle in vid]
               or [vid for vid, e in lib.items() if needle in (e.get("title") or "").lower()])
    if len(matches) == 1:
        return HOME / matches[0]
    if len(matches) > 1:
        raise SystemExit(f"{ref!r} matches several videos: {', '.join(matches)}")
    raise SystemExit(f"{ref!r} is not indexed. Run: eyes index \"{ref}\"")
