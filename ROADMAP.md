# Roadmap

Ideas for later, roughly in order of usefulness. Nothing here is promised.

## New capabilities
- **Chapters and clip export.** `eyes chapters ID` splits a video into topics with titles; `eyes clip ID 1:02-1:31`
  writes the clip (optionally snapped to word boundaries and cuts), so "find the best moments" ends with files.
- **MCP server.** `eyes mcp` exposes the same commands as MCP tools, for agents that prefer tools over a shell.
- **Long videos.** Faster indexing for 1-3 hour videos: index on demand by section, parallel text recognition,
  lighter sampling where nothing changes.
  - **Text-change-triggered sampling.** Grab extra frames when on-screen text changes, so short-lived text
    (a command in a coding tutorial) isn't missed between fixed-rate samples. Raised by @faizif5a on X.
  - **Re-index a section at higher density.** Rerun indexing (including OCR) on a time range at a chosen fps
    so search picks up what the first pass missed. Extends index on demand by section. Raised by @0xYinji.
  - A flag on `eyes index` to set the sampling rate by hand (today automatic only, via `sample_rate()` in
    `src/eyes/analyze.py`).
  - **Keyframe fast mode.** `eyes index --fast` pulls only the keyframes already stored in the video file
    instead of decoding every frame, so a 1-3 hour video can be skimmed in seconds before a full index.
    Inspired by claude-video by Brad Bonanno.
  - **Cue frames.** Grab a frame (or burst) wherever the transcript says "look here", "as you can see",
    "notice" and similar, using the existing word timestamps, so the moments the speaker points at are
    always captured. Inspired by claude-video by Brad Bonanno.
  - **Thumbnail dedup.** Shrink frames to tiny thumbnails and drop near-duplicates before building contact
    sheets, to cut tokens on talking-head and slide videos. One concrete form of lighter sampling where
    nothing changes. Inspired by claude-video by Brad Bonanno.

## Distribution
- **PyPI release** so install is `uv tool install claude-eyes` / `pipx install claude-eyes`.
- **macOS CI** once the repo is public (macOS runners are free for public repos).

## Small polish
- `eyes rm ID` and `eyes clean` to manage the cache without touching folders.
- **Dissolve and fade detection.** Soft transitions are missed: on the explainer video (`docs/eyes-explainer.mp4`)
  Eyes finds 0 of its 8 scene changes, because a blur dissolve on a dark slide changes each frame no more than the
  animations inside a scene. Needs a windowed comparison (frames ~0.5 s apart) plus a check that both sides are
  stable. The explainer's exact scene times make it a ready test case.
- More eval cases for cut detection and word timings.
