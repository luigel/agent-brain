# agent-brain

Long-term memory for coding agents, kept per project. Your agents (Claude Code, Codex and others) record what they learn about you and your repos into an Obsidian vault on your machine: your corrections and preferences, decisions, gotchas, recipes and references. At the start of every session they recall what's relevant. The vault is indexed as knowledge graphs with [graphify](https://pypi.org/project/graphifyy/), which needs no LLM and no API key.

The tool provides:
- **The `brain` command.** Agents use it to recall (`brain query`, `brain find`) and record (`brain init-project`, `brain rebuild`). It also runs as their session hooks (`brain context`, `brain stop-check`).
- **`brain setup`.** It wires a machine in one step: a starter vault, the `~/brain` link, the `brain` skill, the hooks, the instruction-file pointer, and turning off the agents' built-in memory.

Every dev gets their **own private brain**. Nothing is shared unless you push your vault somewhere yourself.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) and `git`.
- Claude Code and/or Codex.
- Optional: [Obsidian](https://obsidian.md), to browse and edit notes yourself.
- Optional: Node.js, only for third-party skill packs installed with `npx` (see [Your own kit](#your-own-kit)).

## Install

```bash
uv tool install git+https://github.com/luigel/agent-brain
```
```bash
brain setup
```

That's it. Start a new agent session.

- Add `--dry-run` to see what setup would change without changing anything.
- `brain doctor` checks the setup at any time.
- In Obsidian, use "Open folder as vault" on `~/Documents/Agent Brain` to read your notes.

## What setup changed

- **The vault.** It's at `~/Documents/Agent Brain` (or `--vault <dir>`), created from a starter with `Home.md`, `_meta/Conventions.md` and empty `Global/` and `Projects/` folders. It's a local git repo, so `git -C ~/brain log` shows everything your agents wrote.
- **`~/brain`.** A link to the vault. Agents always use this path.
- **Claude Code** (if `~/.claude` exists): the `brain` skill in `~/.claude/skills/`, `SessionStart` and `Stop` hooks in `~/.claude/settings.json`, a short block in `~/.claude/CLAUDE.md`, and `autoMemoryEnabled: false`. Add `--claude-dir <dir>` (repeatable) for extra Claude profiles.
- **Codex** (if `~/.codex` exists): a `SessionStart` hook in `~/.codex/hooks.json` and the same block in `~/.codex/AGENTS.md`. Codex reads the skill from `~/.agents/skills/`.
- **`~/.agents/skills/brain`**, for Codex, Cursor, Gemini CLI and other agents that read that folder (`--no-universal` skips it).

Setup is idempotent and only changes what it owns. It keeps your other hooks and instructions, and replaces only its own hooks and its marked `<!-- agent-brain:start -->` block. Before changing a file it saves a copy next to it (`<file>.bak-agent-brain-<timestamp>`). Folders it replaces go to `~/.cache/agent-brain/backups/`. To undo setup, restore those copies and delete `~/brain`.

## Sync and a second machine

The vault works locally. To keep it on more than one machine:

1. Create an **empty, private** repo on your own GitHub account (for example `my-brain`).
2. On each machine, run:
   ```bash
   brain setup --vault-repo git@github.com:<you>/my-brain.git
   ```
   - On the first machine, setup pushes your existing vault to it.
   - On the other machines, setup clones it. If that machine already has an untouched starter vault, setup moves it to `~/.cache/agent-brain/backups/` first.
   - If both sides already have notes, setup stops and prints the commands to merge them by hand.

After that it syncs on its own:
- **Session start:** the `SessionStart` hook pulls, with an 8-second timeout. If you're offline, the session uses the local notes and says so.
- **After writes:** `brain rebuild` and the end-of-reply hook commit and push in the background. Agents never wait on the network.
- **On demand:** `brain sync` commits, pulls and pushes. Background problems go to `~/.cache/agent-brain/sync.log`, and `brain doctor` reports them until a sync succeeds.
- **Not in git:** `.obsidian/` (per-machine settings and plugin configs).

Notes are stored **unencrypted** in that repo. Never put a key, password or token *value* in a note; describe where it lives instead.

## Your own kit

Your vault can also carry your own agent skills, so they follow you to every machine. They live in the vault, not in this repo, and recall never shows them as notes.

- **Skills:** `<vault>/_meta/skills/<name>/SKILL.md`. Add one with:
  ```bash
  brain skill import ~/path/to/my-skill
  ```
  It copies the folder into your vault and installs it on this machine. Other machines pick it up on their next `brain setup`.
- **Third-party packs:** list them in `<vault>/_meta/third-party.json`, then run `brain setup --third-party`. Packs are installed from their authors, never copied:
  ```json
  {
    "skills_cli": [
      {"source": "someone/skills", "skills": ["a-skill", "another-skill"], "agents": ["codex", "cursor"]}
    ],
    "git": [
      {"name": "a-pack", "repo": "https://github.com/someone/a-pack.git", "dest": "~/.codex/a-pack",
       "link": {"path": "~/.agents/skills/a-pack", "target": "skills"}}
    ],
    "manual": [
      {"name": "something else", "how": "how to install it yourself"}
    ]
  }
  ```

Setup only updates or removes skills it installed. It records them in `.agent-brain-managed.json` in each skills folder. It skips a skill, and tells you why, when:
- **someone else's copy** already exists with that name: re-run with `--adopt <name>` to replace it (the old copy is backed up);
- **your claude.ai account syncs** a skill with that name into the profile: turn it off on claude.ai to use yours;
- **Codex has its own copy** in `~/.codex/skills/<name>`.

`brain skills` shows the status of every skill everywhere.

## How the brain is organised

```
~/brain/                          -> link to the vault
  Home.md                         index
  _meta/Conventions.md            how notes are written
  _meta/skills/                   your own skills (not notes)
  Global/<Type>/                  knowledge true in any repo
  Projects/<Name>/<Name>.md       project hub; `paths:` lists the repo folder(s)
  Projects/<Name>/<Type>/         everything about that project
```

Graphs live outside the vault, in `~/.graphify/brain/all/` and `~/.graphify/brain/projects/<slug>/`, and are rebuilt automatically when notes change. Inside a repo, `brain query` ranks that project's notes and `Global/` by their full text (title and body), then lists the notes linked to the best matches; `--all` widens it to the whole vault.

## Updating

```bash
uv tool upgrade agent-brain
```
```bash
brain setup
```

Re-running `setup` refreshes the skill and hooks. With no `--vault`, it keeps the existing `~/brain` link.

## Commands

```
brain query "<question>" [N] [--all | --project NAME]   recall; scoped to the current folder's project
brain find <words...>                                    search every note (dedupe before writing)
brain project [dir]                                      project hub for a folder
brain init-project "<Name>" <repo-dir>...                create a project area mapped to repo folders
brain rebuild                                            rebuild all graphs
brain sync                                               commit, pull and push the vault now
brain context [dir] [--json]                             SessionStart hook output
brain stop-check                                         Stop hook: one end-of-session "record learnings" nudge
brain skills                                             where each skill is installed
brain skill import <dir>                                 add a skill folder to your kit
brain setup / doctor / version
```

## Other agents

`docs/HANDOFF.md` is an agent-agnostic brief. Give it to any coding agent (Cursor, Gemini CLI, …) to connect it to the same brain.

## Limitations

- One private vault per dev. There's no shared or team vault yet.
- macOS and Linux only.
- Claude Code and Codex are wired automatically. Other agents connect by hand through `docs/HANDOFF.md`.
- If you add sync, notes are stored unencrypted in your git remote.

## Development

```bash
uv tool install --editable .
```

The editable install makes `brain` run your checkout directly. Tests run `brain` against a throwaway `HOME`. Run one file at a time:

```bash
python3 -m unittest discover -s tests -p test_vault.py
```

- The bundled skill is `src/agent_brain/skills/brain/`.
- The instruction-file pointer is `src/agent_brain/data/pointer.md`.
- The starter vault is `src/agent_brain/data/vault/`. Files named `dot-x` there are written as `.x`.

## License

MIT
