# Eyes

Coding agents like Claude can't take video as input. Eyes turns a video into evidence an agent can read, then lets it
navigate: skim contact sheets, search what was said or shown, zoom into exact frames, and measure the editing style.
Everything runs on your machine. Nothing is uploaded.

## Install

```bash
uv tool install git+https://github.com/moritzkremb/eyes   # or: pipx install git+https://github.com/moritzkremb/eyes
brew install ffmpeg
eyes setup
```

Optional: `yt-dlp` for URLs, `whisper-cpp` plus `eyes setup --download-model small.en` for videos without captions,
and Apple Vision (macOS, automatic) or `tesseract` for on-screen text.

## Use it with an agent

Copy `skills/eyes/` into your agent's skills folder (for Claude Code: `~/.claude/skills/eyes/`). The skill teaches
the agent the method: index once, read the sheets, search before scrubbing, zoom only where it matters, and answer
with timestamps.

## Commands

```text
eyes index SRC          build the index for a URL or file (cuts, frames, sheets, transcript, on-screen text, audio, color)
eyes overview REF       reprint the index summary
eyes search QUERY       words said or shown, across one video (--in REF) or the whole library
eyes frames REF         frames at timestamps (--at) or across a range (--range, --fps)
eyes burst REF T        dense frames around one moment
eyes crop REF T --box   high-resolution crop of one region (fractions x,y,w,h)
eyes dna REF            measured editing style (pacing, captions, audio, color)
eyes note REF KEY TEXT  add a style note from viewing the sheets
eyes compare REF CAND   how closely an edit matches a reference
eyes report REF         single-file HTML report (--vs CAND for side by side)
eyes library            list indexed videos
eyes setup              check dependencies
```

The cache lives in `~/.cache/eyes/` (override with `EYES_HOME`). Source files are never copied or modified.
