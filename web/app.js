const $ = (s) => document.querySelector(s);
const logbody = $("#logbody");
const esc = (v) => String(v ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function line(text, cls = "") {
  const t = new Date().toLocaleTimeString();
  logbody.innerHTML += `<span class="dim">${t}</span> <span class="${cls}">${esc(text)}</span>\n`;
  logbody.scrollTop = 1e9;
}

// Scan scope comes from config, so the page can say how many contestants a
// scan covers before it starts.
let scope = { rank_start: 1, rank_end: 100 };
let scanning = false;
let setupReady = false;

const totalRanks = () => Math.max(0, scope.rank_end - scope.rank_start + 1);

// --- progress ------------------------------------------------------------
function showProgress({ rank = null, inspected = 0, contest = "" } = {}) {
  const total = totalRanks();
  if (!scanning) {
    $("#progress").innerHTML =
      `<span class="dim">A scan covers ranks ${scope.rank_start}–${scope.rank_end}` +
      ` — ${total} contestants.</span>`;
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
let reportedSoFar = 0, currentContest = "";

const es = new EventSource("/api/stream");
es.onmessage = (m) => {
  const ev = JSON.parse(m.data);
  if (ev.type === "log") {
    line(ev.msg, ev.level === "warn" ? "warn" : ev.level === "error" ? "error" : "");
  } else if (ev.type === "progress") {
    showProgress({ rank: ev.rank, inspected: reportedSoFar, contest: currentContest });
  } else if (ev.type === "scan_start") {
    scanning = true; reportedSoFar = 0; currentContest = ev.contest;
    setRunning(true);
    showProgress({ contest: currentContest });
    line(`Scan started: ${ev.contest}`, "warn");
  } else if (ev.type === "report") {
    reportedSoFar++;
    line(`REPORT ${ev.user} / ${ev.question} — ${ev.reason} (${ev.score}) → ${ev.outcome}`, "good");
    refresh();
  } else if (ev.type === "scan_end") {
    scanning = false;
    setRunning(false);
    showProgress();
    line(`Scan ${ev.status}: ${ev.scanned} contestants, ${ev.inspected} inspected, ` +
         `${ev.flagged} flagged, ${ev.reported} reported`, "warn");
    refresh();
  }
};

function setRunning(on) {
  $("#stop").disabled = !on;
  $("#scan").disabled = on || !setupReady;
  $("#scan").textContent = on ? "Scanning…" : "Start scanning";
}

// --- controls ------------------------------------------------------------
$("#scan").onclick = async () => {
  const slug = $("#slug").value.trim();
  if (!slug) return line("Enter a contest number first.", "error");
  const r = await (await fetch(`/api/scan/${slug}`, { method: "POST" })).json();
  if (!r.ok) line(r.error, "error");
};
$("#stop").onclick = () => fetch("/api/stop", { method: "POST" });
$("#clearlog").onclick = () => { logbody.innerHTML = ""; };
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
  if (!scanning) {
    $("#scan").disabled = !setupReady;
    $("#blocked").textContent = setupReady ? "" : "Finish setup to scan.";
  }

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
  scope = cfg.scope;
  const dry = cfg.safety.dry_run;
  $("#mode").textContent = dry ? "dry run" : "live";
  $("#mode").className = "pill" + (dry ? "" : " live");
  if (!scanning) showProgress();

  // Every number is counted from the stored rows, so a stopped or failed scan
  // adds nothing and rescanning a contest does not inflate anything.
  const st = await (await fetch("/api/stats")).json();
  $("#stats").innerHTML = [
    ["Caught", st.cheating_submissions_caught, "big"],
    ["Reports sent", st.reports_submitted, dry ? "muted" : ""],
    ["Suspicious", st.suspicious_recorded],
    ["Submissions inspected", st.submissions_scanned],
    ["Contests scanned", st.contests_scanned],
  ].map(([label, value, cls]) =>
    `<div class="stat ${cls || ""}"><span class="n">${value ?? 0}</span>` +
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
