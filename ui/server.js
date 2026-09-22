#!/usr/bin/env node
/*
 * Agent-Orchestration dashboard server. Zero dependencies (Node stdlib only).
 *
 *   node server.js [--pipeline <dir>] [--port 4600]
 *
 * Default is SCAN mode over the fixed pipelines root ($AGENT_ORCHESTRATION_HOME, else
 * ~/.agent-orchestration): `/` is the hall, `/r/<slug>` is one run's board, and
 * `/events?run=<slug>` is that run's stream. `--pipeline <dir>` (or $PIPELINE_DIR) keeps
 * the original single-bus mode exactly as it was (spec section 16).
 */
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

const args = process.argv.slice(2);
function opt(flag, fallback) {
  const i = args.indexOf(flag);
  return i !== -1 && args[i + 1] ? args[i + 1] : fallback;
}
// One bus, fixed at startup, only when asked for. Otherwise the root is scanned.
const SINGLE = args.includes("--pipeline") || process.env.PIPELINE_DIR
  ? path.resolve(opt("--pipeline", process.env.PIPELINE_DIR))
  : null;
const PORT = parseInt(opt("--port", process.env.PORT || "4600"), 10);
const HTML = path.join(__dirname, "index.html");
const HALL = path.join(__dirname, "hall.html");
// Section 10.6's three-pane board. index.html stays as the fallback so a bus served in
// single-run mode, and any older install, still renders something.
const BOARD = path.join(__dirname, "board.html");

function readJSON(p, fallback) {
  try { return JSON.parse(fs.readFileSync(p, "utf8")); }
  catch { return fallback; }
}

// Mirror of pipe.py pipelines_root() / scan_pipelines(): the directory IS the registry,
// so adding a team is creating a directory. Kept the same shape as the Python on purpose
// - two implementations of one rule only stay honest if they read alike.
function pipelinesRoot() {
  const home = process.env.AGENT_ORCHESTRATION_HOME
    || path.join(os.homedir(), ".agent-orchestration");
  return path.join(home, "pipelines");
}
function scanPipelines() {
  const base = pipelinesRoot();
  let names = [];
  try { names = fs.readdirSync(base).sort(); } catch { return []; }
  const out = [];
  for (const name of names) {
    const rp = path.join(base, name, "pipeline", "run.json");
    if (fs.existsSync(rp)) {
      out.push({ slug: name, root: path.dirname(rp), run: readJSON(rp, {}) });
    }
  }
  return out;
}
// A slug is resolved by IDENTITY against the scan list and the entry's own recorded path
// is what gets used - nothing from a request is ever joined to a path (section 14).
function findPipeline(slug) {
  if (typeof slug !== "string" || !slug) return null;
  return scanPipelines().find((p) => p.slug === slug) || null;
}

// messages.jsonl is append-only across every run this bus has ever seen, so the tail
// alone can mix features. Scope it to the active runId; logs written before runId
// stamping carry none, so fall back to the raw tail rather than showing a blank feed.
function tailMessages(dir, limit, runId) {
  try {
    const lines = fs.readFileSync(path.join(dir, "messages.jsonl"), "utf8")
      .split("\n").filter(Boolean).slice(-5000);
    const all = lines.map((l) => { try { return JSON.parse(l); } catch { return null; } })
      .filter(Boolean);
    if (!runId) return all.slice(-limit);
    const mine = all.filter((m) => m.runId === runId);
    return (mine.length ? mine : all).slice(-limit);
  } catch { return []; }
}
function snapshot(dir) {
  const run = readJSON(path.join(dir, "run.json"), null);
  return {
    run,
    // plan carries services[].dependsOnServices, which the dashboard uses to draw
    // dependency waves in a multi-service run.
    plan: readJSON(path.join(dir, "plan.json"), null),
    tasks: readJSON(path.join(dir, "tasks.json"), { tasks: [] }).tasks,
    messages: tailMessages(dir, 400, run && run.runId),
    pipelineDir: dir,
  };
}

// ponytail: only the last 8 KB of the log is read for the hall's one-line summary. The
// ceiling is a final record longer than 8 KB (or a run whose last 8 KB is unparseable)
// showing no line; the cost avoided is tailing 12 whole logs every 700 ms. Upgrade path
// if that ever bites: keep a per-bus offset and read only what was appended.
const TAIL_BYTES = 8192;
function lastEvent(dir) {
  try {
    const p = path.join(dir, "messages.jsonl");
    const size = fs.statSync(p).size;
    const start = Math.max(0, size - TAIL_BYTES);
    const buf = Buffer.alloc(size - start);
    const fd = fs.openSync(p, "r");
    try { fs.readSync(fd, buf, 0, buf.length, start); } finally { fs.closeSync(fd); }
    const lines = buf.toString("utf8").split("\n").filter(Boolean);
    for (let i = lines.length - 1; i >= 0; i--) {
      try { return JSON.parse(lines[i]); } catch { /* a torn first line, or a half-write */ }
    }
  } catch { /* no log yet */ }
  return null;
}

