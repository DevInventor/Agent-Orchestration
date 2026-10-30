# Competitive review: parallel-agent orchestration

**Date:** 2026-10-30 · **For:** the next round of UI and feature work on agent-orchestration 0.8.0

**Method.** Everything here was read on 2026-10-30 from primary sources: official docs, product sites,
changelogs, GitHub READMEs, releases and source. Repo status (stars, last push, archived) comes from
`gh api repos/<owner>/<repo>` on the same day. Claims about our own plugin cite files in this repo.
"Unverified" means the source was not found or did not say. No blog round-ups were used.

**Who has changed status since the brief was written:**
- **Shut down or winding down:** Terragon (shut down Feb 9, 2026), Vibe Kanban's company bloop (shut down Apr 10, 2026; the code is now community-maintained), and Google Jules (winds down Dec 31, 2026).
- **Renamed or replaced:**
  - Crystal is now Nimbalyst.
  - claude-flow is now Ruflo.
  - get-shit-done is archived; it continues as GSD Core.
  - Superset is now Paradev.
  - siteboon/claudecodeui is now "CloudCLI".
- **Pivoted or quiet:**
  - Omnara pivoted to a self-hosted managed-agent platform.
  - Inactive for a year or more: opcode (last code commit Oct 2025), container-use (last release Aug 2025).
  - Quiet for about six months: Taskmaster AI and ccpm.
- **Added because they matter:**
  - First-party: Claude Code's own agent view, Projects, dynamic workflows and mods.
  - Workspaces: Paradev, cmux and Happy.
  - Cost tracking: ccusage.
  - Plugins: wshobson's `ship-mate`, Anthropic's official plugins, ECC, oh-my-claudecode and Compound Engineering.

---

## 1. Summary: what is most worth taking

