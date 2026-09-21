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
function hall() {
  return {
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
      ? serveHTML(res, HTML)
      : (res.writeHead(404), res.end("no such run"));
  }
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
server.on("error", (e) => {
  if (e.code === "EADDRINUSE") {
    console.log(`Agent-Orchestration dashboard already running  ->  http://localhost:${PORT}`);
    console.log(`(if it is watching a different pipeline, stop it and restart with)`);
    console.log(` --pipeline ${SINGLE || "<dir>"}`);
    process.exit(0);
  }
  throw e;
});

// 127.0.0.1 only (section 14): POST /api/gate sits behind this, and an unbound listen
// offers it to the whole network.
server.listen(PORT, "127.0.0.1", () => {
  console.log(`Agent-Orchestration dashboard  ->  http://localhost:${PORT}`);
  if (SINGLE) {
    console.log(`watching pipeline    ->  ${SINGLE}`);
    if (!fs.existsSync(SINGLE)) {
      console.log(`(no pipeline yet — it appears once you run /ship in this repo)`);
    }
  } else {
    console.log(`scanning             ->  ${pipelinesRoot()} (${scanPipelines().length} pipeline(s))`);
  }
});