// Deliberately small: the hall shows twelve teams at once, and everything else is one
// click away at /r/<slug>.
// The repositories panel asks "what does this project own", which the service registry
// already answers - run.repos[] only fills in once a workstream has created worktrees, so
// an in-place run left the panel permanently empty. Walk up from cwd the way pipe.py's
// find_config does. ponytail: name and path only. Index state and node counts live in the
// graph service, which speaks no JSON over 9749, and stdlib node has no MCP client - the
// panel hands off to it instead. Wire real counts when that service exposes an endpoint.
function readRegistry(dir) {
  const p = path.join(dir, "agent-orchestration.config.json");
  if (!fs.existsSync(p)) return null;
  try {
    const cfg = JSON.parse(fs.readFileSync(p, "utf8"));
    const base = path.resolve(dir, cfg.reposRoot || ".");
    return (cfg.services || []).map((s) => ({
      name: s.name,
      path: path.join(base, s.path || s.name),
    }));
  } catch { return null; }            // a broken registry is cmd_config's to report
}

function registry() {
  // Up from cwd, the way pipe.py's find_config resolves it - then one level DOWN, because
  // a repos root is commonly a child of where you start the dashboard (GoTrust keeps its
  // registry at GoTrust/codebase/, and the natural place to run from is GoTrust/).
  let dir = process.cwd();
  for (let i = 0; i < 6; i++) {
    const here = readRegistry(dir);
    if (here) return here;
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  try {
    for (const e of fs.readdirSync(process.cwd(), { withFileTypes: true })) {
      if (!e.isDirectory() || e.name.startsWith(".")) continue;
      const child = readRegistry(path.join(process.cwd(), e.name));
      if (child) return child;
    }
  } catch { /* unreadable cwd is not this panel's problem */ }
  return [];
}

function hall() {
  return {
    registry: registry(),
    root: pipelinesRoot(),
    pipelines: scanPipelines().map((p) => {
      const r = p.run || {};
      const ev = lastEvent(p.root);
      return {
        slug: p.slug, feature: r.feature, phase: r.phase, status: r.status,
        activeAgent: r.activeAgent, progressPct: r.progressPct, loop: r.loop,
        services: r.services || null,
        repos: (r.repos || []).map((e) => e.service),
        startedAt: r.startedAt, updatedAt: r.updatedAt,
        lastEvent: ev && { ts: ev.ts, agent: ev.agent, type: ev.type, summary: ev.summary },
      };
    }),
  };
}

// Each client records the bus it subscribed to (null = the hall stream) and receives
// only that, so twelve open boards do not each carry twelve buses' traffic.
const clients = new Set();
function broadcast() {
  if (SINGLE) {
    const payload = `data: ${JSON.stringify(snapshot(SINGLE))}\n\n`;
    for (const res of clients) res.write(payload);
    return;
  }
  const cache = new Map();
  for (const res of clients) {
    if (!cache.has(res.busDir)) {
      cache.set(res.busDir, JSON.stringify(res.busDir ? snapshot(res.busDir) : hall()));
    }
    res.write(`data: ${cache.get(res.busDir)}\n\n`);
  }
}

// Poll the bus for changes (fs.watch is unreliable cross-platform / on WSL2).
const WATCHED = ["run.json", "plan.json", "tasks.json", "messages.jsonl"];
let lastSig = "";
setInterval(() => {
  let sig = "";
  for (const dir of SINGLE ? [SINGLE] : scanPipelines().map((p) => p.root)) {
    for (const f of WATCHED) {
      try { sig += dir + f + fs.statSync(path.join(dir, f)).mtimeMs + ";"; } catch {}
    }
  }
  if (sig !== lastSig) { lastSig = sig; broadcast(); }
}, 700);

// Section 14. The gate is the first path where a browser can move a run forward, so:
// three fixed decisions and nothing free-form, a slug resolved by identity against the
// scan list, no slug or decision in the URL, a capped body, and no process ever spawned.
// It releases a waiter - it never merges. Merging stays `pipe.py finish --apply`.
const GATE_DECISIONS = ["finalize", "in-place", "reject"];   // == pipe.py GATE_DECISIONS
const GATE_BODY_MAX = 4096;

// The one record format, written here and by pipe.py cmd_gate, read by cmd_wait.
// Two writers of one file, kept in agreement by a test rather than by discipline
// (scripts/test_pipe.py S37 compares this key set against the one pipe.py writes).
function gateRecord(runId, decision) {
  return { decision: decision, runId: runId, ts: new Date().toISOString(), by: "browser" };
}

function apiGate(req, res) {
  let body = "", done = false;
  req.on("data", (chunk) => {
    if (done) return;
    body += chunk;
    if (body.length > GATE_BODY_MAX) {
      done = true;
      sendJSON(res, 413, { error: `body must be under ${GATE_BODY_MAX} bytes` });
      req.destroy();
    }
  });
  req.on("end", () => {
    if (done) return;
    let payload;
    try { payload = JSON.parse(body); } catch { payload = null; }
    if (!payload || typeof payload !== "object") {
      return sendJSON(res, 400, { error: "body must be JSON {slug, decision}" });
    }
    if (!GATE_DECISIONS.includes(payload.decision)) {
      return sendJSON(res, 400, {
        error: `decision must be one of ${GATE_DECISIONS.join(", ")}`, field: "decision" });
    }
    const p = findPipeline(payload.slug);
    if (!p) return sendJSON(res, 404, { error: "unknown slug", field: "slug" });
    // dirname of the bus the SCAN recorded - mirrors pipe.py gate_path(). Nothing from
    // the request reaches this path, so there is no traversal surface to guard.
    const file = path.join(path.dirname(p.root), "gate.json");
    const tmp = file + ".tmp";
    try {
      fs.writeFileSync(tmp, JSON.stringify(gateRecord(p.run.runId, payload.decision), null, 2));
      fs.renameSync(tmp, file);   // temp + rename: a waiter never reads a half-written gate
    } catch (e) {
      // A bus deleted between the scan and the write must not take the dashboard down.
      return sendJSON(res, 500, { error: `could not write the gate: ${e.code || e.message}` });
    }
    sendJSON(res, 200, { ok: true, slug: p.slug, decision: payload.decision });
  });
}

function serveHTML(res, file, fallback) {
  fs.readFile(file, (err, buf) => {
    if (err && fallback) return serveHTML(res, fallback);
    if (err) { res.writeHead(500); return res.end(path.basename(file) + " not found"); }
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(buf);
  });
}
function sendJSON(res, code, body) {
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}
function stream(req, res, busDir) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });
  res.busDir = busDir;
  res.write(`data: ${JSON.stringify(busDir ? snapshot(busDir) : hall())}\n\n`);
  clients.add(res);
  const ka = setInterval(() => res.write(": keep-alive\n\n"), 20000);
  req.on("close", () => { clearInterval(ka); clients.delete(res); });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const slug = url.searchParams.get("run");
  const board = url.pathname.match(/^\/r\/([^/]+)\/?$/);

  if (SINGLE) {
    if (url.pathname === "/") return serveHTML(res, HTML);
    if (url.pathname === "/api/state") return sendJSON(res, 200, snapshot(SINGLE));
    if (url.pathname === "/events") return stream(req, res, SINGLE);
    res.writeHead(404); return res.end("not found");
  }

  if (url.pathname === "/") {
    // hall.html is T6; until it lands, / falls back to the single-run board.
    return serveHTML(res, HALL, HTML);
  }
  if (board) {
    // The slug is checked against the scan list, never joined to a path.
    return findPipeline(decodeURIComponent(board[1]))
      ? serveHTML(res, BOARD, HTML)
      : (res.writeHead(404), res.end("no such run"));
  }
  if (url.pathname === "/api/gate" && req.method === "POST") return apiGate(req, res);
  if (url.pathname === "/api/hall") return sendJSON(res, 200, hall());
  if (url.pathname === "/api/state") {
    const p = findPipeline(slug);
    if (!p) return sendJSON(res, 404, { error: "unknown run", field: "run" });
    return sendJSON(res, 200, snapshot(p.root));
  }
  if (url.pathname === "/events") {
    if (!slug) return stream(req, res, null);
    const p = findPipeline(slug);
    if (!p) return sendJSON(res, 404, { error: "unknown run", field: "run" });
    return stream(req, res, p.root);
  }
  res.writeHead(404); res.end("not found");
});

