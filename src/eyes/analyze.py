"""Visual and audio tracks: shots, sampled frames, contact sheets, on-screen text, audio map, palette."""
from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .common import HOME, SCRIPT_DIR, ffmpeg_input_args, fmt, log, need, run

FFMPEG_HINT = "Install ffmpeg (brew install ffmpeg)."


def _ffmpeg() -> str:
    return need("ffmpeg", FFMPEG_HINT)


# ---------------------------------------------------------------- shots

def detect_shots(media: str, duration: float, fps: float = 30.0, threshold: float = 0.3,
                 soft: float = 0.06, spike: float = 4.0, min_len: float = 0.25) -> list[dict]:
    """A cut is a frame-difference score above `threshold`, or a local spike: above `soft` and
    `spike` times the median of its neighbours. Spikes catch jump cuts in talking heads, which a
    single global threshold misses."""
    vf = "scale=256:-2,select='gte(scene,0)',metadata=print:key=lavfi.scene_score"
    base = [_ffmpeg(), "-hide_banner", "-nostats"]
    tail = ["-i", media, "-an", "-sn", "-vf", vf, "-f", "null", "-"]
    result = run([*base, *ffmpeg_input_args(), *tail], check=False)
    if result.returncode != 0:
        result = run([*base, *tail])
    times, scores, current = [], [], None
    for line in result.stderr.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            current = float(m.group(1))
            continue
        m = re.search(r"lavfi\.scene_score=([0-9.]+)", line)
        if m and current is not None:
            times.append(current)
            scores.append(float(m.group(1)))
    w = max(4, round((fps or 30) * 0.27))
    found = []
    for i, score in enumerate(scores):
        if score < soft:
            continue
        neighbours = scores[max(0, i - w):i] + scores[i + 1:i + w + 1]
        if not neighbours:
            continue
        if score >= threshold or (score >= max(neighbours) and score >= spike * max(sorted(neighbours)[len(neighbours) // 2], 0.004)):
            found.append(times[i])
    cuts: list[float] = []
    for t in found:
        if t < min_len or (duration and t > duration - min_len):
            continue
        if cuts and t - cuts[-1] < min_len:
            continue
        cuts.append(round(t, 3))
    bounds = [0.0, *cuts, round(duration, 3)]
    return [{"i": i, "start": a, "end": b, "len": round(b - a, 3)} for i, (a, b) in enumerate(zip(bounds, bounds[1:]))]


# ---------------------------------------------------------------- frames

def sample_rate(duration: float) -> float:
    return max(0.5, min(4.0, 900 / max(duration, 1.0)))


def frame_width(meta: dict) -> int:
    return 406 if meta.get("orientation") == "vertical" else 640


def sample_frames(media: str, out_dir: Path, rate: float, width: int) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.jpg"):
        old.unlink()
    vf = f"fps={rate:.6g},scale={width}:-2"
    base = [_ffmpeg(), "-hide_banner", "-nostats", "-v", "error"]
    tail = ["-i", media, "-an", "-sn", "-vf", vf, "-q:v", "4", str(out_dir / "f_%05d.jpg")]
    if run([*base, *ffmpeg_input_args(), *tail], check=False).returncode != 0:
        run([*base, *tail])
    files = sorted(out_dir.glob("f_*.jpg"))
    return [{"t": round(i / rate, 3), "path": str(p)} for i, p in enumerate(files)]


def extract_frame(media: str, t: float, out: Path, width: int | None = None, crop: str | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    filters = [f for f in (crop, f"scale={width}:-2" if width else None) if f]
    cmd = [_ffmpeg(), "-hide_banner", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", media, "-frames:v", "1"]
    if filters:
        cmd += ["-vf", ",".join(filters)]
    run([*cmd, "-q:v", "2", str(out)])
    if not out.exists():
        raise SystemExit(f"No frame at {fmt(t)} (past the end?)")
    return out


def shot_keyframes(media: str, shots: list[dict], frames: list[dict], rate: float, width: int, out_dir: Path) -> None:
    extra = 0
    for shot in shots:
        mid = (shot["start"] + shot["end"]) / 2
        k = int(round(mid * rate))
        if 0 <= k < len(frames) and shot["start"] <= frames[k]["t"] < shot["end"]:
            shot["frame"], shot["t"] = frames[k]["path"], frames[k]["t"]
        elif extra < 400:
            path = extract_frame(media, mid, out_dir / f"shot_{shot['i']:04d}.jpg", width)
            shot["frame"], shot["t"] = str(path), round(mid, 3)
            extra += 1
        elif frames:
            k = min(max(k, 0), len(frames) - 1)
            shot["frame"], shot["t"] = frames[k]["path"], frames[k]["t"]


def group_scenes(shots: list[dict], threshold: float = 10.0) -> int:
    """Label consecutive shots whose keyframes look nearly the same (animation beats, punch-ins)
    with one scene number. Returns the scene count."""
    from PIL import Image
    prev, scene = None, 0
    for shot in shots:
        thumb = None
        if shot.get("frame"):
            with Image.open(shot["frame"]) as img:
                thumb = list(img.convert("RGB").resize((16, 16)).getdata())
        if prev is not None and thumb is not None:
            diff = sum(abs(a - b) for pa, pb in zip(prev, thumb) for a, b in zip(pa, pb)) / (16 * 16 * 3)
            if diff >= threshold:
                scene += 1
            shot["diff"] = round(diff, 1)
        shot["scene"] = scene
        prev = thumb if thumb is not None else prev
    return scene + 1 if shots else 0


# ---------------------------------------------------------------- contact sheets

def _font(size: int):
    from PIL import ImageFont
    for name in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
                 "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_sheet(items: list[tuple[str, str]], out: Path, vertical: bool) -> Path:
    from PIL import Image, ImageDraw
    cols, tile_w, gap = (6, 250, 6) if vertical else (4, 380, 6)
    with Image.open(items[0][0]) as first:
        tile_h = round(tile_w * first.height / first.width)
    rows = math.ceil(len(items) / cols)
    sheet = Image.new("RGB", (cols * tile_w + (cols + 1) * gap, rows * tile_h + (rows + 1) * gap), (16, 16, 16))
    draw = ImageDraw.Draw(sheet)
    font = _font(20)
    for idx, (path, label) in enumerate(items):
        x = gap + (idx % cols) * (tile_w + gap)
        y = gap + (idx // cols) * (tile_h + gap)
        with Image.open(path) as img:
            sheet.paste(img.convert("RGB").resize((tile_w, tile_h)), (x, y))
        box = draw.textbbox((0, 0), label, font=font)
        draw.rectangle([x, y, x + box[2] - box[0] + 10, y + box[3] - box[1] + 10], fill=(0, 0, 0))
        draw.text((x + 5 - box[0], y + 5 - box[1]), label, fill=(255, 221, 0), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=82)
    return out


def per_sheet(vertical: bool) -> int:
    return 18 if vertical else 16


def build_sheets(frames: list[dict], shots: list[dict], duration: float, vertical: bool, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()
    size = per_sheet(vertical)
    sheets = {"overview": [], "shots": []}
    if frames:
        n = min(len(frames), max(16, min(96, round(duration / 1.5))))
        picks = [frames[round(i * (len(frames) - 1) / max(1, n - 1))] for i in range(n)]
        for s in range(0, len(picks), size):
            chunk = picks[s:s + size]
            path = make_sheet([(f["path"], fmt(f["t"])) for f in chunk], out_dir / f"overview_{s // size + 1:02d}.jpg", vertical)
            sheets["overview"].append({"path": str(path), "start": chunk[0]["t"], "end": chunk[-1]["t"]})
    with_frames = [s for s in shots if s.get("frame")]
    for s in range(0, len(with_frames), size):
        chunk = with_frames[s:s + size]
        items = [(c["frame"], f"#{c['i'] + 1} {fmt(c['start'])} {c['len']:.1f}s"
                  + (f" S{c['scene'] + 1}" if "scene" in c else "")) for c in chunk]
        path = make_sheet(items, out_dir / f"shots_{s // size + 1:02d}.jpg", vertical)
        sheets["shots"].append({"path": str(path), "start": chunk[0]["start"], "end": chunk[-1]["end"],
                                "first_shot": chunk[0]["i"] + 1, "last_shot": chunk[-1]["i"] + 1})
    return sheets


# ---------------------------------------------------------------- on-screen text

def _ocr_engine() -> list[str] | None:
    if sys.platform == "darwin" and shutil.which("swift"):
        source = SCRIPT_DIR / "ocr.swift"
        digest = hashlib.sha1(source.read_bytes()).hexdigest()[:10]
        binary = HOME / "bin" / f"eyes-ocr-{digest}"
        if not binary.exists() and shutil.which("swiftc"):
            binary.parent.mkdir(parents=True, exist_ok=True)
            log("compiling the Vision text recognizer (one time)…")
            # A fresh Command Line Tools SDK can be newer than its compiler; older SDKs still build.
            sdks = sorted(Path("/Library/Developer/CommandLineTools/SDKs").glob("MacOSX[0-9]*.sdk"),
                          key=lambda p: [int(x) for x in re.findall(r"\d+", p.name)], reverse=True)
            for extra in [[], *(["-sdk", str(s)] for s in sdks)]:
                if subprocess.run(["swiftc", "-O", *extra, str(source), "-o", str(binary)], capture_output=True).returncode == 0:
                    break
                binary.unlink(missing_ok=True)
        return [str(binary)] if binary.exists() else None
    if shutil.which("tesseract"):
        return ["tesseract"]
    return None


def _tesseract(paths: list[str]) -> list[dict]:
    from PIL import Image
    results = []
    for path in paths:
        with Image.open(path) as img:
            w, h = img.size
        out = subprocess.run(["tesseract", path, "stdout", "tsv"], capture_output=True, text=True).stdout
        groups: dict = {}
        for row in out.splitlines()[1:]:
            cols = row.split("\t")
            if len(cols) < 12 or not cols[11].strip() or float(cols[10]) < 0:
                continue
            key = (cols[2], cols[3], cols[4])
            l, t, ww, hh = (int(c) for c in cols[6:10])
            g = groups.setdefault(key, {"words": [], "conf": [], "box": [l, t, l + ww, t + hh]})
            g["words"].append(cols[11])
            g["conf"].append(float(cols[10]) / 100)
            b = g["box"]
            g["box"] = [min(b[0], l), min(b[1], t), max(b[2], l + ww), max(b[3], t + hh)]
        lines = [{"text": " ".join(g["words"]), "conf": sum(g["conf"]) / len(g["conf"]),
                  "box": [g["box"][0] / w, g["box"][1] / h, (g["box"][2] - g["box"][0]) / w, (g["box"][3] - g["box"][1]) / h]}
                 for g in groups.values()]
        results.append({"path": path, "lines": lines})
    return results


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


def recognize_text(frames: list[dict], shots: list[dict], limit: int = 500, fast: bool = False) -> dict:
    engine = _ocr_engine()
    if not engine or not frames:
        return {"engine": None, "frames": [], "spans": [], "coverage": None}
    picked = frames
    if len(frames) > limit:
        keys = {s.get("frame") for s in shots}
        chosen = [f for f in frames if f["path"] in keys][:limit // 2]
        step = len(frames) / max(1, limit - len(chosen))
        chosen += [frames[int(i * step)] for i in range(limit - len(chosen))]
        picked = sorted({f["path"]: f for f in chosen}.values(), key=lambda f: f["t"])
    paths = [f["path"] for f in picked]
    log(f"reading on-screen text in {len(paths)} frames…")
    if engine[0] == "tesseract":
        raw = _tesseract(paths)
        name = "tesseract"
    else:
        cmd = engine + (["--fast"] if fast else [])
        out = subprocess.run(cmd, input="\n".join(paths), capture_output=True, text=True)
        if out.returncode != 0:
            log(f"text recognition failed: {out.stderr.strip()[:300]}")
            return {"engine": None, "frames": [], "spans": [], "coverage": None}
        raw = [json.loads(line) for line in out.stdout.splitlines() if line.strip()]
        name = "apple-vision"
    by_path = {r.get("path"): r for r in raw}
    times = [f["t"] for f in picked]
    step = (times[-1] - times[0]) / max(1, len(times) - 1) if len(times) > 1 else 1.0
    frames_out, spans, active = [], [], []
    with_text = 0
    for f in picked:
        lines = [l for l in by_path.get(f["path"], {}).get("lines", [])
                 if l.get("conf", 0) >= 0.4 and len(_norm(l.get("text", ""))) >= 2]
        frames_out.append({"t": f["t"], "lines": lines})
        with_text += bool(lines)
        touched = []
        for line in lines:
            norm = _norm(line["text"])
            cx, cy = line["box"][0] + line["box"][2] / 2, line["box"][1] + line["box"][3] / 2
            best, best_score = None, 0.0
            for span in active:
                if abs(span["_cx"] - cx) > 0.12 or abs(span["_cy"] - cy) > 0.08:
                    continue
                score = difflib.SequenceMatcher(None, span["_norm"], norm).ratio()
                if score > best_score:
                    best, best_score = span, score
            if best is not None and best_score >= 0.8 and best not in touched:
                best["end"] = f["t"] + step
                best["hits"] += 1
                best["_conf"] += line["conf"]
                touched.append(best)
            else:
                span = {"start": f["t"], "end": f["t"] + step, "text": line["text"], "box": [round(v, 4) for v in line["box"]],
                        "hits": 1, "_norm": norm, "_cx": cx, "_cy": cy, "_conf": line["conf"]}
                spans.append(span)
                touched.append(span)
        active = touched
    for span in spans:
        span["conf"] = round(span.pop("_conf") / span["hits"], 3)
        span["start"], span["end"] = round(span["start"], 2), round(span["end"], 2)
        for key in ("_norm", "_cx", "_cy"):
            span.pop(key)
    return {"engine": name, "frames": frames_out, "spans": spans,
            "coverage": round(with_text / len(picked), 3) if picked else None, "step": round(step, 3)}


# ---------------------------------------------------------------- audio

def loudness(media: str) -> dict:
    result = run([_ffmpeg(), "-hide_banner", "-nostats", "-i", media, "-vn", "-af", "ebur128=peak=true",
                  "-f", "null", "-"], check=False)
    summary = result.stderr.rsplit("Summary:", 1)[-1]
    def grab(label):
        m = re.search(rf"{label}:\s+(-?[0-9.]+|-inf)", summary)
        return None if not m or m.group(1) == "-inf" else float(m.group(1))
    return {"lufs": grab("I"), "lra": grab("LRA"), "true_peak": grab("Peak")}


def audio_map(media: str, duration: float, cuts: list[float]) -> dict:
    import numpy as np
    sr = 11025
    raw = run([_ffmpeg(), "-v", "error", "-i", media, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], text=False).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    if x.size < sr:
        return {"curve": [], "silences": [], "tempo": None}
    win = sr // 10
    n = x.size // win
    rms = np.sqrt(np.mean(x[: n * win].reshape(n, win) ** 2, axis=1))
    db = 20 * np.log10(rms + 1e-9)
    silences, run_start = [], None
    for i, value in enumerate(np.append(db, 0)):
        if value < -40 and run_start is None:
            run_start = i
        elif value >= -40 and run_start is not None:
            if i - run_start >= 5:
                silences.append([round(run_start / 10, 1), round(i / 10, 1)])
            run_start = None
    # Onset envelope from positive spectral flux, then tempo by autocorrelation.
    frame, hop = 1024, 256
    window = np.hanning(frame).astype(np.float32)
    count = 1 + (x.size - frame) // hop
    flux = np.zeros(count, dtype=np.float32)
    prev = None
    for s in range(0, count, 4096):
        idx = np.arange(s, min(count, s + 4096))[:, None] * hop + np.arange(frame)[None, :]
        mag = np.log1p(100 * np.abs(np.fft.rfft(x[idx] * window, axis=1)))
        if prev is not None:
            mag_full = np.vstack([prev[None, :], mag])
        else:
            mag_full = np.vstack([mag[:1], mag])
        flux[s:s + len(mag)] = np.maximum(np.diff(mag_full, axis=0), 0).sum(axis=1)
        prev = mag[-1]
    env_rate = sr / hop
    kernel = np.ones(int(env_rate * 0.5)) / int(env_rate * 0.5)
    env = np.maximum(flux - np.convolve(flux, kernel, mode="same"), 0)
    tempo = None
    if env.size > env_rate * 8 and env.std() > 0:
        env = env / (env.max() + 1e-9)
        spec = np.fft.rfft(env - env.mean(), 2 * env.size)
        ac = np.fft.irfft(np.abs(spec) ** 2)[: env.size]
        ac = ac / (ac[0] + 1e-9)
        lags = np.arange(int(60 * env_rate / 200), int(60 * env_rate / 60) + 1)
        bpms = 60 * env_rate / lags
        weights = np.exp(-0.5 * (np.log2(bpms / 120) / 1.0) ** 2)
        best = lags[int(np.argmax(ac[lags] * weights))]
        a, b, c = ac[best - 1], ac[best], ac[best + 1]
        offset = max(-0.5, min(0.5, 0.5 * (a - c) / (a - 2 * b + c))) if (a - 2 * b + c) else 0.0
        period = best + offset
        in_range = ac[lags]
        peakiness = float((ac[best] - np.median(in_range)) / (in_range.std() + 1e-9))
        # Beat grid: best phase, then snap each beat to the local envelope peak.
        phases = np.arange(int(period))
        sums = [env[np.arange(p, env.size, period).astype(int)].sum() for p in phases]
        beat, beats, radius = float(phases[int(np.argmax(sums))]), [], max(1, int(period * 0.15))
        while beat < env.size:
            lo, hi = max(0, int(beat) - radius), min(env.size, int(beat) + radius + 1)
            peak = lo + int(np.argmax(env[lo:hi]))
            beats.append(round((peak * hop + frame / 2) / sr, 3))
            beat = peak + period
        bpm = 60 * env_rate / period
        beat_len = 60 / bpm
        aligned = sum(1 for c in cuts if beats and min(abs(c - b) for b in beats) <= 0.08)
        tempo = {"bpm": round(float(bpm), 1), "strength": round(float(ac[best]), 3), "peakiness": round(peakiness, 2),
                 "beats": beats, "cuts_on_beat": round(aligned / len(cuts), 3) if cuts else None,
                 "cuts_on_beat_by_chance": round(min(1.0, 0.16 / beat_len), 3)}
    step = max(1, len(db) // 600)
    curve = [[round(i * 0.1, 1), round(float(db[i:i + step].max()), 1)] for i in range(0, len(db), step)]
    loud_share = float((db > -40).mean())
    return {"curve": curve, "silences": silences, "silence_share": round(1 - loud_share, 3), "tempo": tempo}


# ---------------------------------------------------------------- color

def palette(paths: list[str], k: int = 6) -> dict:
    import numpy as np
    from PIL import Image
    if not paths:
        return {}
    step = max(1, len(paths) // 200)
    pixels = []
    for path in paths[::step]:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((64, 64))
            pixels.append(np.asarray(img, dtype=np.float32).reshape(-1, 3))
    X = np.concatenate(pixels)
    rng = np.random.default_rng(0)
    if len(X) > 60000:
        X = X[rng.choice(len(X), 60000, replace=False)]
    centers = [X[rng.integers(len(X))]]
    for _ in range(1, k):
        d = np.min(((X[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        centers.append(X[rng.choice(len(X), p=d / d.sum())])
    C = np.array(centers)
    for _ in range(20):
        labels = np.argmin(((X[:, None, :] - C[None]) ** 2).sum(-1), axis=1)
        C = np.array([X[labels == j].mean(axis=0) if np.any(labels == j) else C[j] for j in range(k)])
    shares = np.bincount(labels, minlength=k) / len(labels)
    order = np.argsort(-shares)
    colors = [{"hex": "#%02x%02x%02x" % tuple(int(v) for v in C[j]), "share": round(float(shares[j]), 3)} for j in order]
    mx, mn = X.max(axis=1), X.min(axis=1)
    luma = (0.2126 * X[:, 0] + 0.7152 * X[:, 1] + 0.0722 * X[:, 2]) / 255
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    brightness = float(luma.mean())
    return {"colors": colors, "brightness": round(brightness, 3), "saturation": round(float(sat.mean()), 3),
            "contrast": round(float(luma.std()), 3), "theme": "dark" if brightness < 0.4 else "light" if brightness > 0.6 else "mid"}
