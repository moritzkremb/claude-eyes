"""Editing DNA: measured style spec of a video, and a reference-vs-candidate comparison."""
from __future__ import annotations

import re
import statistics
from pathlib import Path

from .common import HOME, fmt, read_json, write_json


def _load(vdir: Path) -> dict:
    return {name: read_json(vdir / f"{name}.json", {}) or {} for name in
            ("source", "meta", "shots", "transcript", "ocr", "audio", "color", "sheets")}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _position(cy: float) -> str:
    return "top" if cy < 0.33 else "middle" if cy < 0.62 else "bottom"


def _captions(ocr: dict, transcript: dict) -> tuple[list[dict], list[dict]]:
    """Split on-screen text into captions (matches nearby speech) and other overlays."""
    segs = transcript.get("segments") or []
    captions, overlays = [], []
    for span in ocr.get("spans", []):
        tokens = _words(span["text"])
        if not tokens:
            continue
        spoken = set()
        for seg in segs:
            if seg["end"] >= span["start"] - 1.0 and seg["start"] <= span["end"] + 1.0:
                spoken.update(_words(seg["text"]))
        overlap = sum(t in spoken for t in tokens) / len(tokens)
        (captions if spoken and overlap >= 0.6 and len(tokens) <= 10 else overlays).append(span)
    if captions:
        # Real captions share one vertical band; speech-matching graphics elsewhere are overlays.
        bins: dict = {}
        for c in captions:
            bins.setdefault(round((c["box"][1] + c["box"][3] / 2) / 0.04), []).append(c)
        band = max(bins.values(), key=lambda group: sum(c["hits"] for c in group))
        center = statistics.median(c["box"][1] + c["box"][3] / 2 for c in band)
        keep = [c for c in captions if abs(c["box"][1] + c["box"][3] / 2 - center) <= 0.05]
        overlays += [c for c in captions if c not in keep]
        captions = keep
    return captions, overlays


