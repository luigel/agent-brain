# Handoff: connect your agent to the Agent's Brain

For: any coding agent on a machine where agent-brain is set up, such as Codex, Cursor, Gemini CLI, Copilot, Aider or OpenCode. Give this file to the agent and let it work through the steps.

## Goal

The user keeps one long-term memory for all their coding agents: an Obsidian vault called **Agent's Brain**, organised **per project** and indexed as knowledge graphs with graphify. `brain setup` already wires Claude Code and Codex; use that setup as the reference implementation.

Your job is to connect **your own agent** to the **same** brain, so that every agent reads from and writes to one memory.

- Don't build a second brain.
- Don't change how the shared pieces work.
- Configure only your own agent.

## How the brain is organised: per project

```
~/brain/                                  → symlink to the vault folder (by default ~/Documents/Agent Brain)
  Home.md                                 index: list of projects + global notes
  _meta/Conventions.md                    how notes are written (read this first)
  _meta/skills/, _meta/third-party.json   the user's own skills and packs (not notes; recall skips them)
  Global/<Type>/                          knowledge true in any repo
  Projects/<Name>/<Name>.md               project hub; frontmatter `paths:` lists the repo folder(s)
  Projects/<Name>/<Type>/                 everything specific to that project
```

`<Type>` is one of `Preferences/`, `Decisions/`, `Gotchas/`, `Patterns/` or `References/`. A type folder is created only when its first note arrives.

**What "per project" means in practice:**
- **Which project am I in?** Find the hub whose `paths:` contains the current working folder. `brain project` does this lookup.
- **Each project has its own graph**, and there's one for the whole vault. `brain query` run inside a repo searches that project plus `Global/`. `--all` widens to the whole vault, and `--project "<Name>"` targets another project (plus `Global/`).
- **Session-start context is per project:** that project's hub, that project's preferences, and the global preferences.
- **Where a new note goes:**
  - about this repo → `Projects/<Name>/<Type>/`
  - still true in any other repo → `Global/<Type>/`
  - spans a few named projects → `Global/<Type>/`, listing them all in `projects:`
- **New repo:** when the first thing worth recording about a repo comes up, run `brain init-project "<Readable Name>" <repo-dir>`. It creates the area and a hub with `paths:` set, so every agent's next session finds it. Don't create areas for repos that have nothing to record yet.

## Shared pieces (reuse, don't recreate)

| Thing | Where | Notes |
|---|---|---|
| Vault | `~/brain` | Always use this path, not the real folder: its name may contain spaces or quotes. |
| Note rules | `~/brain/_meta/Conventions.md` | Layout, frontmatter, body shape, naming. Every agent follows it. |
| `brain` command | `~/.local/bin/brain` (on PATH) | Installed by the **agent-brain** tool (`uv tool install git+https://github.com/luigel/agent-brain`). It bundles a pinned graphify. One shared implementation for every agent: don't fork or patch the installed copy. `brain doctor` checks a machine's setup. |
| Graphs | `~/.graphify/brain/all/`, `~/.graphify/brain/projects/<slug>/` | Kept outside the vault so they never get committed. Rebuilt automatically when notes change. |
| Reference skill | `src/agent_brain/skills/brain/SKILL.md` in the agent-brain repo (installed copies: `~/.claude/skills/brain/`, `~/.agents/skills/brain/`) | The agent-neutral workflow. `brain setup` installs it into each Claude profile and into `~/.agents/skills` (read by Codex, Cursor, Gemini CLI and others); read it if your agent has skills or rules. |

### The `brain` command

```bash
brain query "<question>" [budget]             # current folder's project + Global/ (whole vault if no project matches)
brain query "<question>" --all                # whole vault
brain query "<question>" --project "<Name>"   # a named project + Global/
brain find <word> [word...]                   # notes anywhere containing all the words (dedupe before writing)
brain project [dir]                           # hub note for a folder (exit 1 if none)
brain init-project "<Name>" <repo-dir>...     # create Projects/<Name>/ with a hub mapped to those folders
brain rebuild                                 # rebuild all graphs; structural, no LLM, <1s
brain context [dir] [--json]                  # session-start text for a folder: hub + project prefs + global prefs
```

- `query` prints a scope line, then up to 5 notes ranked by full-text match (title and body), each with how many of the question's words it matched and its first line. It warns ("Weak matches") when the best note matched under 40% of the words, and names the best note in the whole vault when that one is outside the scope. The current folder's project hub is left out, since session start already injected it. Paths are relative to `~/brain/`. The optional budget (default 1500 tokens) cuts whole results.
- `context` reads `{"cwd": ...}` from stdin when a hook pipes it, or takes a folder argument. `--json` wraps the output as `{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"..."}}`.

### Facts already established (don't re-investigate)

