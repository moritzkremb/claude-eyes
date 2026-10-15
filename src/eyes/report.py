"""Single-file HTML report: shot timeline, pacing, audio, palette, text, transcript, and DNA match."""
from __future__ import annotations

import base64
import html
import io
from pathlib import Path

from . import dna as dna_mod
from .common import HOME, fmt, read_json

CSS = """
*{box-sizing:border-box}body{margin:0;background:#0d0f12;color:#e8e6e1;font:15px/1.5 -apple-system,BlinkMacSystemFont,Inter,Segoe UI,sans-serif}
main{max-width:1280px;margin:0 auto;padding:40px 32px 80px}h1{font-size:30px;margin:0 0 4px;letter-spacing:-.02em}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:#8f949c;margin:36px 0 12px;font-weight:600}
a{color:#ffcf4a}.sub{color:#8f949c;margin-bottom:24px;word-break:break-all}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.card{background:#161a20;border:1px solid #232831;border-radius:12px;padding:14px 16px}.card b{display:block;font-size:24px;letter-spacing:-.02em}
.card span{color:#8f949c;font-size:12px;text-transform:uppercase;letter-spacing:.08em}
.timeline{display:flex;height:84px;border-radius:10px;overflow:hidden;background:#161a20;gap:1px}
.timeline div{background-size:cover;background-position:center;min-width:1px;position:relative}
.timeline div:hover{outline:2px solid #ffcf4a;z-index:2}.axis{display:flex;justify-content:space-between;color:#6b717a;font-size:12px;margin-top:4px}
.panel{background:#161a20;border:1px solid #232831;border-radius:12px;padding:16px}
.swatches{display:flex;height:56px;border-radius:10px;overflow:hidden}.swatches div{display:flex;align-items:flex-end;padding:6px;font-size:11px;color:#fff;text-shadow:0 1px 2px #000}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}.list{margin:0;padding-left:18px}.list li{margin:2px 0}
.t{color:#ffcf4a;font-variant-numeric:tabular-nums;margin-right:8px}details summary{cursor:pointer;color:#8f949c}
.transcript p{margin:4px 0}table{width:100%;border-collapse:collapse}td,th{padding:9px 10px;border-bottom:1px solid #232831;text-align:left}
th{color:#8f949c;font-weight:500;font-size:13px}.v{border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600}
.match{background:#173d2a;color:#5fe39a}.close{background:#3d3517;color:#ffcf4a}.off,.different{background:#3d1a1a;color:#ff7a7a}.na{color:#6b717a}
.label{font-size:13px;color:#8f949c;margin:14px 0 6px}.score{font-size:46px;font-weight:700;letter-spacing:-.03em}
.notes li{margin:4px 0}svg{display:block;width:100%}
"""


def _thumb(path: str, width: int = 160) -> str:
    from PIL import Image
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((width, width * 2))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=70)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except OSError:
        return ""


def _timeline(vdir: Path, duration: float) -> str:
    shots = (read_json(vdir / "shots.json", {}) or {}).get("shots", [])
    step = max(1, len(shots) // 300)
    cells = []
    for i in range(0, len(shots), step):
        group = shots[i:i + step]
        start, end = group[0]["start"], group[-1]["end"]
        img = _thumb(group[0]["frame"]) if group[0].get("frame") else ""
        cells.append(f'<div style="flex:{max(end - start, 0.01):.3f};background-image:url({img})" '
                     f'title="#{group[0]["i"] + 1} {fmt(start)} · {end - start:.1f}s"></div>')
    ticks = "".join(f"<span>{fmt(duration * k / 6)}</span>" for k in range(7))
    return f'<div class="timeline">{"".join(cells)}</div><div class="axis">{ticks}</div>'


def _pacing_svg(curve: list, duration: float, peak: float | None = None) -> str:
    if not curve:
        return ""
    peak = peak or max(1.0, max(c["cuts_per_min"] for c in curve))
    w, h, n = 1000, 120, len(curve)
    bars = "".join(f'<rect x="{i * w / n + 1:.1f}" y="{h - c["cuts_per_min"] / peak * (h - 18):.1f}" width="{w / n - 2:.1f}" '
                   f'height="{c["cuts_per_min"] / peak * (h - 18):.1f}" rx="3" fill="#ffcf4a" opacity=".85">'
                   f'<title>{fmt(c["t"])}: {c["cuts_per_min"]:g} cuts/min</title></rect>' for i, c in enumerate(curve))
    return f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" style="height:120px">{bars}' \
           f'<text x="4" y="12" fill="#6b717a" font-size="11">{peak:g} cuts/min</text></svg>'


def _audio_svg(vdir: Path, duration: float) -> str:
    audio = read_json(vdir / "audio.json", {}) or {}
    curve = audio.get("curve") or []
    if not curve or not duration:
        return "<p class='na'>No audio.</p>"
    w, h = 1000, 110
    floor = -60.0
    pts = " ".join(f"{p[0] / duration * w:.1f},{h - (max(floor, min(0, p[1])) - floor) / -floor * h:.1f}" for p in curve)
    shots = (read_json(vdir / "shots.json", {}) or {}).get("shots", [])[1:]
    cut_lines = "".join(f'<line x1="{s["start"] / duration * w:.1f}" x2="{s["start"] / duration * w:.1f}" y1="0" y2="{h}" '
                        f'stroke="#ffffff" stroke-opacity=".18"/>' for s in shots[:600])
    tempo = audio.get("tempo") or {}
    beats = ""
    if tempo and tempo.get("strength", 0) >= 0.2 and tempo.get("peakiness", 0) >= 4:
        beats = "".join(f'<circle cx="{b / duration * w:.1f}" cy="{h - 4}" r="1.6" fill="#5fe39a"/>' for b in tempo.get("beats", [])[:2000])
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" style="height:110px">{cut_lines}'
            f'<polyline points="0,{h} {pts} {w},{h}" fill="#4a9dff" fill-opacity=".25" stroke="#4a9dff" stroke-width="1.2"/>{beats}</svg>'
            f'<div class="axis"><span>loudness (blue), cuts (white lines){", beats (green dots)" if beats else ""}</span><span>{fmt(duration)}</span></div>')


