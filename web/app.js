const $ = (s) => document.querySelector(s);
const logbody = $("#logbody");
const esc = (v) => String(v ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function line(text, cls = "") {
  const t = new Date().toLocaleTimeString();
  logbody.innerHTML += `<span class="dim">${t}</span> <span class="${cls}">${esc(text)}</span>\n`;
  logbody.scrollTop = 1e9;
}

// The range a scan covers: seeded from config, replaced by what the running
// scan reports so the count is always against what is really being scanned.
let scope = { rank_start: 1, rank_end: 100 };
let scanning = false;
let paused = false;
let setupReady = false;
let dryRun = true;

const totalRanks = () => Math.max(0, scope.rank_end - scope.rank_start + 1);

// --- progress ------------------------------------------------------------
function showProgress({ rank = null, inspected = 0, contest = "" } = {}) {
  const total = totalRanks();
  if (!scanning) {
    const want = Number($("#count").value) || total;
    $("#progress").innerHTML =
      `<span class="dim">Next scan covers the top ${want} contestants.</span>`;
    return;
  }
  const done = rank === null ? 0 : rank - scope.rank_start + 1;
  const pct = total ? Math.min(100, Math.max(0, (done / total) * 100)) : 0;
  $("#progress").innerHTML =
    `<div class="bar"><span style="width:${pct.toFixed(1)}%"></span></div>` +
    `<div class="barline"><b>${rank === null ? "Starting…" : `Contestant ${done} of ${total}`}</b>` +
    `<span class="dim">${esc(contest)}${inspected ? ` · ${inspected} reported so far` : ""}</span></div>`;
}

// --- live event stream ---------------------------------------------------
let reportedSoFar = 0, currentContest = "", lastRank = null;

const es = new EventSource("/api/stream");
es.onmessage = (m) => {
  const ev = JSON.parse(m.data);
  if (ev.type === "log") {
    line(ev.msg, ev.level === "warn" ? "warn" : ev.level === "error" ? "error" : "");
  } else if (ev.type === "progress") {
    lastRank = ev.rank;
    showProgress({ rank: ev.rank, inspected: reportedSoFar, contest: currentContest });
  } else if (ev.type === "state") {
    paused = !!ev.paused;
    setRunning(scanning);
    showProgress({ rank: lastRank, inspected: reportedSoFar, contest: currentContest });
  } else if (ev.type === "scan_start") {
    scanning = true; paused = false; reportedSoFar = 0; currentContest = ev.contest;
    if (ev.rank_end) scope = { rank_start: ev.rank_start, rank_end: ev.rank_end };
    setRunning(true);
    showProgress({ contest: currentContest });
    line(`Scan started: ${ev.contest}`, "warn");
  } else if (ev.type === "report") {
    reportedSoFar++;
    line(`REPORT ${ev.user} / ${ev.question} — ${ev.reason} (${ev.score}) → ${ev.outcome}`, "good");
    refresh();
  } else if (ev.type === "scan_end") {
    scanning = false; paused = false;
    setRunning(false);
    showProgress();
    line(`Scan ${ev.status}: ${ev.scanned} contestants, ${ev.inspected} inspected, ` +
         `${ev.flagged} flagged, ${ev.reported} reported`, "warn");
    refresh();
  }
};

function setRunning(on) {
  const haveSlug = !!$("#slug").value.trim();
  // Every lookup is null-checked. A stale cached page once served an old
  // index.html against a new app.js: the missing button threw here, and the
  // throw took the whole handler down with it -- including Stop. The controls
  // that end a scan must degrade one at a time, never all at once.
  const stop = $("#stop"), pause = $("#pause"), scan = $("#scan");
  // Stop and Pause stay live for the whole run: they are the only way out of
  // a scan, so they must never be the thing that is disabled.
  if (stop) { stop.disabled = !on; stop.textContent = "Stop"; }
  if (pause) {
    pause.disabled = !on;
    pause.textContent = paused ? "Resume" : "Pause";
    pause.classList.toggle("primary", paused && on);
  }
  if (scan) {
    scan.disabled = on || !setupReady || !haveSlug;
    scan.textContent = on ? (paused ? "Paused" : "Scanning…") : "Start scanning";
  }
  $("#blocked").textContent = on ? ""
    : !setupReady ? "Finish setup to scan."
    : !haveSlug ? "Enter a contest number." : "";
  showMode();
}

// --- dry run / live ------------------------------------------------------
// Going live is the consequential direction -- every later scan files real
// reports against real people -- so that way takes two clicks. Going back to
// dry run is harmless and takes one.
let armLive = false;

function showMode() {
  const el = $("#mode");
  if (!el) return;
  el.textContent = armLive ? "click to confirm" : dryRun ? "dry run" : "live";
  el.className = "pill" + (dryRun ? "" : " live") + (armLive ? " arm" : "");
  el.disabled = scanning;
  el.title = scanning
    ? "A scan is running. It keeps the mode it started with."
    : dryRun
      ? "Dry run: reports are composed and stored, never sent. Click to go live."
      : "Live: every scan files reports to LeetCode. Click for dry run.";
}

if ($("#mode")) $("#mode").onclick = async () => {
  if (scanning) return;
  if (dryRun && !armLive) {             // arm, do not switch yet
    armLive = true;
    showMode();
    setTimeout(() => { if (armLive) { armLive = false; showMode(); } }, 4000);
    return;
  }
  armLive = false;
  const r = await (await fetch(`/api/mode?dry_run=${!dryRun}`,
                               { method: "POST" })).json();
  if (!r.ok) return line(r.error, "error");
  dryRun = r.dry_run;
  line(dryRun ? "Switched to DRY RUN - nothing will be submitted."
              : "Switched to LIVE - scans will file reports to LeetCode.", "warn");
  refresh();
};

// --- controls ------------------------------------------------------------
$("#scan").onclick = async () => {
  const slug = $("#slug").value.trim();
  if (!slug) { $("#slug").focus(); return line("Enter a contest number first.", "error"); }
  const n = Math.max(1, Number($("#count").value) || 100);
  const r = await (await fetch(`/api/scan/${encodeURIComponent(slug)}?contestants=${n}`,
                               { method: "POST" })).json();
  if (!r.ok) line(r.error, "error");
};
$("#stop").onclick = () => {
  $("#stop").disabled = true;
  $("#stop").textContent = "Stopping…";
  fetch("/api/stop", { method: "POST" });
};
if ($("#pause")) $("#pause").onclick = async () => {
  // Optimistic: the button answers at once, the scan catches up at the next
  // step boundary. The state event puts it right either way.
  const want = !paused;
  $("#pause").disabled = true;
  await fetch(want ? "/api/pause" : "/api/resume", { method: "POST" });
  $("#pause").disabled = false;
};
$("#clearlog").onclick = () => { logbody.innerHTML = ""; };
$("#slug").oninput = () => { if (!scanning) setRunning(false); };
$("#count").oninput = () => { if (!scanning) showProgress(); };
$("#slug").onkeydown = (e) => {
  if (e.key === "Enter" && !$("#scan").disabled) $("#scan").click();
};

document.querySelectorAll(".tab").forEach((t) => {
  t.onclick = () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $("#" + t.dataset.tab).classList.add("active");
  };
});