def compute(vdir: Path) -> dict:
    d = _load(vdir)
    meta, shots = d["meta"], d["shots"].get("shots", [])
    duration = meta.get("duration") or 0.0
    lens = [s["len"] for s in shots] or [duration]
    cuts = [s["start"] for s in shots[1:]]
    window = 10.0 if duration <= 300 else max(10.0, duration / 30)
    curve = []
    t = 0.0
    while t < duration:
        n = sum(1 for c in cuts if t <= c < t + window)
        curve.append({"t": round(t, 1), "cuts_per_min": round(n * 60 / min(window, duration - t), 1)})
        t += window
    hook_end = min(15.0, duration)
    hook_cuts = sum(1 for c in cuts if c < hook_end)
    rest_cuts = len(cuts) - hook_cuts
    buckets = {"<1s": 0, "1-2s": 0, "2-4s": 0, "4-8s": 0, ">8s": 0}
    for value in lens:
        key = "<1s" if value < 1 else "1-2s" if value < 2 else "2-4s" if value < 4 else "4-8s" if value < 8 else ">8s"
        buckets[key] += 1
    scenes = len({s.get("scene", s["i"]) for s in shots}) if shots else 0
    pacing = {
        "shots": len(shots), "cuts_per_min": round(len(cuts) * 60 / duration, 1) if duration else None,
        "scenes": scenes, "scene_changes_per_min": round(max(0, scenes - 1) * 60 / duration, 1) if duration else None,
        "avg_shot": round(statistics.mean(lens), 2), "median_shot": round(statistics.median(lens), 2),
        "shortest_shot": round(min(lens), 2), "longest_shot": round(max(lens), 2),
        "shot_length_mix": {k: round(v / len(lens), 3) for k, v in buckets.items()},
        "cuts_first_3s": sum(1 for c in cuts if c < 3),
        "hook_cuts_per_min": round(hook_cuts * 60 / hook_end, 1) if hook_end else None,
        "after_hook_cuts_per_min": round(rest_cuts * 60 / (duration - hook_end), 1) if duration > hook_end else None,
        "curve": curve,
    }
    tr = d["transcript"]
    segs = tr.get("segments") or []
    speech = {
        "source": tr.get("source"), "words_per_minute": tr.get("words_per_minute"),
        "speech_coverage": tr.get("speech_coverage"),
        "opening_line": " ".join(s["text"] for s in segs if s["start"] < 6)[:300] or None,
        "first_word_at": segs[0]["start"] if segs else None,
    }
    ocr = d["ocr"]
    captions, overlays = _captions(ocr, tr)
    caption_info = {"detected": bool(captions)}
    if captions:
        cys = [c["box"][1] + c["box"][3] / 2 for c in captions]
        heights = [c["box"][3] for c in captions]
        words = [len(_words(c["text"])) for c in captions]
        letters = [ch for c in captions for ch in c["text"] if ch.isalpha()]
        caption_info.update({
            "count": len(captions), "position": _position(statistics.median(cys)),
            "center_y": round(statistics.median(cys), 3),
            "line_height": round(statistics.median(heights), 4),
            "words_per_caption": round(statistics.median(words), 1),
            "all_caps_share": round(sum(ch.isupper() for ch in letters) / len(letters), 2) if letters else None,
            "changes_per_sec": round(len(captions) / duration, 2) if duration else None,
            "examples": [c["text"] for c in captions[:8]],
        })
    long_overlays = sorted(overlays, key=lambda s: s["end"] - s["start"], reverse=True)[:12]
    text = {
        "engine": ocr.get("engine"), "on_screen_text_share": ocr.get("coverage"), "captions": caption_info,
        "overlays": [{"text": o["text"][:80], "start": o["start"], "seconds": round(o["end"] - o["start"], 1),
                      "position": _position(o["box"][1] + o["box"][3] / 2)} for o in sorted(long_overlays, key=lambda s: s["start"])],
    }
    au = d["audio"]
    tempo = au.get("tempo") or {}
    music = bool(tempo) and tempo.get("strength", 0) >= 0.2 and tempo.get("peakiness", 0) >= 4
    audio = {
        "lufs": au.get("lufs"), "true_peak": au.get("true_peak"), "loudness_range": au.get("lra"),
        "silence_share": au.get("silence_share"),
        "tempo_bpm": tempo.get("bpm") if music else None,
        "rhythmic_music_likely": music,
        "tempo_strength": tempo.get("strength"),
        "cuts_on_beat": tempo.get("cuts_on_beat") if music else None,
        "cuts_on_beat_by_chance": tempo.get("cuts_on_beat_by_chance") if music else None,
    }
    color = d["color"]
    dna = {
        "video": {"id": d["source"].get("id"), "title": d["source"].get("title"), "source": d["source"].get("source")},
        "format": {k: meta.get(k) for k in ("width", "height", "orientation", "fps", "duration")},
        "pacing": pacing, "speech": speech, "text": text, "audio": audio,
        "color": {k: color.get(k) for k in ("colors", "brightness", "saturation", "contrast", "theme")},
        "evidence": {"shot_sheets": [s["path"] for s in d["sheets"].get("shots", [])],
                     "overview_sheets": [s["path"] for s in d["sheets"].get("overview", [])]},
        "style_notes": (read_json(vdir / "dna.json", {}) or {}).get("style_notes", {}),
    }
    write_json(vdir / "dna.json", dna)
    (vdir / "dna.md").write_text(render_md(dna), encoding="utf-8")
    return dna


def _pct(v):
    return "n/a" if v is None else f"{v * 100:.0f}%"


