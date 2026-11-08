---
type: meta
updated: 2026-11-08
---
# Brain conventions

How notes in this vault are written. Every agent that uses the brain (Claude Code, Codex and others) follows this when recording; edit it and they will follow the new rules.

## One idea per note
Each note holds one durable fact, rule or lesson. If a note starts covering two things, split it and link the halves.

## Layout: one area per project, plus Global
```
Home.md                         index of projects and global notes
_meta/Conventions.md            this file
Global/<Type>/                  knowledge that applies across projects
Projects/<Name>/<Name>.md       the project hub
Projects/<Name>/<Type>/         everything specific to that project
```
Each project area gets its own graph, and recall searches the current project first. So:
- A note about one project goes in that project's area.
- A note that applies everywhere (most preferences about how the user works) goes in `Global/`.
- A note that genuinely spans two or three projects also goes in `Global/`, listing them all in `projects:`.

Create a new project area with `brain init-project "<Name>" <repo-dir>`. It writes the hub with `paths:` filled in, so the session hook finds it.

## Type folders
The same type folders are used inside `Global/` and inside each project area. Create them only when the first note of that type arrives.

| Folder | `type` | What goes here |
|---|---|---|
| `Preferences/` | `preference` | How the user wants the agent to work (corrections and confirmed approaches) |
| `Decisions/` | `decision` | A choice that was made, with the why and what was rejected |
| `Gotchas/` | `gotcha` | Something non-obvious that broke or would break, and how to avoid it |
| `Patterns/` | `pattern` | A reusable recipe or technique that worked |
| `References/` | `reference` | Pointers to external things: dashboards, docs, accounts, tickets |

The hub (`type: project`) sits directly in its project folder: what the project is, how to run things, and a Notes list linking every note in the area.

## Frontmatter
```yaml
---
type: gotcha
projects: ["[[Billing API]]"]   # omit for global notes
created: 2026-10-15
updated: 2026-10-15
status: active                       # active | superseded | resolved
---
```
Project hubs also carry `paths:` (absolute folders of the repo, `~/` allowed) and `aliases:`. The session hook uses `paths:` to load the right hub for the folder the agent is working in.

## Body
1. `# Title` matching the filename.
2. The fact, stated plainly in a few lines.
3. `**Why:**` what happened or why it matters.
4. `**How to apply:**` what the agent should do differently.
5. Links: `Related: [[Other note]]`. Always link the project hub. Links are the graph's edges, so link generously. Links work across areas in Obsidian, but a project's own graph only sees links inside that project.

## Names
- Filenames are short readable titles: `Run tests inside the app container.md`.
- Never use the words *secret, password, token, credential* or *service account* in a filename. graphify drops files with those names as possible key dumps, so the note would never be found.
- Never store an actual key, password or token value in a note. Describe it ("the payment provider's test key in phpunit.xml.dist") instead.

## Maintenance
- Before creating a note, search for an existing one and update it instead.
- When a fact stops being true, set `status: superseded` (or `resolved`) and add a line saying what replaced it, rather than deleting.
- Dates are absolute (`2026-10-15`), never "yesterday".
