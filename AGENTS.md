# Installing Eyes (for agents)

A user asked you to install Eyes. Do it end to end without asking about routine steps.

1. Install the command line tool, using the first that works:
   ```bash
   uv tool install git+https://github.com/moritzkremb/claude-eyes
   pipx install git+https://github.com/moritzkremb/claude-eyes
   python3 -m pip install --user git+https://github.com/moritzkremb/claude-eyes
   ```
   If `eyes` is then not found, the install folder isn't on PATH: run `uv tool update-shell` or
   `pipx ensurepath`, or call it as `python3 -m eyes`.
2. `eyes setup --fix` installs ffmpeg, whisper.cpp and a speech model (about 570 MB) where it can.
3. `eyes install-skill` copies the skill into `~/.claude/skills` and/or `~/.agents/skills`, depending on which
   agents are present. Use `--to DIR` for another skills folder.
4. `eyes setup` must print `READY`. If it prints `NOT READY`, it names what's left. If that needs a password
   (sudo) or a choice only the user can make, show them the exact command once.

Then tell the user to restart their agent and try: "Use eyes to watch <video> and tell me ...".
Every command accepts `--json`. Usage is in `skills/eyes/SKILL.md`.

## Working on this repo

- Source: `src/eyes/` (CLI in `cli.py`). Skill: `skills/eyes/SKILL.md` (bundled into the package).
- Test: `python tests/smoke.py` (needs ffmpeg). Cut accuracy: `python tests/eval_cuts.py CASES.json`.
- Keep it dependency-light and cross-platform (macOS, Linux, Windows).