def _swatches(colors: list) -> str:
    return '<div class="swatches">' + "".join(
        f'<div style="flex:{c["share"]};background:{c["hex"]}">{c["hex"]}</div>' for c in colors or []) + "</div>"


def _cards(d: dict) -> str:
    p, s, a, t = d["pacing"], d["speech"], d["audio"], d["text"]
    items = [("Duration", fmt(d["format"]["duration"])), ("Shots", p["shots"]), ("Cuts / min", p["cuts_per_min"]),
             ("Median shot", f"{p['median_shot']}s"), ("Words / min", s["words_per_minute"] or "n/a"),
             ("Text on screen", f"{t['on_screen_text_share'] * 100:.0f}%" if t["on_screen_text_share"] is not None else "n/a"),
             ("Loudness", f"{a['lufs']} LUFS" if a["lufs"] is not None else "n/a"),
             ("Tempo", f"{a['tempo_bpm']:g} BPM" if a["tempo_bpm"] else "no beat")]
    return '<div class="cards">' + "".join(f'<div class="card"><span>{k}</span><b>{html.escape(str(v))}</b></div>' for k, v in items) + "</div>"


def _text_panel(d: dict) -> str:
    cap = d["text"]["captions"]
    parts = []
    if cap.get("detected"):
        parts.append(f"<p><b>Captions</b> · {cap['position']} of frame · {cap['words_per_caption']:g} words each · "
                     f"{cap['changes_per_sec']} per second · ALL CAPS {cap['all_caps_share'] * 100 if cap['all_caps_share'] is not None else 0:.0f}%</p>")
        parts.append("<ul class='list'>" + "".join(f"<li>{html.escape(x)}</li>" for x in cap["examples"][:6]) + "</ul>")
    else:
        parts.append("<p class='na'>No captions detected.</p>")
    if d["text"]["overlays"]:
        parts.append("<div class='label'>Longest-running overlays</div><ul class='list'>" + "".join(
            f"<li><span class='t'>{fmt(o['start'])}</span>{html.escape(o['text'])} <span class='na'>({o['seconds']}s, {o['position']})</span></li>"
            for o in d["text"]["overlays"][:10]) + "</ul>")
    return "".join(parts)