// --- rendering -----------------------------------------------------------
function table(rows, cols, empty) {
  if (!rows.length) return `<p class="dim empty">${esc(empty)}</p>`;
  const head = cols.map(([, label]) => `<th>${label}</th>`).join("");
  const body = rows.map((r) =>
    `<tr>${cols.map(([k, , fmt]) =>
      `<td>${fmt ? fmt(r[k], r) : esc(r[k])}</td>`).join("")}</tr>`).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

const badge = (v) =>
  `<span class="badge">${esc(String(v ?? "").replace(/_/g, " ").toLowerCase())}</span>`;
const when = (v) =>
  esc(String(v ?? "").replace("T", " ").replace("+00:00", "").slice(0, 16));

// --- setup checklist -----------------------------------------------------
// Always on screen while anything is outstanding. The old layout hid these
// steps the moment live reporting was switched on, which is exactly when they
// matter most.
async function refreshSetup() {
  let st;
  try { st = await (await fetch("/api/setup")).json(); }
  catch { return; }

  const steps = [
    { ok: st.chrome_found, title: "Chrome installed",
      done: "Found on this machine",
      todo: "Not found in the usual places — install Chrome, then re-check" },
    { ok: st.browser_running, title: "Browser running",
      done: "Listening on the debugging port",
      todo: st.chrome_found
        ? "Opens on its own profile, separate from your everyday Chrome"
        : "Install Chrome first",
      action: st.chrome_found && !st.browser_running
        ? { label: "Start browser", id: "start-browser" } : null },
    { ok: !!st.signed_in_as, title: "Signed in to LeetCode",
      done: `Signed in as ${st.signed_in_as || ""}`,
      todo: st.browser_running
        ? "Sign in by hand in the window that opened — reports are filed as that account"
        : "Start the browser first",
      action: st.browser_running && !st.signed_in_as
        ? { label: "Re-check", id: "recheck" } : null },
  ];

  setupReady = steps.every((s) => s.ok);
  const el = $("#setup");
  el.className = "setup" + (setupReady ? " ready" : "");

  // Live reporting is a standing warning, not a setup step: it sits alongside
  // the steps instead of replacing them.
  const banner = st.dry_run ? "" :
    `<div class="livebar">Live reporting — every scan files reports to LeetCode</div>`;

  el.innerHTML = banner + (setupReady
    ? `<div class="step ok"><span class="dot">✓</span><span class="step-text">` +
      `<b>Ready to scan</b><span class="dim">Chrome running, signed in as ` +
      `${esc(st.signed_in_as)}</span></span>` +
      `<button id="recheck" class="ghost">Re-check</button></div>`
    : `<p class="setup-head">Set up before scanning</p>` +
      steps.map((s, i) => `
        <div class="step ${s.ok ? "ok" : "todo"}">
          <span class="dot">${s.ok ? "✓" : i + 1}</span>
          <span class="step-text">
            <b>${esc(s.title)}</b>
            <span class="dim">${esc(s.ok ? s.done : s.todo)}</span>
          </span>
          ${s.action ? `<button id="${s.action.id}">${esc(s.action.label)}</button>` : ""}
        </div>`).join(""));

  // Scanning without a signed-in browser only ever produces a failed scan.
  if (!scanning) setRunning(false);

  const start = $("#start-browser");
  if (start) start.onclick = async () => {
    start.disabled = true; start.textContent = "Starting…";
    await fetch("/api/browser/start", { method: "POST" });
    line("Browser started. Sign in to LeetCode in that window.", "warn");
    refreshSetup();
  };
  const recheck = $("#recheck");
  if (recheck) recheck.onclick = () => { recheck.textContent = "Checking…"; refreshSetup(); };
}

async function refresh() {
  refreshSetup();

  const cfg = await (await fetch("/api/config")).json();
  // Adopt the server's state rather than assuming idle: after a page reload
  // mid-scan the buttons would otherwise be dead, leaving no way to stop.
  if (cfg.running !== scanning || cfg.paused !== paused) {
    scanning = cfg.running; paused = cfg.paused;
    setRunning(scanning);
  }
  if (!scanning) scope = cfg.scope;
  const dry = cfg.safety.dry_run;
  dryRun = dry;
  showMode();
  if (!scanning) showProgress();

  // Every number is counted from the stored rows, so a stopped or failed scan
  // adds nothing and rescanning a contest does not inflate anything.
  const st = await (await fetch("/api/stats")).json();
  // Headline numbers count people, not rows. Somebody who pasted all four
  // problems is one offender, not four. The row-level count is still there on
  // hover, and per contestant in the table below.
  const per = (n, noun) => `${n ?? 0} ${noun}${n === 1 ? "" : "s"}`;
  $("#stats").innerHTML = [
    ["Contestants caught", st.users_caught, "big",
     per(st.cheating_submissions_caught, "submission")],
    ["Contestants reported", st.users_reported, dry ? "muted" : "",
     per(st.reports_submitted, "report") + " sent"],
    ["Suspicious", st.users_suspicious, "",
     per(st.suspicious_recorded, "submission") + ", recorded not reported"],
    ["Submissions inspected", st.submissions_scanned, "", ""],
    ["Contests scanned", st.contests_scanned, "", ""],
  ].map(([label, value, cls, hint]) =>
    `<div class="stat ${cls || ""}"${hint ? ` title="${esc(hint)}"` : ""}>` +
    `<span class="n">${value ?? 0}</span>` +
    `<span class="l">${label}</span></div>`).join("");

  const users = await (await fetch("/api/by-user")).json();
  $("#users").innerHTML = table(users, [
    ["username", "Contestant", (v) =>
      `<a href="https://leetcode.com/u/${encodeURIComponent(v)}/" target="_blank" rel="noopener">${esc(v)}</a>`],
    ["submissions", "Caught"],
    ["sent", "Sent"],
    ["reasons", "Reasons", (v) => String(v || "").split(",").map(badge).join(" ")],
    ["last_seen", "Last", when],
  ], "Nobody caught yet.");

  $("#scans").innerHTML = table(await (await fetch("/api/scans")).json(), [
    ["contest_slug", "Contest"],
    ["started_at", "Started", when],
    ["ranks_scanned", "Contestants"],
    ["submissions_seen", "Inspected"],
    ["reported", "Reported"],
    ["status", "Status", badge],
  ], "No contest scanned yet.");
}

refresh();
setInterval(refreshSetup, 10000);   // notice a browser closed behind our back
