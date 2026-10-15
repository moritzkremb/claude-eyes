# Roadmap

Ideas for later, roughly in order of usefulness. Nothing here is promised.

## New capabilities
- **Chapters and clip export.** `eyes chapters ID` splits a video into topics with titles; `eyes clip ID 1:02-1:31`
  writes the clip (optionally snapped to word boundaries and cuts), so "find the best moments" ends with files.
- **MCP server.** `eyes mcp` exposes the same commands as MCP tools, for agents that prefer tools over a shell.
- **Long videos.** Faster indexing for 1-3 hour videos: index on demand by section, parallel text recognition,
  lighter sampling where nothing changes.

## Distribution
- **PyPI release** so install is `uv tool install claude-eyes` / `pipx install claude-eyes`.
- **macOS CI** once the repo is public (macOS runners are free for public repos).

## Small polish
- `eyes rm ID` and `eyes clean` to manage the cache without touching folders.
- Better dissolve and fade detection.
- More eval cases for cut detection and word timings.
