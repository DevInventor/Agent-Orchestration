# Agent-Orchestration

A multi-agent **feature-shipping pipeline** for [Claude Code](https://claude.com/claude-code).
Run `/ship <feature>` and a team of subagents plans the work, stops for your approval,
then builds, tests (with a bounded fix loop), and reviews it — across **one service or
many at once** — coordinating through a shared `./pipeline` bus with a live local dashboard.

```
/ship "add an isEven() helper to svcA and an isOdd() helper to svcB"
        │
        ▼
   PLANNER ──▶ service-grouped plan ──▶ ⏸ FINALIZE GATE (you approve) ──▶ …
        │
        ├─ svcA:  CODER ─▶ TESTER ⇄ (fix loop ≤5) ─▶ REVIEWER ─┐
        ├─ svcB:  CODER ─▶ TESTER ⇄ (fix loop ≤5) ─▶ REVIEWER ─┤─▶ QA ─▶ done
        │         (each service has its OWN fix budget; run in parallel batches)
        └────────────── shared bus: ./pipeline  +  live dashboard ──────────────┘
```

- **Plan first, then approve.** Nothing is coded until you reply `finalize` — you can edit scope at the gate.
- **One service or many.** A single-service feature runs the classic linear flow. A feature spanning several services fans out **phase-batched in parallel**, each service with its own fix-loop budget of 5 and its own dashboard row.
- **Bring your own repos.** An optional `agent-orchestration.config.json` registry maps service names to their local repo paths and test commands.
- **Watch it live.** A zero-dependency dashboard streams plan → code → test → review as it happens.

## Requirements

- **Claude Code** with plugin support.
- **Node.js** 18+ (for the dashboard server — Node stdlib only, no npm install).
- **Python 3.8+** available as `python3` (the pipeline bus CLI).
  - On **native Windows**, Python is usually `python`, not `python3`. Either run inside WSL2, or add a `python3` shim on PATH. Git Bash shim:
    ```bash
    printf '#!/bin/sh\nexec python "$@"\n' > ~/.local/bin/python3 && chmod +x ~/.local/bin/python3
    ```
    (and a `python3.cmd` doing `python %*` on PATH for PowerShell).

## Install

```
/plugin marketplace add DevInventor/Agent-Orchestration
/plugin install agent-orchestration
```

…or non-interactively:

```bash
claude plugin marketplace add DevInventor/Agent-Orchestration
claude plugin install agent-orchestration@agent-orchestration-marketplace
```

Replace `DevInventor` with the GitHub owner/repo you published to. Restart Claude Code to
activate the `/ship` command, the agents, and the skills.

## Quickstart

**Single service** — run `/ship` from the repo you're changing:

```
/ship "add a /health endpoint that returns 200 and the build SHA"
```

**Multiple services** — run `/ship` from the parent directory that contains your service
repos (your "repos root"):

```
/ship "add request-id propagation across the api and worker services"
```

**Already have a spec?** Skip the authoring step and point the pipeline straight at
your spec doc:

```
/ship-from-spec ./docs/my-feature-spec.md
```

`ship` writes the spec from your one-line feature request; `ship-from-spec` consumes
a spec doc you already have. Everything after the spec (plan → build → test → review →
QA) is identical — both share `docs/orchestration-runbook.md`.

In both cases the planner presents a plan and **waits** — reply `finalize` to start.
Watch progress at **http://localhost:4600**:

```bash
node "$(claude plugin root agent-orchestration)/ui/server.js" --pipeline ./pipeline
```

A multi-service run renders a **service-swimlane hero** — one lane per service grouped
into dependency waves (from `plan.json`, which `server.js` now forwards) — while a
single-service run keeps the classic assembly-line view.

## Configuring your services (optional)

Drop a **`agent-orchestration.config.json`** at your repos root to declare the services you work
with and where their repos live locally. It's a registry: list everything once, and each
`/ship` picks the subset a feature touches. Without it, Agent-Orchestration discovers services by
indexing — the config is purely optional.

```jsonc
{
  "$schema": "https://raw.githubusercontent.com/DevInventor/Agent-Orchestration/main/agent-orchestration.schema.json",
  "reposRoot": ".",
  "services": [
    { "name": "api", "path": "services/api", "test": "npm test", "build": "npm run build" },
    { "name": "web", "path": "services/web", "test": "npm test", "dependsOnServices": ["api"] }
  ]
}
```

| field | required | meaning |
|---|---|---|
| `name` | ✓ | unique id used on the bus and in plans |
| `path` | | local dir of the repo (relative to `reposRoot`, or absolute). Defaults to `name` |
| `test` | | shell command to run the service's tests, in its dir |
| `build` | | shell command to build the service |
| `dependsOnServices` | | services that must finish first (dependency waves) |

Validate it any time:

```bash
python3 "$(claude plugin root agent-orchestration)/scripts/pipe.py" config
```

See [`agent-orchestration.config.example.json`](agent-orchestration.config.example.json) and the
[JSON Schema](agent-orchestration.schema.json) (wire up the `$schema` line for editor autocomplete).

## How it works

| Agent | Role | Repo access |
|---|---|---|
| **planner** | Indexes the code, turns the feature into a service-grouped plan + task board | read-only |
| **coder** | Implements the plan; fixes failures routed back to it | read/write |
| **tester** | Authors + runs scenarios, reports pass/fail | read/write (tests only) |
| **reviewer** | Judges the diff against the plan, returns findings | read-only |

The **orchestrator** conducts from the top level: it seeds the bus, runs the plan +
finalize gate, then delegates.

- **Single service:** classic `plan → implement → test (fix loop ≤5) → review → QA → done`.
- **Multiple services (phase-batched):** the orchestrator spawns **all coders in one
  batch → awaits → all testers → awaits → re-spawns only the services still failing**,
  then a reviewer batch, then a macro QA gate. Each service keeps its **own** fix-loop
  counter (5 each), drops out the moment it's green, and `dependsOnServices` gates which
  services enter each wave. See `skills/ship` for the full contract.

### The pipeline bus

All agents coordinate only through files under `./pipeline` (managed atomically by
`scripts/pipe.py`). A multi-service run namespaces per-service artifacts under
`pipeline/services/<name>/`; the shared `run.json`, `tasks.json`, and `messages.jsonl`
drive the dashboard. `pipeline/` is git-ignored — it's run state, not source.

## Publishing your own copy

This repo is ready to publish as a Claude Code plugin marketplace. To host your own:

```bash
git init && git add -A && git commit -m "Agent-Orchestration plugin"
git remote add origin git@github.com:DevInventor/Agent-Orchestration.git
git push -u origin main
```

Then anyone can `claude plugin marketplace add DevInventor/Agent-Orchestration`. Before publishing,
replace `DevInventor` in this README and in `agent-orchestration.schema.json` / the example config, and
set your details in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.

## License

[MIT](LICENSE)
