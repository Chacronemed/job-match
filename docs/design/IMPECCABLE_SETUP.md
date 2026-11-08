# Impeccable pass — tool setup

Branch `design/impeccable-pass` (2026-11-07). Everything is installed **in the project**
(`.claude/`), nothing at user level, no hook, no live mode. Diagnostic only: the dashboard code is
untouched on this branch.

## What was run

| Step | Command | Result |
|---|---|---|
| Impeccable skill | `npx impeccable@4.8.0 install --providers=claude --scope=project --no-hooks` | skill + engine v0.1.18 + 4 agents in `.claude/`; the design hook was **refused** (`--no-hooks`) |
| Telemetry | `npx impeccable telemetry off` | `telemetry: off`. The CLI stores this choice in `~/.impeccable/config.json` (the only file written outside the repo; the cloud container is ephemeral). For later sessions `.claude/settings.json` also sets `IMPECCABLE_NO_TELEMETRY=1` |
| Live copy agent | `IMPECCABLE_LIVE_COPY_AGENT=off` | set in the shell for this session and in `.claude/settings.json` `env`. Live mode (`/impeccable live`, `live-server`, `live-inject`) was **not** used |
| transitions.dev (free only) | `npx skills add Jakubantalik/transitions.dev --skill transitions-dev --skill transitions-polish --agent claude-code --copy -y` | the two free skills. Not installed: the Pro recipes (`npx transitions-dev add …`, sign-in), the `transitions-refine` CLI / Refine panel. `transitions-ui-generation` was skipped by the CLI itself (invalid YAML front matter) |
| Emil Kowalski skills | `npx skills@latest add emilkowalski/skills --skill review-animations --skill improve-animations --skill find-animation-opportunities --skill animation-performance --skill break-ui --agent claude-code --copy -y` | only the five kept skills were installed, so there was nothing else to remove (the repository also offers animate, animate-expo, animation-vocabulary, apple-design, ask-sonner, choreograph, emil-design-eng, mobile-native, pick-ui-library, prototype, remove-animations, write-swift: not installed) |

`DO_NOT_TRACK=1` was set for the `skills` CLI runs.

## Disabled for this pass (not deleted)

| What | How | Undo |
|---|---|---|
| Skill `design-taste-frontend` (`.claude/skills/design-taste-frontend/`, still in `skills-lock.json`) | `.claude/settings.json` → `permissions.deny: ["Skill(design-taste-frontend)"]` | remove the deny entry |
| Plugin `frontend-design@claude-plugins-official` | `.claude/settings.json` → `enabledPlugins` set to `false` (was `true`); its skill is also denied (`Skill(frontend-design)`, `Skill(frontend-design:frontend-design)`) | set back to `true`, remove the deny entries |

Reason: both push a marketing/landing-page art direction (taste-skill says « not for dashboards or
app screens »); this pass judges an Operate surface against its own `DESIGN.md`, and two
competing design voices would blur the diagnosis.

## Files added or modified by the installations

**Added**
- `.claude/skills/impeccable/` — 59 files, 2.3 MB: `SKILL.md`, `reference/*.md` (commands),
  `reference/degraded/`, `scripts/` (launcher `impeccable`, `impeccable.cmd`, `live-browser*.js`,
  `modern-screenshot.umd.js`, `command-metadata.json`, `engine-checksums.txt`, `VERSION`),
  `scripts/data/font-index.json`, `scripts/data/font-index-failures.json`.
  `scripts/bin/linux-x64/impeccable` (21 MB engine binary) is **gitignored**: the launcher
  downloads it again on first run and checks it against `scripts/engine-checksums.txt`.
- `.claude/agents/impeccable-asset-producer.md`, `impeccable-documenter.md`,
  `impeccable-finish-reviewer.md`, `impeccable-manual-edit-applier.md`
- `.claude/skills/transitions-dev/` (38 files: `SKILL.md`, `_root.css`, 35 recipe `.md`,
  `LICENSE.txt`), `.claude/skills/transitions-polish/` (4 files)
- `.claude/skills/animation-performance/`, `break-ui/` (+ `CATALOG.md`),
  `find-animation-opportunities/`, `improve-animations/` (3 files), `review-animations/` (2 files)

**Modified**
- `skills-lock.json` — seven entries added by the `skills` CLI (source, path, hash, `installMode: copy`)
- `.claude/settings.json` — plugin disabled, deny rules, the two Impeccable env vars
- `.gitignore` — keep `.claude/skills/impeccable/scripts/data/` (the repo-wide `data/` rule
  would have dropped it), ignore the engine binary and `.impeccable/` (critique snapshots,
  build state)

**Written by this pass (not by an installer):** `PRODUCT.md` (`/impeccable init`), a new final
section in `docs/design/DESIGN.md`, `docs/design/IMPECCABLE_AUDIT.md`, this file, and
`docs/design/screenshots/impeccable/` (62 PNGs).

## Security notes

- The skills were read before use: the emilkowalski and transitions skills are Markdown and CSS
  only; Impeccable ships a checksum-pinned binary and browser scripts used only by live mode
  (unused). No skill was given a hook.
- Impeccable's detector was run on files and on a local fixture server (`127.0.0.1`, test seed,
  mocked API), never on the production dashboard.