1. **Claude Code now ships most of our hall natively, so stop competing on the run list.**
   - **Agent view** shows Working / Needs input / Idle / Completed / Failed / Stopped, with needs-input sorted first, and `claude agents --json` is "the supported way to read session state" ([agent view](https://code.claude.com/docs/en/agent-view.md)).
   - **Projects** groups threads into Ready for review / Waiting on you / Working / Landing / Idle / Resolved ([projects](https://code.claude.com/docs/en/claude-projects.md)).
   - **`/workflows`** shows phases with agent counts and per-agent tokens ([workflows](https://code.claude.com/docs/en/workflows.md)).
   - What sets us apart is the gated, multi-service plan→test→review pipeline and the validated bus, not the list of runs.
2. **Tell the human when they are needed. The closest dashboards all do, and we do not.**
   - Examples: browser push in [Vibe Kanban](https://vibekanban.com/docs/settings/general.md), OS notifications and dock badges in [Nimbalyst](https://nimbalyst.com/docs/session-management/agent-window-and-session-management.md) and [Paradev](https://docs.paradev.com/agent-status), contextual notification text in [cmux](https://github.com/manaflow-ai/cmux), and a tab-title count ("2 awaiting input") in agent view.
   - Our version needs the browser Notification API plus a count in `document.title`. Effort is S, there are no dependencies, and 127.0.0.1 is a secure context ([MDN](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts)).
3. **A diff surface on the board.**
   - Every dashboard in the closest group has one: [Conductor](https://www.conductor.build/llms-full.txt), [Vibe Kanban](https://vibekanban.com/docs/workspaces/changes.md), [Paradev](https://docs.paradev.com/diff-viewer), [Sculptor](https://github.com/imbue-ai/sculptor/blob/main/docs/help/changes.md), [Claude Squad](https://github.com/smtg-ai/claude-squad/blob/main/README.md) and [Claude Desktop](https://code.claude.com/docs/en/desktop.md).
   - The coder already writes `code/diff.patch` per service (`agents/coder.md`). Show it read-only, with "Viewed" ticks and reviewer findings pinned to lines. Effort is M.
4. **Tokens per run and per agent.**
   - Examples: Conductor rounds agent cost to cents ([0.80](https://www.conductor.build/changelog/0.80.0-stacks.md)), CloudCLI has a cost modal ([releases](https://github.com/siteboon/claudecodeui/releases)), `/workflows` shows per-agent tokens, and Ruflo's cost tracker reads tokens from transcripts through a Stop hook ([ruflo-cost-tracker](https://github.com/ruvnet/ruflo/blob/main/plugins/ruflo-cost-tracker/README.md)).
   - Our version: a plugin `SubagentStop` command hook writes the figures to the bus through `pipe.py`, and the UI only reads them. Effort is M.
5. **Superpowers has moved on, so re-read it and bump the pin.**
   - The latest release is v7.0.1 (2026-10-21) ([releases](https://github.com/obra/superpowers/releases)).
   - Anthropic's official marketplace pins it at 7.0.0, commit bb92a77 ([marketplace.json](https://github.com/anthropics/claude-plugins-official/blob/main/.claude-plugin/marketplace.json)). Our suite pins 6.4.1 (`scripts/test_pipe.py:1800`).
   - The skill set is unchanged. `writing-plans`, which our planner binds, now "records decisions" and checks the plan's length against the spec ([release notes](https://github.com/obra/superpowers/blob/main/RELEASE-NOTES.md)). Effort is S.
6. **Validate a finding before it can block.**
   - Anthropic's `code-review` plugin checks each candidate issue with a separate subagent and drops the ones that fail ([code-review.md](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/code-review/commands/code-review.md)).
   - BMAD routes each finding to intent_gap, bad_spec, patch or defer ([step-04](https://github.com/bmad-code-org/BMAD-METHOD/blob/V6.12/src/bmm-skills/ship/bmad-build/step-04-review.md)).
   - For us a false `blocking` finding costs one of five fix iterations. Effort is M.
7. **Capture what was learned when a run finishes.**
   - Compound Engineering writes `docs/solutions/*.md` that later plans and reviews read back ([ce-compound](https://github.com/EveryInc/compound-engineering-plugin/blob/main/docs/guides/ce-compound.md)). Devin turns sessions into knowledge suggestions that a human approves ([Devin](https://docs.devin.ai/work-with-devin/advanced-capabilities)).
   - We have the codebase-memory graph the planner already queries; it could hold these. Effort is M.
8. **Name collision.**
   - The wshobson/agents marketplace (42k stars) ships a plugin named `agent-orchestration` ([plugin.json](https://github.com/wshobson/agents/blob/main/plugins/agent-orchestration/.claude-plugin/plugin.json)).
   - It also ships `ship-mate`, which has its own `/ship` and a very similar flow: orchestrator → architect → pause for a human → implement → review → QA ([ship.md](https://github.com/wshobson/agents/blob/main/plugins/ship-mate/commands/ship.md)).

---

## 2. Comparison

Legend: — = none found; ? = unverified. "Gate" means the human approves a plan or a launch, not tool permissions.

| Product | Many runs at once | Gates | Diff / review | Notifications | Cost / tokens | Isolation | Packaging |
|---|---|---|---|---|---|---|---|
| **agent-orchestration (us)** | Hall cards, office floor, per-run kanban | Spec and finalize gates (finalize / in-place / reject) | — in UI; `diff.patch` and review findings stay on the bus | — | — | Worktree per service | CC plugin, stdlib Node on 127.0.0.1 |
| Conductor | Workspace sidebar with PR/CI state and hover card | Plan approval; merge blocked by checks and todos | Diff viewer with line comments sent to the agent; PR page | Completion sounds, named notifications | Context gauge; agent cost in cents | Worktree; cloud sandbox | Mac app (closed), iOS, cloud |
| Vibe Kanban | Kanban of issues plus workspace list (Running / Idle / Needs Attention) | Approve / Request Changes card | Side-by-side diff, batched comments, PR creation | Sounds, browser push | Context gauge; no $ | Worktree | `npx`, local web; company shut down |
| Nimbalyst (was Crystal) | Session list, session kanban by phase, attention list | Approvals in the transcript; review queue | Inline red/green with Keep / Revert; PR mode | OS notifications, dock badge, menu-bar fleet, iOS push | Token gauge; usage report | Worktree | Electron and iOS, MIT |
| Paradev (was Superset) | Sidebar working / done / waiting; activity strip | Plan review in chat; attention flag | Split diff, Viewed ticks, Create PR, review tab | Chimes, dock badge | ? | Worktree | Electron (macOS), ELv2 |
| Sculptor | Workspace tabs, agent tabs | Plan approval panel | Changes panel; PR button showing CI | Native question panels so notifications reach you | % context chip | Worktree (container experimental) | Desktop research preview, MIT |
| CloudCLI (claudecodeui) | Project / session sidebar | Allow once / Allow & remember / Deny | Git explorer; inline Edit diffs | Web push and desktop (action_required / stop / error) | Context gauge, cost modal | Worktree manager | npm web app (62 deps), AGPL |
| Claude Squad | TUI list with Preview / Diff tabs | — (experimental auto-yes) | Diff tab | — | — | Worktree and tmux | Go TUI, AGPL |
| CCManager | TUI project → worktree → session, `[active/busy/waiting]` | Experimental Haiku auto-approval | ± counts only | State-change hook commands | — | Worktree; devcontainer | npm TUI, MIT |
| cmux | Vertical tabs with latest notification text and unread badge | — (terminal) | — | Blue ring, notification panel, jump to unread | — | — | Native macOS terminal |
| Happy | Mobile session list | Phone answers permission prompts | Git changes view | Push for done / permission / question | ? | OS sandbox modes | Mobile, CLI relay, MIT |
| ccusage | — | — | — | — | Daily / session / 5-hour block, statusline | — | npm CLI, MIT |
| container-use | `list`, `watch` CLI | Human `merge` / `apply` | `diff`, `log` | — | — | Container and branch per agent | MCP server (low activity) |
| Claude Code | Agent view, Projects overview, `/workflows`, agent teams | Workflow approval card; teammate plan approval | Desktop diff with line comments, Create PR | Terminal / OS notifications; `Notification` hook | `/usage`, statusline cost, OTel, per-agent tokens in workflows | Worktree (`.claude/worktrees/`); cloud VM | CLI, Desktop, web |
| Copilot Agent HQ | Mission control across repos and vendors | Draft PR review | PR; session logs | VS Code badges | Premium requests | Cloud sandbox / Actions; app worktrees | GitHub, VS Code, app |
| Codex | App chats plus cloud tasks | — | Review pane with "Last turn" scope, per-hunk revert | ? | Per-thread $ (enterprise) | Worktree; cloud workspace | ChatGPT desktop, CLI, cloud |
| Cursor | Agents Window | ? | Diffs view; best-of-N | ? | Spend limit | Worktrees (max 25); cloud VMs | IDE, cloud |
| Antigravity | Agent Manager / 2.0 desktop | Plan comments then Proceed / Review | Word-level diff | Sounds, inbox | Token breakdown | ? | Desktop app |
| Devin | Sessions grouped Working / Ready / Blocked / Inactive | Optional batch approval of child sessions | PR tab with file tree | Notification inbox | ACUs | VM per session | Cloud |
| Factory | Mission Control overlay | Spec Mode approval | ? | ? | `/cost`, `/stats` | `--worktree` | CLI, cloud |
| Kiro | Spec task waves; Crew cards | Confirm each spec document | Markdown Review comments | ? | ? | ? | IDE, CLI, Web, Crew |
| Warp | Tab icons, child pill bar, runs page | Approval before children launch | Inline code review | Complete / Request / Error mailbox; **Claude Code plugin** | Credit caps | Cloud | Terminal app, Oz cloud |
| Ruflo | `/ruflo` console in Claude Code | Console ask mode; ADR diff approval | Diff before each write | Budget alerts | Per-agent USD, burn rate | Worktree per agent | CC plugin and npm CLI |
| BMAD (+ bmad-loop) | bmad-loop TUI | Open-question halt; approve / approve-and-stop | 4-layer review | — | Token budgets (loop) | Worktree per story (loop) | npm installer, skills |
| Spec Kit | — | review-spec and review-plan gates | `converge` gap tasks | — | — | Branch | Python CLI, skills |
| GSD Core | — | Discuss phase; UAT log | Verifier, code-reviewer | — | `actuals.tokens` per plan | Worktrees, parallel waves | npm, skills |
| superpowers | — | Plan review at handoff | Task and branch reviews | — | — | Worktrees skill | CC plugin (we adopt it) |

---

## 3. Competitors

### 3A. Dashboards over parallel agents (closest to us)

#### Conductor: the most complete, and shipping weekly
- **Status:** a Mac app ("not available for Windows or Linux yet"). 0.92.0 "Remote control" shipped 2026-10-23, and releases come roughly weekly ([changelog](https://www.conductor.build/changelog.md)).
  - Pricing: Free with local workspaces; Pro is $50/mo (cloud, API, mobile); Teams is $60/user ([llms-full](https://www.conductor.build/llms-full.txt)).
  - Supports Claude Code, Codex, Cursor and OpenCode. Isolation is a worktree per workspace, and the docs say "not a security boundary".
- **UI, sidebar** ([0.44](https://www.conductor.build/changelog/0.44.0-new-sidebar-rebuilt-composer-codex-checkpoints.md), [image](https://conductor-marketing.t3.tigrisfiles.io/uploads/1774395513472-image.png)):
  - Workspaces are grouped by repo.
  - Each row shows a PR-state icon, the title and `+N −M`.
  - Hovering a row shows a card with status ("In review"), author, age, `+693 −662`, the PR number and a next-action button ("Commit and push").
  - Clicking an already-selected workspace jumps to the oldest unread chat.
- **UI, more views:**
  - User-defined sections and an experimental "matrix-style" status indicator ([0.85](https://www.conductor.build/changelog/0.85.0-sections-routines-and-a-new-model-picker.md)).
  - A team Home with Pinned / Mine / Following / Team sections and presence dots ([llms-full](https://www.conductor.build/llms-full.txt)).
- **PR page** ([0.73](https://www.conductor.build/changelog/0.73.0-pr-page.md)): a PR tab beside the chats, a green Merge button, a Checks tab ("✗ 26/27"), and "Add to chat" on every review comment.
- **Diff and gates** ([llms-full](https://www.conductor.build/llms-full.txt)):
  - Diff viewer (⌘⇧D): line comments become attachments sent to the agent, GitHub threads show inline, and files can be reverted.
  - An agent `Review` action follows per-repo review preferences.
  - Workspaces stay blocked until their todos are checked off.
  - Plan Mode asks you to "approve it or give feedback".
- **Cost and notifications:**
  - The workspace details popover "rounds agent costs to cents" ([0.80](https://www.conductor.build/changelog/0.80.0-stacks.md)), and there is a context gauge ([0.92](https://www.conductor.build/changelog/0.92.0-remote-control.md)).
  - Completion sounds ([0.52](https://www.conductor.build/changelog/0.52.0-sounds-colors.md)), and "Workspace notifications now show the workspace name" ([0.77](https://www.conductor.build/changelog/0.77.0-early-access-multiplayer-api-background-tasks-performance.md)). Whether these are OS notifications is unverified.
- **We lack** ([llms-full](https://www.conductor.build/llms-full.txt)):
  - Per-repo `setup` / `run` / `archive` scripts with a per-workspace port range, and `.worktreeinclude` for gitignored files.
  - Checkpoints per turn, and archiving that keeps uncommitted work.
  - Creating a workspace from an issue, and an MCP server and API.
- **Gap they have and we fill:** "Conductor only supports automating testing one service at a time" ([llms-full](https://www.conductor.build/llms-full.txt)). Our multi-service waves cover this.
- **Borrow:** "The workspace is the unit of delegation. The branch and pull request are the unit of integration." Also a gitignored `.context/` folder for handoffs ([llms-full](https://www.conductor.build/llms-full.txt)).

#### Vibe Kanban: kanban plus workspace; the company has shut down
- **Status:**
  - bloop shut down on 2026-04-10. Remote services ended after 30 days, "local workspaces will continue to function", and the project is "open source and community maintained" ([shutdown](https://www.vibekanban.com/blog/shutdown)).
  - 28.5k stars, Apache-2.0. Last release v0.1.44 (2026-04-24), but commits continue into 2026-10 ([repo](https://github.com/BloopAI/vibe-kanban)).
  - Ships with `npx vibe-kanban`, binds to 127.0.0.1 by default, and uses a Rust backend.
- **Overview screenshot** ([image](https://github.com/BloopAI/vibe-kanban/blob/main/packages/public/vibe-kanban-screenshot-overview.png)):
  - A project rail on the left.
  - A board with To do / In progress / In review / Done columns, filter tabs Active / All / Backlog / Cancelled, and a "New Issue" button.
  - An in-progress card carries a nested workspace chip.
  - A right split pane streams that workspace: a setup-script empty state ("No setup script configured… [Configure]"), the agent's steps, and a composer with Queue / Stop.
- **Workspace screenshot** ([image](https://github.com/BloopAI/vibe-kanban/blob/main/packages/public/vibe-kanban-screenshot-workspace.png)): four panes. Workspace list (title, age, `4 +134 −2`) | chat with a "2 files changed +61 −3" bar | side-by-side diff | Git / Terminal / Notes.
- **Status display:**
  - Sidebar states are Running, Idle and "Needs Attention — Pending approval required" (raised-hand icon), plus a dev-server dot and a PR badge ([interface](https://vibekanban.com/docs/workspaces/interface.md)).
  - The accordion groups Needs Attention / Idle / Running. An empty group reads "No workspaces".
- **Diff and review:**
  - Comments on diff lines are batched and "submitted together when you send a message" ([reviewing](https://vibekanban.com/docs/reviewing-code.md)).
  - Plan approval is a card with **Approve** and **Request Changes**.
  - The context gauge goes grey, then default, then orange at 60%, then red at 80% ([chat](https://vibekanban.com/docs/workspaces/chat-interface.md)).
- **Notifications:** sounds on complete, attention and error, plus browser push ([settings](https://vibekanban.com/docs/settings/general.md)).
- **Borrow:** "Your issue description becomes the prompt", with a table of weak vs strong examples ([issues](https://vibekanban.com/docs/issue-management.md)). Also: deleting a workspace removes the worktree but keeps the branch ([managing](https://vibekanban.com/docs/workspaces/managing-workspaces.md)).

#### Nimbalyst (successor to Crystal)
- **Status:**
  - Crystal: "deprecated and replaced by Nimbalyst… February 2026" ([crystal](https://github.com/stravu/crystal/blob/main/README.md)).
  - Nimbalyst: MIT, 2.0k stars, v0.81.7 (2026-10-16). Electron app for Mac, Windows and Linux, plus iOS ([repo](https://github.com/nimbalyst/nimbalyst)).
- **Agent window screenshot** ([image](https://nimbalyst.com/docs/assets/docs-session-overview.png)):
  - Session list: "13 sessions", grouped under TODAY, each row with title, age and model, plus a Kanban button and tag search.
  - Centre: the transcript, with a turn footer "Finished in 13ms · 1 file".
  - Right panel: "All Session Edits", with the empty state "No files edited in this session" and a Commit box.
- **Status and attention** ([agent window](https://nimbalyst.com/docs/session-management/agent-window-and-session-management.md)):
  - An attention list grouped Awaiting input / Running / Unread, with a "9+" badge and the note that "Mark all read… does not approve requests" ([image](https://nimbalyst.com/docs/assets/agent-attention-list.png)).
  - A macOS menu-bar "session fleet" that flags a session which "has stopped responding". This is the same idea as our *stale*.
  - Session Kanban groups by phase: Backlog / Planning / Implementing / Validating / Complete. Hovering a card shows a live transcript peek.
- **Diff and review:** inline red/green with Keep or Revert. The docs admit "Reverting in the editor is not reported back to the agent session" ([diff approval](https://nimbalyst.com/docs/visual-editors-powered-by-ai/markdown-wysiwyg/ai-editing-red-green-diff-approval.md)).
- **Tokens:** an "18k/200k (9%)" gauge, and an AI Usage Report that is "separate from provider billing dashboards" ([usage](https://nimbalyst.com/docs/session-management/ai-usage-report.md)).
- **Borrow:**
  - Super Loops: fresh context each iteration, progress kept in files, and a maximum iteration count ([loops](https://nimbalyst.com/docs/developer-features/agent-teams-and-super-loops.md)).
  - Plan mode is limited to editing markdown.

#### Paradev (formerly Superset)
- **Status:** 15.7k stars, Elastic License 2.0, desktop-v2.0.2 (2026-10-29). macOS only; "Windows is not yet available" ([repo](https://github.com/ParadevAI/Paradev)). Free locally; Pro is $20/user ([pricing](https://paradev.com/pricing)).
- **Status display** ([agent status](https://docs.paradev.com/agent-status)):
  - The sidebar "shows which agent is working, done, or waiting on you".
  - An activity strip shows running agents and ports.
  - Agent chips appear only when more than one agent is in a workspace.
  - A manual "Clear Status" button fixes stale indicators.
  - Status comes from lifecycle hooks that do nothing outside Paradev terminals (an env-var guard).
- **Diff screenshot** ([image](https://github.com/ParadevAI/Paradev/blob/main/apps/marketing/public/images/readme/diff-viewer.png)):
  - Agent tabs Claude / Codex / OpenCode, and a split diff of `RevenueChart.tsx −3 +18` with a **Viewed** checkbox.
  - A right panel with Files / Changes / Review tabs, "3 files +131 −3", and per-file ± counts.
  - Focus mode steps one file at a time through Against base / Commits / Staged / Unstaged. Selected PR lines can be sent to an agent ([diff viewer](https://docs.paradev.com/diff-viewer)).
- **Notifications:** finish and needs-input sounds, plus a dock badge ([agent status](https://docs.paradev.com/agent-status)). Token or cost display is unverified.
- **Borrow:** the Viewed tick per file, a manual clear for stale state, and hooks that do nothing outside our environment.

#### Sculptor (Imbue)
- **Status:**
  - "Experimental research preview". MIT, 242 stars, v0.49.0 (2026-10-21) ([repo](https://github.com/imbue-ai/sculptor)). Pricing is unverified.
  - The repo docs give a git worktree as the default, with containers as an experimental backend ([workspaces](https://github.com/imbue-ai/sculptor/blob/main/docs/help/workspaces.md)). The product page still says "Every agent runs in its own container" ([site](https://imbue.com/sculptor/)), which looks stale.
- **Screenshot** ([image](https://github.com/imbue-ai/sculptor/blob/main/docs/help/images/changes_panel.png)):
  - A Files panel with Browse / Changes / Commits tabs.
  - A centre diff that collapses "28 unmodified lines", under a header "widget-store › main from main, +15 −0 · 2 files".
  - Chat on the right with a collapsed "9 Called Tools" row.
- **Gates and status:**
  - Plan mode waits for approval ([chat](https://github.com/imbue-ai/sculptor/blob/main/docs/help/chat.md)).
  - Sculptor replaces AskUserQuestion and ExitPlanMode with native panels "because calling them raises a notification that is more likely to reach you" ([harnesses](https://github.com/imbue-ai/sculptor/blob/main/docs/help/integrated_harnesses.md)).
  - A "% context" chip opens a token breakdown.
  - The PR button shows state, approvals, unresolved comments and CI ([PRs](https://github.com/imbue-ai/sculptor/blob/main/docs/help/pull_requests.md)).
- **Process (the closest to ours)** ([skills](https://github.com/imbue-ai/sculptor/blob/main/docs/help/skills.md)):
  - `sculptor-workflow` runs spec → mock → architect → plan → build → review.
  - Each stage is its own agent tab and writes a durable artifact keyed by a feature *slug*.
  - `build` re-reads each task file "so it doesn't drift" and commits per task.
  - `review` "doesn't fix anything".
- **We lack:** the CI Babysitter. It polls PR checks about every 30 s, then spawns a fixer agent, with a retry cap of 3, and "never merges or closes a PR itself" ([ci](https://github.com/imbue-ai/sculptor/blob/main/docs/help/ci_babysitter.md)).

#### CloudCLI (siteboon/claudecodeui)
- **Status:** 14.3k stars, AGPL-3.0, v1.37.6 (2026-10-27). Self-hosting is free; the cloud version is "€7/month" ([repo](https://github.com/siteboon/claudecodeui)).
- **Weight:** heavy, with 62 runtime dependencies including node-pty, sqlite and xterm ([package.json](https://github.com/siteboon/claudecodeui/blob/main/package.json)).
- **Desktop screenshot** ([image](https://github.com/siteboon/claudecodeui/blob/main/public/screenshots/desktop-main.png)):
  - A project-grouped session sidebar. Each row shows age and a message-count badge.
  - Chat / Shell / Files tabs, with tool calls drawn as blue cards and a green "Tool Result".
- **Mobile screenshot** ([image](https://github.com/siteboon/claudecodeui/blob/main/public/screenshots/mobile-chat.png)): inline red/green Edit diffs, a permission-mode pill, a "15.5%" context ring, and tabs Chat / Shell / Files / Git / Tasks.
- **Gates:** a banner with **Allow once / Allow & remember / Deny**. "Allow & remember" writes an allow rule ([banner](https://github.com/siteboon/claudecodeui/blob/main/src/modules/chat/composer/PermissionRequestsBanner.tsx)).
- **Notifications:** web push and desktop, of three kinds: `action_required`, `stop` and `error`. Each kind can be turned off, duplicates are suppressed for 20 s, and the title is the session name ([orchestrator](https://github.com/siteboon/claudecodeui/blob/main/server/modules/notifications/services/notification-orchestrator.service.js)).
- **Tokens:** a context summary that opens a cost modal, with cache tokens counted ([releases](https://github.com/siteboon/claudecodeui/releases)).

#### Claude Squad and CCManager (terminal managers)
- **Claude Squad:**
  - AGPL, 8.7k stars. v1.0.20 (2026-08-20) is also its last commit ([repo](https://github.com/smtg-ai/claude-squad)).
  - Screenshot: an Instances list (branch, `+48,−47`, a green dot) beside Preview / Diff tabs, with a key bar `n new · d kill · ↵ open · s submit PR` ([image](https://github.com/smtg-ai/claude-squad/blob/main/assets/screenshot.png)).
  - Status is a hash of the tmux pane: changed means Running, unchanged means Ready ([tmux.go](https://github.com/smtg-ai/claude-squad/blob/main/session/tmux/tmux.go)). It is a cheap way to detect staleness.
- **CCManager:**
  - MIT, v4.4.11 (2026-10-27) ([repo](https://github.com/kbwo/ccmanager)).
  - Sessions show Busy / Waiting / Idle, and projects show `[active/busy/waiting]` counts.
  - **State-change hooks run your shell command** with `CCMANAGER_OLD_STATE`, `CCMANAGER_NEW_STATE` and related env vars. The docs give `noti` and Slack as examples ([status-hooks](https://github.com/kbwo/ccmanager/blob/main/docs/status-hooks.md)).
  - On start it offers to restore previous sessions from a record written incrementally, so it survives a crash.

#### cmux, Happy, ccusage (added)
- **cmux:**
  - A native macOS terminal for agents. 28.6k stars, GPL-3.0 app, v0.65.2.2 (2026-10-27) ([repo](https://github.com/manaflow-ai/cmux)).
  - Screenshot: sidebar cards titled after the work, each with a blue unread badge, the latest notification line ("Claude is waiting for your input"), a PR link and the branch ([image](https://github.com/manaflow-ai/cmux/blob/main/docs/assets/main-first-image.png)).
  - Why it exists: Claude Code's own notification "is always just 'Claude is waiting for your input' with no context".
- **Happy:**
  - Mobile and desktop clients for Claude and Codex. MIT, 24.4k stars ([repo](https://github.com/slopus/happy)).
  - Three push kinds: done ("It's ready!"), permission and question. Each deep-links to the session ([pushNotifications.ts](https://github.com/slopus/happy/blob/main/packages/happy-cli/src/api/pushNotifications.ts)).
  - "Auto never falls back to silent execution" ([permissions](https://happy.engineering/permissions/)).
- **ccusage:**
  - MIT, 19.3k stars, v20.0.45 (2026-10-26). It reads local agent logs ([repo](https://github.com/ccusage/ccusage)).
  - Reports by day, session and 5-hour block, with `--json` and per-model breakdowns.
  - Screenshot: a table of Date / Agent / Models / Input / Output / Cache Create / Cache Read / Total Tokens / Cost (USD) ([image](https://cdn.jsdelivr.net/gh/ccusage/ccusage@main/docs/public/screenshot.png)).
  - The statusline shows session / today / block / burn rate ([statusline](https://ccusage.com/guide/statusline)).

#### Low activity, pivoted or dead (brief)
- **container-use (Dagger):**
  - An MCP server giving each agent a container and a branch, with CLI `list / log / diff / watch / merge / apply` ([README](https://github.com/dagger/container-use/blob/main/README.md), [CLI](https://container-use.com/cli-reference.md)).
  - Last release v0.4.2 (2025-08-19) ([releases](https://github.com/dagger/container-use/releases)).
  - Worth borrowing: "See complete command history and logs of what agents actually did, not just what they claim."
- **Omnara:** relaunched 2026-09-09 as an "open-source alternative to Claude Managed Agents" ([changelog](https://docs.omnara.com/changelog)). It is no longer a Claude Code command centre.
  - Gate pattern worth noting: a deny can carry a reason the model sees, and requests stay open with no timeout ([interactions](https://docs.omnara.com/events/interactions)).
- **opcode (was Claudia):**
  - Latest release v0.2.0 (2025-08-31); last code commit 2025-10-13 ([commits](https://github.com/winfunc/opcode/commits/main)).
  - It had a usage dashboard by model, project and date, and a checkpoint timeline with a diff viewer ([README](https://github.com/winfunc/opcode)).
- **Terragon:** "Terragon shutdown on February 9th, 2026" ([site](https://www.terragonlabs.com/)). An Apache-2.0 snapshot remains.
  - The screenshot shows a task list grouped Today / Yesterday / Older, with status, repo, branch and PR/CI glyphs on each row ([oss](https://github.com/terragon-labs/terragon-oss)).

### 3B. First-party agent surfaces

#### Claude Code (the platform we ship on)
- **Status:** v2.1.314, Oct 30, 2026 ([changelog](https://code.claude.com/docs/en/changelog.md)). The docs list five ways to run work in parallel: subagents, agent view (research preview), agent teams (experimental), Projects (beta) and dynamic workflows ([agents](https://code.claude.com/docs/en/agents.md)).
- **Agent view** ([agent view](https://code.claude.com/docs/en/agent-view.md)):
  - States: Working (animated), Needs input (yellow), Idle (dimmed), Completed (green), Failed (red) and Stopped (grey). Needs input and Ready for review sort above Working.
  - `claude agents --json` is the supported way to read state from outside; files under `~/.claude/jobs/` "are not a stable interface".
  - While the view is open, it sends notifications that fire the `Notification` hook (`agent_needs_input`, `agent_completed`).
  - Each background session gets a worktree under `.claude/worktrees/`.
  - The page shows no cost per session.
- **Projects:** an Overview grouped Ready for review / Waiting on you / Working / Landing / Idle / Resolved. Thread cards offer Fix CI, Address comments, Merge it and Create PR ([projects](https://code.claude.com/docs/en/claude-projects.md)).
- **Dynamic workflows** ([workflows](https://code.claude.com/docs/en/workflows.md)):
  - A JS script built from `agent()`, `pipeline()`, `parallel()` and `phase()`.
  - `/workflows` shows phases with agent counts and "each agent's token usage". An approval card lists the planned phases.
  - **Plugins can ship workflows** in `workflows/`, namespaced `/plugin:name`.
  - There is "No mid-run user input… For sign-off between stages, run each stage as its own workflow". Our finalize gate would therefore split one workflow into two.
- **Agent teams:** off by default. Coordination is file-based: inboxes at `~/.claude/teams/{team}/inboxes/`, a shared task list with dependencies, plan-approval requests to the lead, and `TaskCompleted` / `TeammateIdle` gate hooks. Costs are about 7x tokens in plan mode ([agent teams](https://code.claude.com/docs/en/agent-teams.md), [costs](https://code.claude.com/docs/en/costs.md)).
- **Subagents** ([sub-agents](https://code.claude.com/docs/en/sub-agents.md)):
  - `isolation: worktree` and persistent `memory` frontmatter.
  - Plugin subagents ignore `hooks`, `mcpServers` and `permissionMode`.
  - Transcripts are kept 30 days at `~/.claude/projects/{project}/{sessionId}/subagents/agent-{agentId}.jsonl`.
- **Hooks** ([hooks](https://code.claude.com/docs/en/hooks.md)):
  - 33 events, including SubagentStart/Stop, TaskCreated/Completed, Notification, WorktreeCreate/Remove and StopFailure.
  - Handler types include **`http`**, which POSTs the event JSON to a URL.
  - `SubagentStop` carries `agent_id`, `agent_type` and `last_assistant_message`. The `agent_transcript_path` field was reported by a research pass; the page was truncated before that section, so treat it as unverified.
- **Mods** ([mods](https://code.claude.com/docs/en/plugins/mods/overview.md)):
  - A plugin can now "draw an interface… a pane beside the transcript or a band above the prompt" in the CLI (v2.1.287+), Desktop and VS Code.
  - The built-in `/diff` is itself a mod. Cloud sessions and `-p` run the hooks but draw nothing.
- **Cost:**
  - The statusline JSON carries `cost.total_cost_usd` and lines added/removed. `subagentStatusLine` gets `tokenCount` per subagent, and a plugin can ship one ([statusline](https://code.claude.com/docs/en/statusline.md)).
  - OTel metrics `claude_code.cost.usage` and `token.usage` carry `agent.name` and `plugin.name` ([monitoring](https://code.claude.com/docs/en/monitoring-usage.md)).
- **Desktop:** a diff "file by file before creating a pull request", line comments, Create PR, and an OS notification when a session you are not viewing finishes ([desktop](https://code.claude.com/docs/en/desktop.md)).
- **Cloud:** "A cloud session… doesn't load the plugins in your local settings" ([plugins](https://code.claude.com/docs/en/plugins/overview.md)).

#### GitHub Copilot: coding agent and Agent HQ
- **Mission control:** "a single command center to assign, steer, and track the work of multiple agents" ([Agent HQ](https://github.blog/news-insights/company-news/welcome-home-agents/)).
- **Other vendors' agents:** Claude and Codex joined on 2026-02-04, and you can assign one issue to several agents "to compare their results" ([pick your agent](https://github.blog/news-insights/company-news/pick-your-agent-use-claude-and-codex-on-agent-hq/)).
- **Session logs:** these now collapse subagent work "with a heads-up display showing what it's working on right now" ([changelog](https://github.blog/changelog/2026-03-19-more-visibility-into-copilot-coding-agent-sessions/)).
- **VS Code Agents window:** badges for "new results, input requests, and pull request checks", plus "Mark as Done" ([Sep 2026](https://github.blog/changelog/2026-10-01-github-copilot-in-vs-code-september-2026-releases/)).
- **Copilot app:** a worktree per session ([preview](https://github.blog/changelog/2026-06-02-expanded-technical-preview-availability-for-the-github-copilot-app/)).

#### OpenAI Codex
- **Status:** the Codex app merged into the ChatGPT desktop app on July 9 ([what's new](https://learn.chatgpt.com/docs/whats-new)). CLI 0.165 added a repository filter and directory grouping to the "agent command center" ([changelog](https://learn.chatgpt.com/docs/changelog)).
- **Review pane:** Unstaged / Staged / Commit / Branch / **Last turn** views, with stage or revert per hunk ([review](https://learn.chatgpt.com/docs/code-review?surface=app)).
- **Worktrees:** a snapshot is taken before a worktree is deleted, and `.worktreeinclude` is honoured ([worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)).
- **Best-of-N:** `--attempts` 1–4 ([commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli)).

#### Cursor
- **Agents Window (3.0):** runs many agents across local, worktree, cloud and SSH, with `/best-of-n` ([3.0](https://cursor.com/changelog/3-0)).
- **Worktrees:** set up from `.cursor/worktrees.json`, with a cap of 25 ([worktrees](https://cursor.com/docs/configuration/worktrees)).
- **Cloud agents:** attach "Screenshots, videos, and logs" showing how they verified the work ([cloud](https://cursor.com/docs/cloud-agent)).
- Status, approval and notification UI in the Agents Window is undocumented on the pages read, so it is unverified.

#### Google Jules and Antigravity
- **Jules** "will wind down on December 31, 2026" ([changelog](https://jules.google/docs/changelog/)). One idea worth noting: a "Planning Critic" agent that reviews plans no human is asked to approve.
- **Antigravity:**
  - Artifacts (task list, implementation plan, walkthrough, screenshots) take "Google Docs-style comments" ([launch](https://antigravity.google/blog/introducing-google-antigravity)).
  - On the plan you comment, then choose **Proceed** or **Review** ([plan](https://antigravity.google/docs/implementation-plan/)).
  - 2.0 is a standalone desktop app ([2.0](https://antigravity.google/blog/introducing-google-antigravity-2/)).
  - `/teamwork` has a coordinator, workers, Critic / Challenger / Auditor roles, and a Success Auditor, and "Multiple workers never edit the same file at the same time" ([teamwork](https://antigravity.google/docs/teamwork/)).
  - Recent changes: completion sounds and a token breakdown ([changelog](https://antigravity.google/docs/changelog)).

#### Devin, Factory, Amp, Kiro, Warp (brief)
- **Devin** ([release notes](https://docs.devin.ai/release-notes/overview), [advanced](https://docs.devin.ai/work-with-devin/advanced-capabilities)):
  - Sessions grouped Working / Ready / Blocked / Inactive, a notification inbox (bell), and a file tree on the PR diff.
  - "Managed Devins" each run in their own VM. "Auto-approve child sessions" can be turned off to approve them in batches.
- **Factory:**
  - Missions break work into features, and "every milestone ends with a validation phase" ([missions](https://factory.com/news/missions)).
  - Spec Mode saves to `.factory/docs/YYYY-MM-DD-slug.md` ([spec mode](https://docs.factory.com/cli/user-guides/specification-mode)).
  - `/cost` and `/stats`, and Ctrl+T toggles the Mission Control overlay ([CLI](https://docs.factory.com/reference/cli-reference)).
- **Amp:** threads run on "orbs" (machines) and notify you "when a thread is ready" ([manual](https://ampcode.com/manual)). Puck is an assistant that "keeps track of" your agents ([puck](https://ampcode.com/docs/puck)).
- **Kiro:**
  - Specs are `requirements.md` (EARS: "WHEN … THE SYSTEM SHALL …"), `design.md` and `tasks.md`.
  - Run-all "groups tasks into waves", the same idea as our dependency waves ([specs](https://kiro.dev/docs/specs/), [requirements](https://kiro.dev/docs/specs/feature-specs/requirements-first/)).
  - Kiro Crew is an open-source workspace with one card per agent ([crew](https://kiro.dev/blog/introducing-kiro-crew/)).
- **Warp:**
  - Notifications are Complete / Request / Error, with tab badges and a mailbox filtered All / Unread / Errors.
  - **Claude Code has "full support via notification plugin"** ([notifications](https://docs.warp.dev/agent-platform/local-agents/agent-notifications)).
  - "Approval is required before the parent launches children" ([orchestration](https://docs.warp.dev/platform/orchestration/)).

### 3C. Plugin and skill packs for orchestration and process

#### obra/superpowers (we depend on it)
- **Versions:**
  - 308.8k stars, MIT. Releases since our pin: v6.4.2 (09-25), v7.0.0 (10-10), v7.0.1 (10-21) ([releases](https://github.com/obra/superpowers/releases)).
  - The official marketplace serves 7.0.0 ([marketplace.json](https://github.com/anthropics/claude-plugins-official/blob/main/.claude-plugin/marketplace.json)).
- **Skills:** the same 15 at v6.4.1 and v7.0.1 ([6.4.1](https://github.com/obra/superpowers/tree/v6.4.1/skills), [7.0.1](https://github.com/obra/superpowers/tree/v7.0.1/skills)).
- **Changes to skills we bind:**
  - Modified: `writing-plans`, `executing-plans`, `subagent-driven-development` and `systematic-debugging` (example only).
  - Unchanged: TDD, receiving-code-review, verification-before-completion and finishing-a-development-branch ([compare](https://github.com/obra/superpowers/compare/v6.4.1...v7.0.1)).
- **`writing-plans` (v6.4.2):**
  - A plan "records decisions"; steps are "one action with a checkable result".
  - A new self-review check, "Proportion", compares the plan's length to the spec's.
  - Plans carry `Review Focus` and per-task `Interfaces: Consumes / Produces` ([SKILL](https://github.com/obra/superpowers/blob/v7.0.1/skills/writing-plans/SKILL.md)).
  - Its Execution Handoff and its default save path must keep being overridden by our gate and bus.
- **v7.0.1 and compaction:** "After a compaction, Claude Code re-attaches each skill cut off at 20,000 characters". One session lost its five-round cap and "ran 18 fix rounds" ([release notes](https://github.com/obra/superpowers/blob/main/RELEASE-NOTES.md)).
  - Our largest skill is 9,922 B, but `docs/orchestration-runbook.md` is 21,286 B. It is read as a file, not as a skill, so the 20k rule does not apply directly, but the same risk of losing rules after compaction does.
- **SDD fix loop:**
  - Max 5 rounds. Rounds 4–5 go to a fresh implementer "on a more capable model".
  - "Minor" findings never enter the loop.
  - Decisions are logged as `Ruling: <what> — <why> — <cost if wrong>`.
  - "Never dispatch multiple implementation subagents in parallel", which we deliberately diverge from by isolating in worktrees ([SDD](https://github.com/obra/superpowers/blob/v7.0.1/skills/subagent-driven-development/SKILL.md), [fix-loop](https://github.com/obra/superpowers/blob/v7.0.1/skills/subagent-driven-development/references/fix-loop.md)).

#### wshobson/agents, including `ship-mate` (a direct competitor)
- **Status:** 42k stars, MIT. 94 plugins and 202 agents ([README](https://github.com/wshobson/agents/blob/main/README.md)).
- **`ship-mate` v1.0.1** ([ship.md](https://github.com/wshobson/agents/blob/main/plugins/ship-mate/commands/ship.md)):
  - Usage: `/ship stories/foo.md | status | resume`. State lives in `.claude/pipeline/state.json`.
  - Stages: scan → orchestrate → architect → **PAUSE for human** → implement → review → qa → Playwright (frontend only).
  - Tasks run one at a time.
  - A 🔴 Critical finding pauses the run, and QA failing twice escalates to the human. It has "No Cyclic Handoff" and "Two-Handoff Rule" anti-loop rules.
  - Review has three tiers ([review](https://github.com/wshobson/agents/blob/main/plugins/ship-mate/agents/review.md)).
  - The story template is As a… / Given-When-Then / `- [ ]` tasks ([template](https://github.com/wshobson/agents/blob/main/plugins/ship-mate/stories/_template.md)).
- **`/full-stack-feature`:** "Read from prior step files -- do NOT rely on context window memory", with two phase checkpoints ([command](https://github.com/wshobson/agents/blob/main/plugins/full-stack-orchestration/commands/full-stack-feature.md)).
- **`conductor` plugin:** git-aware "semantic revert" by track, phase or task ([README](https://github.com/wshobson/agents/blob/main/plugins/conductor/README.md)).
- **No dashboard or cost tracking was found.**

#### Ruflo (formerly claude-flow)
- **Status:** "Claude Flow is now Ruflo". 80.2k stars, MIT, v3.65.0 (2026-10-30), with several releases a day ([README](https://github.com/ruvnet/ruflo/blob/main/README.md)).
- **Console:** `/ruflo` is a console inside Claude Code that "Track[s] workflows, agents, models, tokens and cost". Its "Room" shows what is "waiting for a yes", and every write shows a diff before the Yes ([console](https://github.com/ruvnet/ruflo/blob/main/plugins/ruflo-console/README.md)).
- **Cost tracker:** a Stop hook parses the Claude Code jsonl, attributes USD per agent and model, and has a budget ladder at 50 / 75 / 90 / 100% with a hard stop at 100% ([cost-tracker](https://github.com/ruvnet/ruflo/blob/main/plugins/ruflo-cost-tracker/README.md)).
- **SPARC:** machine gates such as "≥3 acceptance criteria", and a traceability report ([sparc](https://github.com/ruvnet/ruflo/blob/main/plugins/ruflo-sparc/README.md)).
- **Scale:** hundreds of tools plus a daemon, the opposite of our minimal bus. The README's download badge is labelled "Illustrative".

#### BMAD-METHOD
- **Status:** 54.8k stars. Stable v6.12.4 (2026-10-14). v7 was in alpha with an ETA of 2026-10-16, but no v7 tag exists ([README](https://github.com/bmad-code-org/BMAD-METHOD/blob/main/README.md), [tags](https://github.com/bmad-code-org/BMAD-METHOD/tags)).
- **Roster:** Analyst, PM, Architect, UX and Dev ("File paths and AC IDs are your vocabulary") ([dev](https://github.com/bmad-code-org/BMAD-METHOD/blob/V6.12/src/bmm-skills/agents/bmad-agent-dev/SKILL.md)).
- **Spec template** ([spec](https://github.com/bmad-code-org/BMAD-METHOD/blob/V6.12/src/bmm-skills/ship/bmad-build/spec-template.md)):
  - A `<frozen-after-approval>` block holding Intent, Boundaries (Always / Never) and an I/O & edge-case matrix.
  - Append-only Spec Change Log and Review Triage Log sections.
  - Target size "900–1300 tokens. Above 1600 = high risk of context rot".
- **Gate:** "Approve and continue / Approve and stop / Review spec", and the spec is re-read from disk on approval ([step-02](https://github.com/bmad-code-org/BMAD-METHOD/blob/V6.12/src/bmm-skills/ship/bmad-build/step-02-plan.md)).
- **Review:** four parallel layers (Blind Hunter, Edge Case Hunter, Verification Gap, Acceptance Auditor) ([review](https://github.com/bmad-code-org/BMAD-METHOD/blob/V6.12/src/bmm-skills/ship/bmad-code-review/customize.toml)). Findings are triaged into intent_gap (revert, back to the human), bad_spec (amend, re-derive), patch, or defer to `deferred-work.md`.
- **bmad-loop:** "Plain Python drives the loop… No LLM in the control loop", with one board writer and a TUI dashboard ([bmad-loop](https://github.com/bmad-code-org/bmad-loop/blob/main/README.md)). This is our pipe.py idea, independently arrived at.

#### GitHub Spec Kit
- **Status:** 144k stars, MIT, v1.2.5 (2026-10-28) ([release](https://github.com/github/spec-kit/releases/tag/v1.2.5)).
- **Flow:** `/speckit-constitution → specify → plan → tasks → implement → converge`, repeating implement and converge "until convergence reports `Converged`" ([README](https://github.com/github/spec-kit/blob/main/README.md)).
- **Spec:** user stories P1–P3, each with an "Independent Test"; `FR-###` and `SC-###` IDs; `[NEEDS CLARIFICATION]` markers ([spec](https://github.com/github/spec-kit/blob/main/templates/spec-template.md)).
- **Plan:** a "Constitution Check — GATE" ([plan](https://github.com/github/spec-kit/blob/main/templates/plan-template.md)).
- **Tasks:** written as `T012 [P] [US1] …`, and "Tests are OPTIONAL", which is the opposite of our mandatory tester ([tasks](https://github.com/github/spec-kit/blob/main/templates/tasks-template.md)).
- **converge:** appends gap tasks, "APPEND-ONLY, NEVER REWRITE" ([converge](https://github.com/github/spec-kit/blob/main/templates/commands/converge.md)).
- **Gates:** the workflow YAML has review-spec and review-plan gates ([workflow.yml](https://github.com/github/spec-kit/blob/main/workflows/speckit/workflow.yml)).

#### GSD Core (formerly get-shit-done)
- **Status:** gsd-build/get-shit-done is archived; "GSD Has Moved" ([README](https://github.com/gsd-build/get-shit-done/blob/main/README.md)). GSD Core is MIT, 11k stars, v1.19.0 (2026-10-26) ([repo](https://github.com/open-gsd/gsd-core)).
- **Phase loop:** Discuss → Plan (with a plan-checker) → Execute (parallel waves, "fresh 200k-token context" per executor) → Verify → Ship ([phase loop](https://github.com/open-gsd/gsd-core/blob/next/docs/explanation/the-phase-loop.md)).
- **Context:** "The orchestrator… never touches source files", and `STATE.md` is the first file every agent reads ([context](https://github.com/open-gsd/gsd-core/blob/next/docs/explanation/context-engineering.md)).
- **Plan format:** `PLAN.md` frontmatter carries `must_haves` (truths / artifacts / key_links), which the verifier checks. `SUMMARY.md` records `actuals: {tokens, tasks, commits}` ([artifacts](https://github.com/open-gsd/gsd-core/blob/next/docs/reference/planning-artifacts.md)).
- **Agents:** the roster includes a `gsd-mempalace-curator` ([agents](https://github.com/open-gsd/gsd-core/tree/next/agents)).

#### Anthropic official plugins (added)
- **Status:** 45.3k stars ([repo](https://github.com/anthropics/claude-plugins-official)).
- **`feature-dev`:**
  - Seven phases: 2–3 parallel explorers, then "DO NOT SKIP" clarifying questions, then 2–3 architects (minimal / clean / pragmatic) from which the user picks.
  - Then "DO NOT START WITHOUT USER APPROVAL", then three parallel reviewers.
  - It has no tester and no worktrees ([feature-dev](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/feature-dev/commands/feature-dev.md)).
- **`code-review`:** four parallel reviewers, then **a validation subagent per candidate issue**, with unvalidated issues dropped ([code-review](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/code-review/commands/code-review.md)).
- **`session-report`:** an HTML report of "tokens, cache, subagents, skills, expensive prompts" built from `~/.claude/projects` ([session-report](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/session-report/skills/session-report/SKILL.md)).

#### Smaller or quieter packs (brief)
- **ccpm:**
  - "Issue state is project state. Comments are the audit trail".
  - Tasks carry `depends_on / parallel / conflicts_with`.
  - It runs several agents in one worktree per epic, and "Conflicts are never auto-resolved".
  - Last substantive commit 2026-03-18 ([README](https://github.com/automazeio/ccpm/blob/main/README.md), [conventions](https://github.com/automazeio/ccpm/blob/main/skill/ccpm/references/conventions.md)).
- **Taskmaster AI:**
  - License is MIT plus Commons Clause. Last release 2026-03-31.
  - Its TDD validator rejects a RED phase with no failing test and checks total = passed + failed + skipped ([validator](https://github.com/eyaltoledano/claude-task-master/blob/main/packages/tm-core/src/modules/workflow/services/test-result-validator.ts)).
- **SuperClaude:** v4.3.0 (2026-03-22). The self-review agent asks four mandatory questions, including "tests executed with command and outcome?" ([self-review](https://github.com/SuperClaude-Org/SuperClaude_Framework/blob/master/plugins/superclaude/agents/self-review.md)).
- **ECC:**
  - 292.9k stars. `orch-pipeline` first classifies a change as trivial / small / standard / large, which decides which phases run, and is "gated, not autonomous" ([orch-pipeline](https://github.com/affaan-m/ECC/blob/main/skills/orch-pipeline/SKILL.md)).
  - v2.0 added "deterministic conflict prediction" across parallel worktrees ([2.0.0](https://github.com/affaan-m/ECC/blob/main/docs/releases/2.0.0/release-notes.md)).
- **oh-my-claudecode:** 40.4k stars. Team pipeline `team-plan → team-prd → team-exec → team-verify → team-fix`, a live HUD, and replayable per-agent jsonl logs ([README](https://github.com/Yeachan-Heo/oh-my-claudecode/blob/main/README.md)).
- **Compound Engineering:**
  - 25.8k stars. `ce-code-review` selects personas from the diff, is report-only by default, and reads a repo `REVIEW.md` policy ([ce-code-review](https://github.com/EveryInc/compound-engineering-plugin/blob/main/docs/guides/ce-code-review.md)).
  - `/ce-compound` captures what was learned ([ce-compound](https://github.com/EveryInc/compound-engineering-plugin/blob/main/docs/guides/ce-compound.md)).
- **OpenSpec:** 73.4k stars. `/opsx:propose|apply|archive`, and "Stores" for cross-repo features ([README](https://github.com/Fission-AI/OpenSpec/blob/main/README.md)). Not deep-dived.

---

## 4. Ranked recommendations for us

Constraints: **lightweight · zero npm dependencies · localhost only · the UI never spawns processes.** Fit says
whether an idea keeps all four; ⚠ marks one that would break a constraint or reverse a recorded decision.

### UI improvements

| # | Idea (evidence) | Value | Effort | Fit |
|---|---|---|---|---|
| U1 | **Attention signals.** On a card entering gate / stale / failed / done: a browser `Notification` with context ("svcA · finalize gate waiting"), a `document.title` count ("(2) need you"), a favicon dot. Permission is asked from a click (MDN). Evidence: agent view, cmux, Vibe Kanban, CloudCLI, Happy, Warp. | High. Every close dashboard has this, and a gate nobody notices costs wall-clock. | S | Full. Browser API only, and 127.0.0.1 is a secure context. |
| U2 | **Read-only diff on the board.** Serve the existing `code/diff.patch` per service: file list with ± counts, unified view, "Viewed" ticks in `localStorage`, reviewer findings (file:line from `review.json`) pinned to lines. Evidence: Conductor, Paradev, Sculptor, Vibe Kanban, Codex "Last turn". | High. Today the change can only be seen outside the dashboard. | M | Full. The server reads a file it already has, with no git spawn. Hand-rolled patch parser, about 60 lines. |
| U3 | **Last event line and unread count on each hall card.** The newest `messages.jsonl` summary under the title, plus an unread badge since the last visit. Evidence: cmux, Conductor (jump to oldest unread), Nimbalyst attention list. | Medium. We already sort by urgency (`URGENCY` in `ui/hall.html`); this adds the why. | S | Full. |
| U4 | **Plan on the gate card.** Show `plan.md` and the AC list inline when a card is at gate, so approval happens beside the plan. Evidence: Antigravity (comment, then Proceed / Review), Vibe Kanban, CloudCLI PlanDisplay. | Medium | S | Full. Read-only. |
| U5 | **Tokens per run, service and agent on the board and cards.** Display only; the data comes from F3. Evidence: Conductor cents, `/workflows` per-agent tokens, ccusage columns. | Medium-high | S, after F3 | Full |
| U6 | **Transcript peek per seat.** Click an agent and read its subagent transcript read-only. Evidence: Nimbalyst live peek, Copilot session logs, `/workflows` drill-down. | Medium | M | ⚠ The server must read outside the pipelines root (`~/.claude/projects/…`). Keep §14's rule: take the path from a bus record written by F3, never from the URL. |
| U7 | **"Reject with reason" at the gate.** The reason is fed back to the planner. Evidence: Omnara, Vibe Kanban "Request Changes", Antigravity comments. | Medium | S | ⚠ This reverses spec §14's "no free-form input" on `/api/gate`. Alternative within constraints: keep the reason in the terminal reply and show it read-only. |
| U8 | **PR / CI chips on cards.** Evidence: Conductor, Paradev, cmux, Sculptor. | Medium | M | ⚠ Needs `gh`, which means spawning, and PR creation is out of scope (spec §15). Only possible if `pipe.py finish` records PR state on the bus. |

### New features

| # | Idea (evidence) | Value | Effort | Fit |
|---|---|---|---|---|
| F1 | **Re-read superpowers 7.0.1 and bump the 6.4.1 pin.** Check the four changed skills against our bindings (writing-plans most). Note that the official marketplace serves 7.0.0. | High. Our planner's method changed upstream two releases ago. | S | Full. ADR-0002 already prescribes this. |
| F2 | **Validate before blocking.** The reviewer runs a short check per `blocking` / `major` finding and drops the unconfirmed ones. Route them like BMAD: patch, defer (to a `deferred.md` on the bus), or back to the human. Optional `REVIEW.md` repo policy. Evidence: Anthropic code-review, BMAD, Compound Engineering, ship-mate tiers. | High. Each false blocker burns one of five iterations. | M | Full. Prompt plus the `pipe.py review` schema. |
| F3 | **Token capture without UI spawning.** Ship a plugin `hooks/hooks.json` `SubagentStop` **command** hook that calls `pipe.py` to append the agent's token totals (read from its transcript) to the bus. Claude Code runs it, not the UI. Evidence: Ruflo cost-tracker, session-report, statusline `cost.*`. Tokens only; skip a dollar price table until asked. | Medium-high | M | Full. Confirm first that the hook input carries the transcript path and that transcripts carry usage (both unverified here). |
| F4 | **Gate and stale notifications outside the browser.** `pipe.py` runs a user-configured shell command on state change, with env vars, as CCManager does. Pairs with Warp's Claude Code notification plugin and terminal notifiers. | Medium | S | Full. `pipe.py` already runs in agent processes. |
| F5 | **Plan format upgrades.** Stable AC IDs used everywhere (Spec Kit FR/SC, Kiro EARS). Per-task `Interfaces` and a `Review Focus` that feeds the tester's negative cases (superpowers). `conflicts_with` per task (ccpm) to warn before a wave. A frozen-after-approval marker (BMAD). | Medium | S–M | Full. `validate-plan` already exists in `pipe.py`. |
| F6 | **Learning capture at done.** One short "what we learned" record per run, stored as a codebase-memory ADR the planner already queries. Evidence: Compound Engineering, Devin knowledge suggestions, GSD's mempalace curator. | Medium | M | Full. Reuses the existing MCP. |
| F7 | **Worktree setup.** Add a `setup` command and a copy-ignored-files list (`.worktreeinclude`) to the service registry. Evidence: Conductor, Vibe Kanban, CCManager, Cursor, Codex all converge on `.worktreeinclude`. | Medium. New worktrees often lack `.env`. | S | Full |
| F8 | **Size triage.** Let `/ship` skip phases for trivial changes. Evidence: ECC orch-pipeline, BMAD oneshot, Kiro Quick Spec. | Medium | S–M | Full. Gates stay for anything above trivial. |
| F9 | **Runbook under 20k.** Move fix-loop and multi-service rules into reference files read at the step, as superpowers 7.0.1 did. The runbook is 21,286 B. | Medium | S | Full |
| F10 | **Decide naming.** Act on the `agent-orchestration` and `/ship` collisions in wshobson/agents before wider publishing. | Medium | S | Full |
| F11 | **Ingest Claude Code `http` hooks directly** (SubagentStart/Stop, Notification) instead of polling the bus. | Low-medium | M | ⚠ Adds a third write route to the server, beyond the gate and hide. F3's command-hook route gives the same data without it. |
| F12 | **Ship the pipeline as a plugin workflow** (`workflows/`), getting `/workflows` progress and per-agent tokens for free. | Strategic | L | ⚠ Workflows have "no mid-run user input", so the finalize gate means two workflows. Large rewrite; revisit if agent view or workflows become stable. |
| F13 | **A mod pane** showing the hall inside the Claude Code session. | Strategic | L | ⚠ A second UI to keep in sync, and mods can spawn processes (we would choose not to). |
| — | Not recommended now: best-of-N attempts (Copilot, Codex, Cursor), mobile or remote access (Conductor iOS, Happy), cloud sandboxes, CI babysitter. | — | L | ⚠ Each needs spawning, a network beyond localhost, or PR scope that §15 defers. |

**Order to build:** F1 → U1 → F9 → U3 → U2 → F2 → F3 + U5 → F7 → F5. The first four are size S. None of the nine
adds a write route to the server.

---

## 5. Sources

All read on 2026-10-30. GitHub repo metadata comes from `gh api repos/<owner>/<repo>` on the same day.

- **Ours:** `README.md`, `CONTEXT.md`, `skills/ship/SKILL.md`, `agents/*.md`, `docs/adr/0002-framework-adoption.md`, `docs/specs/2026-09-18-multi-pipeline-engine.md` (§10.6–10.8, §14, §15), `ui/hall.html`, `ui/board.html`, `ui/server.js`, `scripts/test_pipe.py`
- **Conductor:**
  - https://www.conductor.build/llms.txt · https://www.conductor.build/llms-full.txt · https://www.conductor.build/changelog.md
  - Changelog entries: https://www.conductor.build/changelog/0.92.0-remote-control.md · https://www.conductor.build/changelog/0.85.0-sections-routines-and-a-new-model-picker.md · https://www.conductor.build/changelog/0.83.0-auto-port-forwarding.md · https://www.conductor.build/changelog/0.80.0-stacks.md · https://www.conductor.build/changelog/0.77.0-early-access-multiplayer-api-background-tasks-performance.md · https://www.conductor.build/changelog/0.73.0-pr-page.md · https://www.conductor.build/changelog/0.63.0-cursor-support-dispatcher.md · https://www.conductor.build/changelog/0.62.0-repo-settings-browser-preview.md · https://www.conductor.build/changelog/0.54.0-new-queue-diff-diffs.md · https://www.conductor.build/changelog/0.52.0-sounds-colors.md · https://www.conductor.build/changelog/0.44.0-new-sidebar-rebuilt-composer-codex-checkpoints.md · https://www.conductor.build/changelog/0.41.0-tool-approval-codex-plan-mode-beta.md
  - Images: https://conductor-marketing.t3.tigrisfiles.io/uploads/1774395513472-image.png · https://www.conductor.build/changelog/pr-page-0.73.0.png
- **Vibe Kanban:**
  - https://github.com/BloopAI/vibe-kanban · https://github.com/BloopAI/vibe-kanban/blob/main/README.md · https://github.com/BloopAI/vibe-kanban/releases · https://www.vibekanban.com/blog/shutdown
  - Images: https://github.com/BloopAI/vibe-kanban/blob/main/packages/public/vibe-kanban-screenshot-overview.png · https://github.com/BloopAI/vibe-kanban/blob/main/packages/public/vibe-kanban-screenshot-workspace.png · https://mintcdn.com/vibekanban/QA35mU65cg2kMRzj/images/workspaces-sidebar-accordion.png
  - Docs: https://vibekanban.com/docs/llms.txt · https://vibekanban.com/docs/workspaces/interface.md · https://vibekanban.com/docs/workspaces/changes.md · https://vibekanban.com/docs/reviewing-code.md · https://vibekanban.com/docs/workspaces/chat-interface.md · https://vibekanban.com/docs/workspaces/git-operations.md · https://vibekanban.com/docs/settings/general.md · https://vibekanban.com/docs/settings/projects-repositories.md · https://vibekanban.com/docs/browser-testing.md · https://vibekanban.com/docs/remote-access.md · https://vibekanban.com/docs/integrations/vibe-kanban-mcp-server.md · https://vibekanban.com/docs/workspaces/managing-workspaces.md · https://vibekanban.com/docs/issue-management.md
- **Crystal / Nimbalyst:**
  - https://github.com/stravu/crystal/blob/main/README.md · https://github.com/nimbalyst/nimbalyst · https://github.com/nimbalyst/nimbalyst/blob/main/README.md · https://nimbalyst.com/llms.txt
  - Docs: https://nimbalyst.com/docs/session-management/agent-window-and-session-management.md · https://nimbalyst.com/docs/visual-editors-powered-by-ai/markdown-wysiwyg/ai-editing-red-green-diff-approval.md · https://nimbalyst.com/docs/session-management/ai-usage-report.md · https://nimbalyst.com/docs/developer-features/worktrees.md · https://nimbalyst.com/docs/developer-features/pull-request-reviews.md · https://nimbalyst.com/docs/developer-features/agent-teams-and-super-loops.md · https://nimbalyst.com/docs/mobile/mobile-app.md
  - Images: https://nimbalyst.com/docs/assets/docs-session-overview.png · https://nimbalyst.com/docs/assets/agent-attention-list.png
- **Paradev:** https://github.com/ParadevAI/Paradev · https://github.com/ParadevAI/Paradev/blob/main/apps/marketing/public/images/readme/diff-viewer.png · https://docs.paradev.com/agent-status · https://docs.paradev.com/agent-integration · https://docs.paradev.com/diff-viewer · https://paradev.com/pricing
- **Sculptor:**
  - https://github.com/imbue-ai/sculptor · https://github.com/imbue-ai/sculptor/blob/main/README.md · https://imbue.com/sculptor/
  - Help docs: https://github.com/imbue-ai/sculptor/blob/main/docs/help/workspaces.md · https://github.com/imbue-ai/sculptor/blob/main/docs/help/chat.md · https://github.com/imbue-ai/sculptor/blob/main/docs/help/changes.md · https://github.com/imbue-ai/sculptor/blob/main/docs/help/pull_requests.md · https://github.com/imbue-ai/sculptor/blob/main/docs/help/ci_babysitter.md · https://github.com/imbue-ai/sculptor/blob/main/docs/help/skills.md · https://github.com/imbue-ai/sculptor/blob/main/docs/help/integrated_harnesses.md · https://github.com/imbue-ai/sculptor/blob/main/docs/help/experimental/container_backend.md
  - Image: https://github.com/imbue-ai/sculptor/blob/main/docs/help/images/changes_panel.png
- **CloudCLI:** https://github.com/siteboon/claudecodeui · https://github.com/siteboon/claudecodeui/releases · https://github.com/siteboon/claudecodeui/blob/main/package.json · https://github.com/siteboon/claudecodeui/blob/main/public/screenshots/desktop-main.png · https://github.com/siteboon/claudecodeui/blob/main/public/screenshots/mobile-chat.png · https://github.com/siteboon/claudecodeui/blob/main/src/modules/chat/composer/PermissionRequestsBanner.tsx · https://github.com/siteboon/claudecodeui/blob/main/server/modules/notifications/services/notification-orchestrator.service.js · https://cloudcli.ai/docs/features/git-explorer · https://cloudcli.ai/docs/features/session-management
- **Claude Squad:** https://github.com/smtg-ai/claude-squad · https://github.com/smtg-ai/claude-squad/blob/main/README.md · https://github.com/smtg-ai/claude-squad/blob/main/assets/screenshot.png · https://github.com/smtg-ai/claude-squad/blob/main/session/tmux/tmux.go
- **CCManager:** https://github.com/kbwo/ccmanager · https://github.com/kbwo/ccmanager/blob/main/docs/status-hooks.md · https://github.com/kbwo/ccmanager/blob/main/docs/auto-approval.md
- **cmux:** https://github.com/manaflow-ai/cmux · https://github.com/manaflow-ai/cmux/blob/main/docs/assets/main-first-image.png · https://github.com/manaflow-ai/cmux/blob/main/docs/assets/sidebar-notification-badge.png
- **Happy:** https://github.com/slopus/happy · https://github.com/slopus/happy/blob/main/packages/happy-cli/src/api/pushNotifications.ts · https://happy.engineering/ · https://happy.engineering/mobile/ · https://happy.engineering/permissions/
- **ccusage:** https://github.com/ccusage/ccusage · https://cdn.jsdelivr.net/gh/ccusage/ccusage@main/docs/public/screenshot.png · https://ccusage.com/guide/statusline
- **container-use, Omnara, opcode, Terragon:**
  - container-use: https://github.com/dagger/container-use/blob/main/README.md · https://github.com/dagger/container-use/releases · https://container-use.com/cli-reference.md · https://container-use.com/environment-workflow.md
  - Omnara: https://github.com/omnara-ai/omnara · https://docs.omnara.com/changelog · https://docs.omnara.com/events/interactions
  - opcode: https://github.com/winfunc/opcode · https://github.com/winfunc/opcode/commits/main
  - Terragon: https://www.terragonlabs.com/ · https://github.com/terragon-labs/terragon-oss
- **Claude Code:** https://code.claude.com/docs/en/changelog.md · https://code.claude.com/docs/en/agents.md · https://code.claude.com/docs/en/agent-view.md · https://code.claude.com/docs/en/claude-projects.md · https://code.claude.com/docs/en/workflows.md · https://code.claude.com/docs/en/agent-teams.md · https://code.claude.com/docs/en/costs.md · https://code.claude.com/docs/en/sub-agents.md · https://code.claude.com/docs/en/hooks.md · https://code.claude.com/docs/en/plugins/mods/overview.md · https://code.claude.com/docs/en/statusline.md · https://code.claude.com/docs/en/monitoring-usage.md · https://code.claude.com/docs/en/desktop.md · https://code.claude.com/docs/en/claude-code-on-the-web.md · https://code.claude.com/docs/en/plugins/overview.md · https://code.claude.com/docs/en/remote-control.md
- **GitHub:** https://github.blog/news-insights/company-news/welcome-home-agents/ · https://github.blog/news-insights/company-news/pick-your-agent-use-claude-and-codex-on-agent-hq/ · https://github.blog/ai-and-ml/github-copilot/how-to-orchestrate-agents-using-mission-control/ · https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent · https://github.blog/changelog/2026-03-19-more-visibility-into-copilot-coding-agent-sessions/ · https://github.blog/changelog/2026-06-02-expanded-technical-preview-availability-for-the-github-copilot-app/ · https://github.blog/changelog/2026-10-01-github-copilot-in-vs-code-september-2026-releases/
- **Codex:** https://learn.chatgpt.com/docs/whats-new · https://learn.chatgpt.com/docs/changelog · https://learn.chatgpt.com/docs/cloud · https://learn.chatgpt.com/docs/developer-commands?surface=cli · https://learn.chatgpt.com/docs/environments/git-worktrees · https://learn.chatgpt.com/docs/code-review?surface=app
- **Cursor:** https://cursor.com/changelog · https://cursor.com/changelog/3-0 · https://cursor.com/docs/agent/agents-window · https://cursor.com/docs/configuration/worktrees · https://cursor.com/docs/cloud-agent
- **Google:** https://jules.google/docs/ · https://jules.google/docs/changelog/ · https://antigravity.google/blog/introducing-google-antigravity · https://antigravity.google/blog/introducing-google-antigravity-2/ · https://antigravity.google/docs/implementation-plan/ · https://antigravity.google/docs/teamwork/ · https://antigravity.google/docs/changelog
- **Devin, Factory, Amp, Kiro, Warp:**
  - Devin: https://docs.devin.ai/release-notes/overview · https://docs.devin.ai/work-with-devin/advanced-capabilities · https://docs.devin.ai/get-started/first-run
  - Factory: https://factory.com/news/missions · https://docs.factory.com/cli/features/missions · https://docs.factory.com/missions/reference · https://docs.factory.com/cli/user-guides/specification-mode · https://docs.factory.com/reference/cli-reference
  - Amp: https://ampcode.com/news · https://ampcode.com/manual · https://ampcode.com/docs/puck
  - Kiro: https://kiro.dev/docs/specs/ · https://kiro.dev/docs/specs/feature-specs/requirements-first/ · https://kiro.dev/changelog/ · https://kiro.dev/blog/introducing-kiro-crew/
  - Warp: https://docs.warp.dev/agent-platform/ · https://docs.warp.dev/agent-platform/local-agents/agent-notifications · https://docs.warp.dev/platform/orchestration/ · https://www.warp.dev/blog/multi-harness-cloud-agent-orchestration
- **superpowers:** https://github.com/obra/superpowers/releases · https://github.com/obra/superpowers/blob/main/RELEASE-NOTES.md · https://github.com/obra/superpowers/compare/v6.4.1...v7.0.1 · https://github.com/obra/superpowers/tree/v6.4.1/skills · https://github.com/obra/superpowers/tree/v7.0.1/skills · https://github.com/obra/superpowers/blob/v7.0.1/skills/writing-plans/SKILL.md · https://github.com/obra/superpowers/blob/v7.0.1/skills/subagent-driven-development/SKILL.md · https://github.com/obra/superpowers/blob/v7.0.1/skills/subagent-driven-development/references/fix-loop.md · https://github.com/obra/superpowers/commit/bb92a77741419a4ab5f06e711a283343f1ada0c3
- **Anthropic plugins:** https://github.com/anthropics/claude-plugins-official · https://github.com/anthropics/claude-plugins-official/blob/main/.claude-plugin/marketplace.json · https://github.com/anthropics/claude-plugins-official/blob/main/plugins/feature-dev/commands/feature-dev.md · https://github.com/anthropics/claude-plugins-official/blob/main/plugins/code-review/commands/code-review.md · https://github.com/anthropics/claude-plugins-official/blob/main/plugins/session-report/skills/session-report/SKILL.md
- **wshobson/agents:** https://github.com/wshobson/agents/blob/main/README.md · https://github.com/wshobson/agents/blob/main/plugins/agent-orchestration/.claude-plugin/plugin.json · https://github.com/wshobson/agents/blob/main/plugins/ship-mate/.claude-plugin/plugin.json · https://github.com/wshobson/agents/blob/main/plugins/ship-mate/commands/ship.md · https://github.com/wshobson/agents/blob/main/plugins/ship-mate/agents/review.md · https://github.com/wshobson/agents/blob/main/plugins/ship-mate/stories/_template.md · https://github.com/wshobson/agents/blob/main/plugins/full-stack-orchestration/commands/full-stack-feature.md · https://github.com/wshobson/agents/blob/main/plugins/conductor/README.md
- **Ruflo:** https://github.com/ruvnet/ruflo/blob/main/README.md · https://github.com/ruvnet/ruflo/blob/main/plugins/ruflo-console/README.md · https://github.com/ruvnet/ruflo/blob/main/plugins/ruflo-cost-tracker/README.md · https://github.com/ruvnet/ruflo/blob/main/plugins/ruflo-sparc/README.md
- **BMAD:** https://github.com/bmad-code-org/BMAD-METHOD/blob/main/README.md · https://github.com/bmad-code-org/BMAD-METHOD/tags · https://github.com/bmad-code-org/BMAD-METHOD/blob/V6.12/src/bmm-skills/agents/bmad-agent-dev/SKILL.md · https://github.com/bmad-code-org/BMAD-METHOD/blob/V6.12/src/bmm-skills/ship/bmad-build/spec-template.md · https://github.com/bmad-code-org/BMAD-METHOD/blob/V6.12/src/bmm-skills/ship/bmad-build/step-02-plan.md · https://github.com/bmad-code-org/BMAD-METHOD/blob/V6.12/src/bmm-skills/ship/bmad-build/step-04-review.md · https://github.com/bmad-code-org/BMAD-METHOD/blob/V6.12/src/bmm-skills/ship/bmad-code-review/customize.toml · https://github.com/bmad-code-org/bmad-loop/blob/main/README.md
- **Spec Kit:** https://github.com/github/spec-kit/blob/main/README.md · https://github.com/github/spec-kit/releases/tag/v1.2.5 · https://github.com/github/spec-kit/blob/main/templates/spec-template.md · https://github.com/github/spec-kit/blob/main/templates/plan-template.md · https://github.com/github/spec-kit/blob/main/templates/tasks-template.md · https://github.com/github/spec-kit/blob/main/templates/commands/converge.md · https://github.com/github/spec-kit/blob/main/workflows/speckit/workflow.yml
- **GSD:** https://github.com/gsd-build/get-shit-done/blob/main/README.md · https://github.com/open-gsd/gsd-core · https://github.com/open-gsd/gsd-core/blob/next/docs/explanation/the-phase-loop.md · https://github.com/open-gsd/gsd-core/blob/next/docs/explanation/context-engineering.md · https://github.com/open-gsd/gsd-core/blob/next/docs/reference/planning-artifacts.md · https://github.com/open-gsd/gsd-core/tree/next/agents
- **Others:**
  - ccpm: https://github.com/automazeio/ccpm/blob/main/README.md · https://github.com/automazeio/ccpm/blob/main/skill/ccpm/references/conventions.md
  - Taskmaster: https://github.com/eyaltoledano/claude-task-master/blob/main/packages/tm-core/src/modules/workflow/services/test-result-validator.ts
  - SuperClaude: https://github.com/SuperClaude-Org/SuperClaude_Framework/blob/master/plugins/superclaude/agents/self-review.md
  - ECC: https://github.com/affaan-m/ECC/blob/main/skills/orch-pipeline/SKILL.md · https://github.com/affaan-m/ECC/blob/main/docs/releases/2.0.0/release-notes.md
  - oh-my-claudecode: https://github.com/Yeachan-Heo/oh-my-claudecode/blob/main/README.md
  - Compound Engineering: https://github.com/EveryInc/compound-engineering-plugin/blob/main/docs/guides/ce-code-review.md · https://github.com/EveryInc/compound-engineering-plugin/blob/main/docs/guides/ce-compound.md
  - OpenSpec: https://github.com/Fission-AI/OpenSpec/blob/main/README.md
- **Web platform:** https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts · https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API
