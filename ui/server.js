#!/usr/bin/env node
/*
 * Agent-Orchestration dashboard server. Zero dependencies (Node stdlib only).
 *
 *   node server.js [--pipeline <dir>] [--port 4600]
 *
 * Serves the dashboard and streams the ./pipeline bus over Server-Sent Events.
 * Defaults: pipeline = ./pipeline (cwd), or $PIPELINE_DIR; port 4600 or $PORT.
 */
const http = require("http");
const fs = require("fs");
const path = require("path");

const args = process.argv.slice(2);
function opt(flag, fallback) {
  const i = args.indexOf(flag);
  return i !== -1 && args[i + 1] ? args[i + 1] : fallback;
}
const PIPELINE = path.resolve(
  opt("--pipeline", process.env.PIPELINE_DIR || path.join(process.cwd(), "pipeline"))
);
const PORT = parseInt(opt("--port", process.env.PORT || "4600"), 10);
const HTML = path.join(__dirname, "index.html");

function readJSON(p, fallback) {
  try { return JSON.parse(fs.readFileSync(p, "utf8")); }
  catch { return fallback; }
}
function tailMessages(limit) {
  try {
    const lines = fs.readFileSync(path.join(PIPELINE, "messages.jsonl"), "utf8")
      .split("\n").filter(Boolean);
    return lines.slice(-limit).map((l) => { try { return JSON.parse(l); } catch { return null; } })
      .filter(Boolean);
  } catch { return []; }
}
function snapshot() {
  return {
    run: readJSON(path.join(PIPELINE, "run.json"), null),
    // plan carries services[].dependsOnServices, which the dashboard uses to draw
    // dependency waves in a multi-service run.
    plan: readJSON(path.join(PIPELINE, "plan.json"), null),
    tasks: readJSON(path.join(PIPELINE, "tasks.json"), { tasks: [] }).tasks,
    messages: tailMessages(400),
    pipelineDir: PIPELINE,
  };
}

const clients = new Set();
function broadcast() {
  const payload = `data: ${JSON.stringify(snapshot())}\n\n`;
  for (const res of clients) res.write(payload);
}

// Poll the bus for changes (fs.watch is unreliable cross-platform / on WSL2).
let lastSig = "";
setInterval(() => {
  let sig = "";
  for (const f of ["run.json", "plan.json", "tasks.json", "messages.jsonl"]) {
    try { sig += f + fs.statSync(path.join(PIPELINE, f)).mtimeMs + ";"; } catch {}
  }
  if (sig !== lastSig) { lastSig = sig; broadcast(); }
}, 700);

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname === "/") {
    fs.readFile(HTML, (err, buf) => {
      if (err) { res.writeHead(500); return res.end("index.html not found"); }
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(buf);
    });
  } else if (url.pathname === "/api/state") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(snapshot()));
  } else if (url.pathname === "/events") {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });
    res.write(`data: ${JSON.stringify(snapshot())}\n\n`);
    clients.add(res);
    const ka = setInterval(() => res.write(": keep-alive\n\n"), 20000);
    req.on("close", () => { clearInterval(ka); clients.delete(res); });
  } else {
    res.writeHead(404); res.end("not found");
  }
});

server.listen(PORT, () => {
  console.log(`Agent-Orchestration dashboard  ->  http://localhost:${PORT}`);
  console.log(`watching pipeline    ->  ${PIPELINE}`);
  if (!fs.existsSync(PIPELINE)) {
    console.log(`(no pipeline yet — it appears once you run /ship in this repo)`);
  }
});
