---
name: brain
description: "Your long-term memory: the user's Obsidian vault \"Agent's Brain\" at ~/brain, indexed as a knowledge graph with graphify. Use it to RECALL before any non-trivial task (starting work in a project, debugging, planning, making a decision, or whenever the user refers to earlier work, \"last time\", \"like we did before\", a preference, or a project by name), and to RECORD automatically whenever something worth keeping comes up: a correction or preference from the user, a decision and its reason, a gotcha that cost time, a working recipe, an external reference, or project facts not visible in the repo. Also use for \"remember this\", \"forget that\", \"what do you know about X\", \"/brain\". This replaces any built-in memory, so use it even when the user doesn't mention the brain."
---
<!-- Managed by agent-brain: `brain setup` overwrites this file. Edit src/agent_brain/skills/brain/SKILL.md in the agent-brain repo instead. -->

# Agent's Brain

The brain is a vault of small linked Markdown notes at `~/brain` (a symlink to the Obsidian vault). The vault is a git repo. When it has a remote, it syncs across the user's machines: sessions pull at start, and `brain rebuild` plus the end-of-reply hook commit and push your writes in the background. `brain sync` does it on demand. Other agents (Codex and others) use the same vault, so notes may have been written by any of them.

The brain is organised **per project**:
- `~/brain/Projects/<Name>/` holds everything about one repo: the hub note `<Name>.md` plus type folders (`Decisions/`, `Gotchas/`, `Patterns/`, `Preferences/`, `References/`).
- `~/brain/Global/` holds knowledge that applies across projects, in the same type folders.

graphify turns the notes and their `[[wikilinks]]` into graphs under `~/.graphify/brain/`: one per project, plus one for the whole vault. That's how you find what's relevant without reading everything.

It replaces the built-in auto memory. Do not write to `~/.claude/projects/*/memory/`; anything worth remembering goes here.

The notes are the source of truth and the graph is only an index. Always open the actual note before acting on it, and treat what it says as "true when written": check file names, flags and commands against the current code before relying on them.

All commands go through the `brain` command on PATH (installed by the `agent-brain` tool; `brain doctor` checks the setup):

```bash
brain query "<question>" [budget]             # current project's graph (whole vault if the folder has no project)
brain query "<question>" --all                # whole vault: cross-project questions, or nothing found in the project
brain query "<question>" --project "<Name>"   # another project's graph
brain find <word> [word...]                   # notes anywhere containing all the words (dedupe before writing)
brain project [dir]                           # project hub for a folder (default: cwd; exit 1 if none)
brain init-project "<Name>" <repo-dir>...     # create Projects/<Name>/ with a hub mapped to those folders
brain rebuild                                 # rebuild all graphs (structural, no LLM, <1s)
```

The query prints which scope it searched and what the `src=` paths are relative to.

Note format, folders and naming rules live in `~/brain/_meta/Conventions.md`. Read it before your first write in a session; the user may have changed it.

## Recall

At session start a hook has already put three things into context: the current project's hub note, that project's preferences, and the global preferences. That is the minimum. Before non-trivial work, go one step further:

1. Run `brain query "<what the task is about>"` from the repo folder. It searches only this project's area. Use the words a note would use (component names, error text, tool names), not the user's whole message.
2. The output lists nodes with `src=<path>`. Open the few notes that look relevant, resolving paths against the folder named in the scope line. Skip the rest.
3. Widen only when you need to. Use `--all` when the project's area has nothing relevant, or when the question is about another project or crosses projects ("how did we handle webhooks elsewhere?"). Then try `brain find <keyword>` before concluding there's nothing.
4. Use what you found quietly. Mention a note only when it changes what you do ("the brain says tests here run through `make test`, so...").

Don't re-run recall on every turn of a task you've already recalled for. Do run it again when the task shifts to a different area.

## Record (automatic)

Writes are automatic: record without asking, then say what you saved in one line at the end of your reply, e.g. `Saved to brain: [[Queue retries double-charge]] (new), [[Billing API]] (updated).`

**Worth recording** (would change how a future session behaves):
- A correction or preference from the user, including quiet confirmations that an unusual approach was right → `Preferences/`
- A decision with its reason and what was rejected → `Decisions/`
- Something non-obvious that broke or nearly did, and how to avoid it → `Gotchas/`
- A recipe that worked and will be needed again → `Patterns/`
- Where something lives outside the repo (dashboards, accounts, tickets, docs) → `References/`
- Project facts you can't get from the code: environment quirks, which account to use, who owns what → the project hub or a linked note

**Where it goes:**
- About this project only → `Projects/<Name>/<Type>/`. This is the usual case.
- Applies across projects (how the user likes to work in general, a technique that isn't repo-specific) → `Global/<Type>/`.
- Spans a few specific projects → `Global/<Type>/`, listing them all in `projects:`.

When unsure, ask whether the note would still be true in a different repo. If yes, it's global.

**Not worth recording:** code structure or anything `git log` / the repo already says, the state of the current task, one-off details, guesses you haven't confirmed. And never a key, password or token *value*: the vault syncs to other devices. Describe where it lives instead.

**How to write:**
1. `brain find <key words>`. If a note already covers it, update that note (bump `updated:`, add the new fact or a dated "Update" line) rather than creating a near-duplicate. If the other note was written by another agent, adjust the relevant lines; don't rewrite the whole note.
2. If the repo has no project area yet (`brain project` exits 1), create one with `brain init-project "<Name>" <repo-dir>`. Give it a readable name such as `Billing API`, not the folder slug. Then replace the hub's placeholder line with a sentence about what the project is.
3. Create one note per idea, following Conventions: right area and type folder (create the folder if it's the first of its type), frontmatter, `**Why:**` and `**How to apply:**`, absolute dates.
4. Link it: the project hub via `projects:` and in the body, plus any related notes. Links are the graph's edges, and an unlinked note is hard to find later.
5. Add a one-line entry to the project hub's "Notes" section. For global notes, add it to `Home.md` under Global. Humans browsing Obsidian see these lists.
6. `brain rebuild`.

Record at natural moments: when the user corrects you, when a decision lands, when a bug's cause is found. Don't save everything up for the end of the session; sessions end without warning.

## Forget and fix

- "Forget X" / a fact turns out wrong → set `status: superseded` (or `resolved`) and add a line saying what replaced it. Delete the file only if the user explicitly asks for deletion.
- If a note you recalled contradicts what you see in the code, trust the code, fix the note, and mention it.

## Maintain

When asked to tidy the brain (or when you notice duplicates while recording):
- Merge notes that say the same thing.
- Add missing links between related notes.
- Mark stale notes superseded.
- Move a project note that turned out to apply everywhere into `Global/`.
- Keep `Home.md` and each hub's Notes list in sync with the folders.

Rebuild when done.

## Explicit commands

- `/brain` or "what do you know about X" → recall and summarise what the notes say, with links.
- `/brain record` or "remember this" → record now.
- `/brain rebuild` → rebuild and report the node/edge count.