// Launching the dashboard is now part of starting a run, so a second launch is expected
// and must not be a crash: report the one already running and exit clean.
// A held port is NOT proof our dashboard is on it. Observed: 4600 and 4601 both taken,
// one by a dashboard from a run that had finished three days earlier and that nothing
// reaps - so assuming "already running" and exiting left the operator with no dashboard
// at all. Step to the next free port instead, and report the one actually bound.
let port = PORT;
server.on("error", (e) => {
  if (e.code === "EADDRINUSE" && port < PORT + 10) {
    server.listen(++port, "127.0.0.1");
    return;
  }
  if (e.code === "EADDRINUSE") {
    console.log(`no free port in ${PORT}-${PORT + 10}; stop a stale dashboard and retry`);
    process.exit(1);
  }
  throw e;
});

// 127.0.0.1 only (section 14): POST /api/gate sits behind this, and an unbound listen
// offers it to the whole network.
server.listen(PORT, "127.0.0.1", () => {
  port = server.address().port;
  console.log(`Agent-Orchestration dashboard  ->  http://localhost:${port}`);
  if (SINGLE) {
    console.log(`watching pipeline    ->  ${SINGLE}`);
    if (!fs.existsSync(SINGLE)) {
      console.log(`(no pipeline yet — it appears once you run /ship in this repo)`);
    }
  } else {
    console.log(`scanning             ->  ${pipelinesRoot()} (${scanPipelines().length} pipeline(s))`);
  }
});