def _page(title: str, body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>"


def build(vdir: Path, vs: Path | None = None) -> Path:
    d = dna_mod.compute(vdir)
    if vs is not None:
        return _build_compare(vdir, d, vs)
    duration = d["format"]["duration"]
    trn = read_json(vdir / "transcript.json", {}) or {}
    src = read_json(vdir / "source.json", {}) or {}
    notes = d.get("style_notes") or {}
    body = [f"<h1>{html.escape(d['video'].get('title') or d['video']['id'])}</h1>",
            f"<div class='sub'>{html.escape(src.get('url') or src.get('source') or '')} · {d['format']['width']}x{d['format']['height']} "
            f"{d['format']['orientation']} · transcript: {html.escape(trn.get('source') or 'none')}</div>",
            _cards(d), "<h2>Every shot</h2>", _timeline(vdir, duration),
            "<h2>Pacing</h2><div class='panel'>", _pacing_svg(d["pacing"]["curve"], duration),
            f"<div class='axis'><span>{d['pacing']['cuts_first_3s']} cuts in the first 3s · hook {d['pacing']['hook_cuts_per_min']} cuts/min vs "
            f"{d['pacing']['after_hook_cuts_per_min']} after</span></div></div>",
            "<h2>Audio</h2><div class='panel'>", _audio_svg(vdir, duration), "</div>",
            "<div class='two'><div><h2>Palette</h2>", _swatches(d["color"].get("colors")),
            f"<div class='axis'><span>{d['color'].get('theme')} theme · brightness {d['color'].get('brightness')} · saturation {d['color'].get('saturation')}</span></div></div>",
            "<div><h2>On-screen text</h2><div class='panel'>", _text_panel(d), "</div></div></div>"]
    if notes:
        body.append("<h2>Style notes</h2><div class='panel'><ul class='notes'>" + "".join(
            f"<li><b>{html.escape(k)}:</b> {html.escape(v)}</li>" for k, v in notes.items()) + "</ul></div>")
    if trn.get("segments"):
        body.append("<h2>Transcript</h2><details class='panel transcript'><summary>Show transcript</summary>" + "".join(
            f"<p><span class='t'>{fmt(s['start'])}</span>{html.escape(s['text'])}</p>" for s in trn["segments"]) + "</details>")
    out = vdir / "report.html"
    out.write_text(_page(d["video"].get("title") or "eyes report", "".join(body)), encoding="utf-8")
    return out


def _build_compare(ref_dir: Path, ref: dict, cand_dir: Path) -> Path:
    result, _ = dna_mod.compare(ref_dir, cand_dir)
    cand = read_json(cand_dir / "dna.json")
    counts = result["summary"]
    scored = [r for r in result["rows"] if r["verdict"] != "n/a"]
    score = round(100 * sum(1 if r["verdict"] == "match" else 0.5 if r["verdict"] == "close" else 0 for r in scored) / max(1, len(scored)))
    def show(v):
        return "n/a" if v is None else f"{v:g}" if isinstance(v, float) else html.escape(str(v))
    rows = "".join(f"<tr><td>{html.escape(r['metric'])}</td><td>{show(r['reference'])}</td><td>{show(r['candidate'])}</td>"
                   f"<td><span class='v {r['verdict'] if r['verdict'] != 'n/a' else 'na'}'>{r['verdict']}</span></td></tr>"
                   for r in result["rows"])
    peak = max([c["cuts_per_min"] for c in ref["pacing"]["curve"] + cand["pacing"]["curve"]] + [1])
    body = [f"<h1>DNA match: {html.escape(cand['video'].get('title') or '')}</h1>",
            f"<div class='sub'>against reference: {html.escape(ref['video'].get('title') or '')}</div>",
            f"<div class='cards'><div class='card'><span>Match score</span><b class='score'>{score}</b></div>"
            f"<div class='card'><span>Match</span><b>{counts['match']}</b></div><div class='card'><span>Close</span><b>{counts['close']}</b></div>"
            f"<div class='card'><span>Off</span><b>{counts['off'] + counts['different']}</b></div></div>",
            "<h2>Shots</h2><div class='label'>Reference</div>", _timeline(ref_dir, ref["format"]["duration"]),
            "<div class='label'>Your edit</div>", _timeline(cand_dir, cand["format"]["duration"]),
            "<h2>Pacing (cuts per minute)</h2><div class='two'><div class='panel'><div class='label'>Reference</div>",
            _pacing_svg(ref["pacing"]["curve"], ref["format"]["duration"], peak), "</div><div class='panel'><div class='label'>Your edit</div>",
            _pacing_svg(cand["pacing"]["curve"], cand["format"]["duration"], peak), "</div></div>",
            "<h2>Palette</h2><div class='two'><div><div class='label'>Reference</div>", _swatches(ref["color"].get("colors")),
            "</div><div><div class='label'>Your edit</div>", _swatches(cand["color"].get("colors")), "</div></div>",
            "<h2>Metrics</h2><div class='panel'><table><tr><th>Metric</th><th>Reference</th><th>Your edit</th><th></th></tr>", rows, "</table></div>"]
    out = HOME / "compare" / f"{ref['video']['id']}__vs__{cand['video']['id']}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_page("DNA match", "".join(body)), encoding="utf-8")
    return out