def render_md(dna: dict) -> str:
    f, p, s, t, a, c = (dna[k] for k in ("format", "pacing", "speech", "text", "audio", "color"))
    cap = t["captions"]
    lines = [f"# Editing DNA: {dna['video'].get('title') or dna['video']['id']}", "",
             f"Source: {dna['video'].get('source')}", "",
             "## Format",
             f"- {f['width']}x{f['height']} ({f['orientation']}), {f['fps']} fps, {fmt(f['duration'])} ({f['duration']:.1f}s)", "",
             "## Pacing",
             f"- {p['shots']} shots, {p['cuts_per_min']} cuts/min; median shot {p['median_shot']}s (avg {p['avg_shot']}s, "
             f"range {p['shortest_shot']}-{p['longest_shot']}s)",
             f"- {p['scenes']} distinct scenes, {p['scene_changes_per_min']} scene changes/min (cuts between near-identical "
             f"frames, like animation beats or punch-ins, count as one scene)",
             "- Shot length mix: " + ", ".join(f"{k} {_pct(v)}" for k, v in p["shot_length_mix"].items()),
             f"- Hook: {p['cuts_first_3s']} cuts in the first 3s; {p['hook_cuts_per_min']} cuts/min in the first 15s "
             f"vs {p['after_hook_cuts_per_min']} after",
             "- Pacing curve (cuts/min per window): " + " ".join(f"{fmt(w['t'])}={w['cuts_per_min']:g}" for w in p["curve"]), "",
             "## Speech",
             f"- Transcript: {s['source'] or 'none'}; {s['words_per_minute'] or 'n/a'} words/min while talking; "
             f"speech covers {_pct(s['speech_coverage'])} of the runtime; first word at {s['first_word_at']}s",
             f"- Opening line: {s['opening_line'] or 'n/a'}", "",
             "## On-screen text",
             f"- Text visible in {_pct(t['on_screen_text_share'])} of sampled frames ({t['engine'] or 'no text engine'})"]
    if cap.get("detected"):
        lines += [f"- Captions: {cap['position']} (center y {cap['center_y']}), line height {cap['line_height'] * 100:.1f}% of frame, "
                  f"{cap['words_per_caption']:g} words each, {cap['changes_per_sec']} changes/sec, ALL CAPS share {_pct(cap['all_caps_share'])}",
                  "- Caption examples: " + " | ".join(cap["examples"])]
    else:
        lines.append("- Captions: none detected")
    if t["overlays"]:
        lines.append("- Longest-running text overlays:")
        lines += [f"  - {fmt(o['start'])} for {o['seconds']}s, {o['position']}: {o['text']}" for o in t["overlays"]]
    lines += ["", "## Audio",
              f"- Loudness {a['lufs']} LUFS integrated, true peak {a['true_peak']} dBFS, range {a['loudness_range']} LU; "
              f"near-silent {_pct(a['silence_share'])} of the time"]
    if a["rhythmic_music_likely"]:
        lines.append(f"- Rhythmic music around {a['tempo_bpm']} BPM; {_pct(a['cuts_on_beat'])} of cuts land on a beat "
                     f"(chance would be about {_pct(a['cuts_on_beat_by_chance'])})")
    else:
        lines.append("- No strong steady beat detected (speech-led or ambient audio)")
    lines += ["", "## Color",
              f"- Theme {c.get('theme')}; brightness {c.get('brightness')}, saturation {c.get('saturation')}, contrast {c.get('contrast')}",
              "- Palette: " + ", ".join(f"{x['hex']} ({_pct(x['share'])})" for x in c.get("colors") or []), "",
              "## Style notes (from viewing the shot sheets)"]
    notes = dna.get("style_notes") or {}
    if notes:
        lines += [f"- **{k}:** {v}" for k, v in notes.items()]
    else:
        lines.append("_Not filled yet. View the shot sheets and add notes with `eyes note`._")
    lines += ["", "## Evidence", *[f"- {p}" for p in dna["evidence"]["shot_sheets"]]]
    return "\n".join(lines) + "\n"


