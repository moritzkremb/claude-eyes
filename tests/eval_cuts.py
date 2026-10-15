"""Measure cut detection against videos whose real cuts are known.

Cases file (JSON list), each item one of:
  {"video": "render.mp4", "edl": "final.edl.json"}   clips[].edited_start / source_start / source_end
  {"video": "render.mp4", "cuts": [2.73, 6.5, ...]}  cut times in seconds
Add "skip": "reason" to leave a case out.

  python tests/eval_cuts.py tests/eval_cases.local.json          # score the current settings
  python tests/eval_cuts.py tests/eval_cases.local.json --grid   # search for better settings
"""
import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path

from eyes.analyze import pick_cuts, scene_scores
from eyes.common import HOME
from eyes.media import probe

TOLERANCE = 0.1


def truth_cuts(case: dict, fps: float) -> list[float]:
    if "cuts" in case:
        return case["cuts"]
    clips = json.loads(Path(case["edl"]).expanduser().read_text())["clips"]
    # A join where the source simply continues is invisible, so it is not a cut.
    return [b["edited_start"] for a, b in zip(clips, clips[1:]) if abs(b["source_start"] - a["source_end"]) >= 2 / fps]


def scores_for(video: str) -> tuple[list[float], list[float]]:
    key = hashlib.sha1(f"{video}:{Path(video).stat().st_mtime}".encode()).hexdigest()[:12]
    cache = HOME / "eval-scores" / f"{key}.json"
    if cache.exists():
        return tuple(json.loads(cache.read_text()))
    data = scene_scores(video)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data))
    return data


def match(found: list[float], truth: list[float]) -> int:
    used, hits = set(), 0
    for t in truth:
        best = min((abs(f - t), i) for i, f in enumerate(found) if i not in used) if len(used) < len(found) else None
        if best and best[0] <= TOLERANCE:
            used.add(best[1])
            hits += 1
    return hits


def evaluate(cases: list[dict], **tuning) -> dict:
    rows, tp, n_found, n_truth = [], 0, 0, 0
    for c in cases:
        found = pick_cuts(c["times"], c["scores"], c["duration"], fps=c["fps"], **tuning)
        hits = match(found, c["truth"])
        rows.append((Path(c["video"]).parent.name + "/" + Path(c["video"]).name, hits, len(c["truth"]), len(found) - hits))
        tp, n_found, n_truth = tp + hits, n_found + len(found), n_truth + len(c["truth"])
    recall = tp / n_truth if n_truth else 0
    precision = tp / n_found if n_found else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return {"rows": rows, "tp": tp, "truth": n_truth, "extra": n_found - tp, "recall": recall, "precision": precision, "f1": f1}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases")
    ap.add_argument("--grid", action="store_true")
    args = ap.parse_args()
    cases = [c for c in json.loads(Path(args.cases).read_text()) if not c.get("skip")]
    for c in cases:
        c["video"] = str(Path(c["video"]).expanduser())
        meta = probe(c["video"])
        c["fps"], c["duration"] = meta["fps"] or 30, meta["duration"]
        c["truth"] = truth_cuts(c, c["fps"])
        c["times"], c["scores"] = scores_for(c["video"])
    base = evaluate(cases)
    for name, hits, total, extra in base["rows"]:
        print(f"{name:60s} found {hits:3d}/{total:<3d} extra {extra}")
    print(f"\nTOTAL found {base['tp']}/{base['truth']} (recall {base['recall']:.0%}), extra {base['extra']} "
          f"(precision {base['precision']:.0%}), F1 {base['f1']:.3f}")
    if not args.grid:
        return
    grid = {"soft": [0.02, 0.03, 0.04, 0.06], "spike": [2.5, 3, 4, 5], "window": [0.2, 0.27, 0.4], "threshold": [0.2, 0.3, 0.4]}
    results = []
    for values in itertools.product(*grid.values()):
        tuning = dict(zip(grid, values))
        r = evaluate(cases, **tuning)
        results.append((r["f1"], r["tp"], r["extra"], tuning))
    print("\nBest settings:")
    for f1, tp, extra, tuning in sorted(results, key=lambda x: -x[0])[:10]:
        print(f"  F1 {f1:.3f}  found {tp}/{base['truth']}  extra {extra}  {tuning}")


if __name__ == "__main__":
    sys.exit(main())
