// Claude Code runs this, not the dashboard: the UI still never spawns a process. One file
// for every hook the plugin ships, chosen by hook_event_name. Stdlib Node only, because
// Node is already required for the dashboard and, unlike `python3`, has no Store stub.
const fs = require("fs");
const os = require("os");
const path = require("path");

/* ---- ADR-0003: /ship starts in a fresh chat ----
   The orchestrator is a model, and every one of its turns re-reads the whole chat it runs
   in. On a real run that chat already held 492k tokens when /ship began, and re-reading it
   was 30% of the run's cost. So /ship is stopped once in a chat past MAX_CONTEXT, and the
   same command sent again inside CONFIRM_MS runs anyway: the person decides, once. */
const MAX_CONTEXT = 120000;
const CONFIRM_MS = 10 * 60 * 1000;
const SHIP = new Set(["ship", "ship-from-spec",
  "agent-orchestration:ship", "agent-orchestration:ship-from-spec"]);

// What the next turn re-reads: the last main-thread reply's input plus what it wrote.
// Only the tail is read - a chat this hook exists for can be tens of megabytes.
function contextTokens(transcript) {
  let text = "";
  try {
    const fd = fs.openSync(transcript, "r");
    const size = fs.fstatSync(fd).size, n = Math.min(size, 4 << 20);
    const buf = Buffer.alloc(n);
    fs.readSync(fd, buf, 0, n, size - n);
    fs.closeSync(fd);
    text = buf.toString("utf8");
  } catch { return 0; }
  const lines = text.split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    let m; try { m = JSON.parse(lines[i]); } catch { continue; }
    const u = m && m.type === "assistant" && !m.isSidechain && m.message && m.message.usage;
    if (u) return (u.input_tokens || 0) + (u.cache_read_input_tokens || 0)
      + (u.cache_creation_input_tokens || 0) + (u.output_tokens || 0);
  }
  return 0;
}

const stateFile = (sid) => path.join(process.env.AO_HOOK_STATE || os.tmpdir(),
  `ao-ship-${String(sid || "none").replace(/[^\w-]/g, "")}.json`);
const readState = (sid) => { try { return JSON.parse(fs.readFileSync(stateFile(sid), "utf8")); } catch { return {}; } };
const writeState = (sid, s) => { try { fs.writeFileSync(stateFile(sid), JSON.stringify(s)); } catch {} };
const fresh = (ts) => !!ts && Date.now() - ts < CONFIRM_MS;

function why(tokens, typed) {
  const k = Math.round(tokens / 1000);
  return `This chat already holds about ${k}k tokens, and the /ship orchestrator re-reads all ` +
    `of it on every turn - on a real run that was 30% of the cost. Start it in a fresh chat ` +
    `(/clear, then /ship): the run lives on its bus, so a resume picks up where it was. ` +
    (typed ? "To run it here anyway, send the same command again."
           : "Tell the user this, and do not retry: typing the command twice runs it here.");
}

function typedShip(e) {
  if (!SHIP.has(e.command_name)) return null;
  const st = readState(e.session_id), tokens = contextTokens(e.transcript_path);
  if (tokens <= MAX_CONTEXT || fresh(st.pending)) {
    writeState(e.session_id, { allowed: Date.now() });
    return null;
  }
  writeState(e.session_id, { pending: Date.now() });
  return { decision: "block", reason: why(tokens, true) };
}

// The model calling the skill itself. It may not confirm on the person's behalf, so only a
// typed confirmation (or a small chat) lets it through.
function skillShip(e) {
  if (!SHIP.has(String((e.tool_input || {}).skill || ""))) return null;
  const tokens = contextTokens(e.transcript_path);
  if (tokens <= MAX_CONTEXT || fresh(readState(e.session_id).allowed)) return null;
  return { hookSpecificOutput: { hookEventName: "PreToolUse",
    permissionDecision: "deny", permissionDecisionReason: why(tokens, false) } };
}

/* ---- a usage limit is a pause, not a death ----
   Claude Code waits for the reset and continues by itself. Meanwhile no agent writes to
   any bus, and the hall would call every running team dead. This file tells it why;
   server.js reads it and drops it once any bus moves again or it is a day old. */
const home = () => process.env.AGENT_ORCHESTRATION_HOME || path.join(os.homedir(), ".agent-orchestration");
const limitFile = () => path.join(home(), "usage-limit.json");
function writeLimit(state) {
  try {
    fs.mkdirSync(home(), { recursive: true });
    fs.writeFileSync(limitFile(), JSON.stringify({ at: new Date().toISOString(), state }));
  } catch {}
}

function handle(e) {
  switch (e.hook_event_name) {
    case "UserPromptExpansion": return typedShip(e);
    case "PreToolUse": return e.tool_name === "Skill" ? skillShip(e) : null;
    case "StopFailure": if (e.error === "rate_limit") writeLimit("waiting"); return null;
    case "Notification":
      if (e.notification_type === "quota_auto_resume_fired") fs.rmSync(limitFile(), { force: true });
      else if (/^quota_auto_resume_(stale|disabled)$/.test(e.notification_type || "")) writeLimit("needs-you");
      return null;
    default: return null;
  }
}

let raw = "";
process.stdin.on("data", (c) => { raw += c; }).on("end", () => {
  let e; try { e = JSON.parse(raw); } catch { return; }
  let out = null;
  try { out = handle(e); } catch { /* a broken hook must never block the person's work */ }
  if (out) process.stdout.write(JSON.stringify(out));
});