METRICS = [
    ("Duration (s)", ("format", "duration"), "rel"),
    ("Orientation", ("format", "orientation"), "eq"),
    ("Cuts per minute", ("pacing", "cuts_per_min"), "rel"),
    ("Scene changes per minute", ("pacing", "scene_changes_per_min"), "rel"),
    ("Median shot (s)", ("pacing", "median_shot"), "rel"),
    ("Shots under 1s", ("pacing", "shot_length_mix", "<1s"), "abs"),
    ("Cuts in first 3s", ("pacing", "cuts_first_3s"), "count"),
    ("Hook cuts/min (first 15s)", ("pacing", "hook_cuts_per_min"), "rel"),
    ("Words per minute", ("speech", "words_per_minute"), "rel"),
    ("Speech coverage", ("speech", "speech_coverage"), "abs"),
    ("First word at (s)", ("speech", "first_word_at"), "count"),
    ("On-screen text share", ("text", "on_screen_text_share"), "abs"),
    ("Captions", ("text", "captions", "detected"), "eq"),
    ("Caption position", ("text", "captions", "position"), "eq"),
    ("Caption line height", ("text", "captions", "line_height"), "rel"),
    ("Words per caption", ("text", "captions", "words_per_caption"), "rel"),
    ("Caption ALL CAPS share", ("text", "captions", "all_caps_share"), "abs"),
    ("Loudness (LUFS)", ("audio", "lufs"), "db"),
    ("Tempo (BPM)", ("audio", "tempo_bpm"), "rel"),
    ("Cuts on beat", ("audio", "cuts_on_beat"), "abs"),
    ("Brightness", ("color", "brightness"), "abs"),
    ("Saturation", ("color", "saturation"), "abs"),
]


def _get(d: dict, path: tuple):
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def _verdict(ref, cand, kind: str) -> str:
    if ref is None or cand is None:
        return "n/a"
    if kind == "eq":
        return "match" if ref == cand else "different"
    if kind == "db":
        diff = abs(cand - ref)
        return "match" if diff <= 1.5 else "close" if diff <= 3 else "off"
    if kind == "abs":
        diff = abs(cand - ref)
        return "match" if diff <= 0.08 else "close" if diff <= 0.18 else "off"
    if kind == "count":
        diff = abs(cand - ref)
        return "match" if diff <= 1 else "close" if diff <= 2 else "off"
    if ref == 0:
        return "match" if cand == 0 else "off"
    ratio = abs(cand - ref) / abs(ref)
    return "match" if ratio <= 0.2 else "close" if ratio <= 0.4 else "off"


def _palette_distance(a: list, b: list) -> float | None:
    if not a or not b:
        return None
    def rgb(h):
        return [int(h[i:i + 2], 16) for i in (1, 3, 5)]
    def nearest(x, pool):
        return min(sum((p - q) ** 2 for p, q in zip(rgb(x["hex"]), rgb(y["hex"]))) ** 0.5 for y in pool)
    return round(sum(x["share"] * nearest(x, b) for x in a) / max(1e-9, sum(x["share"] for x in a)), 1)


def compare(ref_dir: Path, cand_dir: Path) -> tuple[dict, Path]:
    ref, cand = compute(ref_dir), compute(cand_dir)
    rows = []
    for label, path, kind in METRICS:
        r, c = _get(ref, path), _get(cand, path)
        rows.append({"metric": label, "reference": r, "candidate": c, "verdict": _verdict(r, c, kind)})
    dist = _palette_distance((ref.get("color") or {}).get("colors"), (cand.get("color") or {}).get("colors"))
    rows.append({"metric": "Palette distance (0 = same)", "reference": 0, "candidate": dist,
                 "verdict": "n/a" if dist is None else "match" if dist < 25 else "close" if dist < 50 else "off"})
    counts = {v: sum(r["verdict"] == v for r in rows) for v in ("match", "close", "off", "different")}
    result = {"reference": ref["video"], "candidate": cand["video"], "rows": rows, "summary": counts}
    out = HOME / "compare" / f"{ref['video']['id']}__vs__{cand['video']['id']}.md"
    write_json(out.with_suffix(".json"), result)
    def show(v):
        return "n/a" if v is None else f"{v:g}" if isinstance(v, float) else str(v)
    md = [f"# DNA match: {cand['video'].get('title')} vs reference {ref['video'].get('title')}", "",
          f"{counts['match']} match, {counts['close']} close, {counts['off'] + counts['different']} off", "",
          "| Metric | Reference | Candidate | Verdict |", "|---|---|---|---|"]
    md += [f"| {r['metric']} | {show(r['reference'])} | {show(r['candidate'])} | {r['verdict']} |" for r in rows]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    return result, out