- **No LLM needed.** graphify parses Markdown headings and `[[wikilinks]]` structurally: no API key, no token cost, under a second. `brain` sets `GRAPHIFY_OUT` so output never lands inside the vault.
- **Blocked filenames.** graphify silently skips files whose names contain *secret, password, token, credential* or *service account*. Note filenames must avoid those words; `init-project` refuses such names.
- **Graph links stay inside the project.** A project graph only sees links between notes in that project. Links to `Global/` notes still work in Obsidian and in the whole-vault graph. `brain query` doesn't use the graphs; it ranks the notes' text.
- **Sync.** The vault is a git repo. If it has a remote (the user's own private repo), sessions pull at start, and `brain rebuild` and the Stop hook commit and push in the background; `brain sync` does it on demand. Notes are stored unencrypted on the remote, so never store a key, password or token *value* in a note; describe where it lives instead.

## Setup steps

### Step 0: Find out what your agent supports

Check your own documentation and config files; don't guess. Note which of these your agent has:

1. **A global instructions file**, loaded in every session (for example `AGENTS.md`, `GEMINI.md`, a rules file).
2. **Skills, rules or custom commands** that load on demand.
3. **A session-start hook** that can run a command and add its output to your context.
4. **A built-in persistent memory** of its own.
5. **A sandbox** that limits which folders you can write to.

Steps 2 to 6 below depend on these answers. A known-setups table at the end covers agents already checked.

### Step 1: Check the shared pieces work from your agent

If `brain` isn't on PATH yet, this machine isn't set up. Install it (needs `uv` and `git`), then wire the vault:

```bash
uv tool install git+https://github.com/luigel/agent-brain
```
```bash
brain setup
```

Then run `brain doctor`.

Run each of these from your agent:
1. `brain rebuild`: should list `all` plus one line per project.
2. `brain query "how do I run tests" --all`: should print a scope line and a numbered list of notes.
3. From inside a repo that has a project area: `brain query "<something about it>"`; the scope line should name that project.
4. `brain project <that repo's folder>`: should print `.../Projects/<Name>/<Name>.md`.
5. `brain context <that repo's folder>`: should include the project hub and, if any exist, the preferences sections.

If the vault has no projects yet, steps 3 to 5 have nothing to show; that's fine.

**Writes:** your agent must be able to write to two real paths:
- the folder `~/brain` points to (`readlink ~/brain`);
- `~/.graphify/brain`.

If your sandbox blocks either, add it as a writable folder in your agent's config. Writable folders are a permission change, so show the user the change before saving it.

### Step 2: Add the brain protocol to your standing instructions (required)

Every agent needs this, with or without skills or hooks. Append the block below to your agent's **global** instructions file and leave everything else in that file untouched. If your agent has skills or rules (step 3), you can shorten this to the first two bullets plus a pointer to the skill.

```markdown
# Agent's Brain (long-term memory)

- `~/brain` is your long-term memory, shared with the user's other coding agents. It replaces any built-in memory. Note rules: `~/brain/_meta/Conventions.md`. Tool: the `brain` command.
- The brain is per project. `brain project` maps the current folder to `~/brain/Projects/<Name>/`. Knowledge true in any repo lives in `~/brain/Global/`.
- **Recall** before non-trivial work. If session-start context wasn't injected, run `brain context` in the repo folder first. Then run `brain query "<topic>"` from the repo folder with 3 to 8 concrete words (exact error text, component, command or tool names); it searches this project and `Global/`, titles and bodies. Open the few relevant notes. If it says "Weak matches" or nothing fits, query once more with different words; use `--all` for cross-project questions or when that also finds nothing. Notes are true *when written*: check names, flags and commands against the code before relying on them.
- **Record automatically** whenever something durable comes up. That means a correction or preference from the user, a decision and its reason, a gotcha that cost time, a reusable recipe, an external reference, or a project fact that isn't in the repo. Don't record code structure, git history, task state, or any key, password or token value.
- **How to record:**
  1. `brain find <words>`; update an existing note rather than duplicating it. If another agent wrote it, adjust the relevant lines only.
  2. If the repo has no area (`brain project` exits 1), run `brain init-project "<Readable Name>" <repo-dir>` and replace the hub's placeholder line.
  3. Write one note per idea in `Projects/<Name>/<Type>/`, or in `Global/<Type>/` if it's true in any repo, following Conventions: frontmatter, `**Why:**`, `**How to apply:**`, absolute dates. Link the hub.
  4. Add a one-line entry to the hub's Notes list, or to `Home.md` under Global for global notes.
  5. Run `brain rebuild`.
  6. End your reply with one line, e.g. `Saved to brain: [[Note]] (new), [[Hub]] (updated)`.
- **Forget:** set `status: superseded` and say what replaced it. Delete only when the user explicitly asks.
```

### Step 3: Install a brain skill or rule (if your agent supports them)

If your agent reads `~/.agents/skills`, `brain setup` already put the `brain` skill there; check that it loads. Otherwise create a `brain` skill, rule or command in your agent's global (user-level) location. Adapt it from `~/.agents/skills/brain/SKILL.md`:
- Keep the behaviour identical: per-project recall with `--all` fallback, automatic recording, the placement rules, `init-project`, forget/fix, and maintenance.
- Call the `brain` command.
- Remove wording specific to another agent.
- Make the trigger description broad. It should fire on starting work in a repo, debugging, planning, decisions, references to earlier work, "remember this", "forget that" and "what do you know about X".

### Step 4: Load per-project context at session start

**If your agent has session-start hooks:**
- Register `~/.local/bin/brain context --json 2>/dev/null || true` (or the same without `--json` if your agent injects plain stdout), with a timeout of about 30 seconds.
- Your hook must give the command the session's working folder, either as `{"cwd": "<dir>"}` on stdin or as a folder argument. Otherwise it can't pick the project.
- Match every way a session starts (start, resume, clear/compact) if your agent distinguishes them.
- **Merge with existing hooks; never replace them.**
- Output is capped at 8,000 characters.

**If it has no hooks:** step 2 already tells the agent to run `brain context` at the start of work in a repo. Nothing more to do.

**Optional: end-of-reply reminder to record.** Claude Code also runs `brain stop-check` as a `Stop` hook.
- Once per session, after real work, it blocks the agent from stopping with a reason asking it to record anything worth keeping. Real work means a file edit, or 8 or more tool calls.
- It stays silent if the session already wrote to the brain, and it respects `stop_hook_active` to avoid loops. Markers live in `~/.cache/agent-brain/stop-reminded/`.
- It reads a JSONL transcript with Claude-style `tool_use` blocks, taken from `transcript_path` in the hook input.
- If your agent has a stop/turn-end hook **with that same input and transcript format**, you can register the same command. If it doesn't, don't register it, because it would never fire. Mention the gap in your report instead; making `stop-check` work with your transcript format is a change to the shared tool, so it goes through the agent-brain repo.

### Step 5: Built-in memory

If your agent has its own persistent memory, propose turning it off so the brain is the only source of truth; `brain setup` does this for Claude Code. **Ask the user before changing it.** If it holds memories worth keeping, offer to migrate them into the right project area or `Global/`, following Conventions.

### Step 6: Map your agent's project folders

Your agent may know repos under different paths from the ones in the hubs.
- List the project folders your agent uses (trusted projects, recent workspaces).
- For each, run `brain project <dir>`.
- If it prints nothing but the folder is a checkout of a repo that already has an area (compare `git remote -v` with the hub's paths), add the folder to that hub's `paths:` list.
- If it's ambiguous, ask the user.
- Don't create areas for repos with nothing to record.

## Known setups

| Agent | Status | Where things go |
|---|---|---|
| Claude Code | Wired by `brain setup` (reference) | Skill `~/.claude/skills/brain/`; SessionStart hook (`brain context`) and Stop hook (`brain stop-check`) in `~/.claude/settings.json`; pointer block in `~/.claude/CLAUDE.md`; built-in auto memory off. Extra Claude profiles: `brain setup --claude-dir <dir>`. |
| Codex | Wired by `brain setup` when `~/.codex` exists | Skill from `~/.agents/skills/brain/`; SessionStart hook (`brain context --json`) merged into `~/.codex/hooks.json`; pointer block in `~/.codex/AGENTS.md`. By hand: verify in a fresh Codex session that the context arrives, add the two writable folders in `~/.codex/config.toml` if the sandbox blocks writes (check the current key name in the Codex docs), and decide about Codex's own memory. |
| Anything else | Not yet | Use step 0. Check the agent's own docs for its instructions file, skills or rules, hooks and memory. |

## Rules for sharing one brain

- **Several agents write here.** Run `brain find` before creating anything. When updating, adjust the relevant lines; don't rewrite a whole note another agent wrote.
- **Don't change the system.** That means `Conventions.md`, the per-project layout, and how the `brain` command behaves. If you think something should change, propose it to the user; every connected agent depends on these, and a silent change breaks them.
- **Leave other agents' config alone.** Don't edit another agent's configuration (`~/.claude/`, `~/.codex/`, …) unless the user asks.

## Done when

- [ ] Every step-1 command works from your agent, including writes, with no sandbox denials.
- [ ] Your global instructions file has the brain protocol block.
- [ ] A brain skill or rule exists, if your agent supports them.
- [ ] A fresh session in a repo with a project area shows that hub and the global preferences, either through a hook or because the agent ran `brain context` itself.
- [ ] Built-in memory has been discussed with the user (if your agent has one).
- [ ] Your project folders are mapped to hubs, or listed as unmapped in your report.
- [ ] You've reported back: what changed (files and settings), anything that didn't work, and any decision left for the user.
