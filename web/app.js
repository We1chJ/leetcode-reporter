const $ = (s) => document.querySelector(s);
const logbody = $("#logbody");
const esc = (v) => String(v ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function line(text, cls = "") {
  const t = new Date().toLocaleTimeString();
  logbody.innerHTML += `<span class="dim">${t}</span> <span class="${cls}">${esc(text)}</span>\n`;
  logbody.parentElement.scrollTop = 1e9;
}

// --- live event stream ---------------------------------------------------
const es = new EventSource("/api/stream");
es.onmessage = (m) => {
  const ev = JSON.parse(m.data);
  if (ev.type === "log")
    line(ev.msg, ev.level === "warn" ? "warn" : ev.level === "error" ? "error" : "");
  else if (ev.type === "progress")
    $("#status").textContent = `rank ${ev.rank} — ${ev.user}`;
  else if (ev.type === "scan_start")
    line(`Scan started: ${ev.contest}${ev.dry_run ? " (dry run)" : ""}`, "warn");
  else if (ev.type === "report") {
    line(`REPORT ${ev.user} / ${ev.question} — ${ev.reason} (${ev.score}) → ${ev.outcome}`, "good");
    refresh();
  } else if (ev.type === "scan_end") {
    line(`Scan ${ev.status}: ${ev.scanned} contestants, ${ev.inspected} submissions inspected, ` +
         `${ev.flagged} flagged, ${ev.reported} reported`, "warn");
    $("#status").textContent = "";
    refresh();
  }
};

// --- controls ------------------------------------------------------------
$("#scan").onclick = async () => {
  const slug = $("#slug").value.trim();
  if (!slug) return line("Enter a contest slug first.", "error");
  const r = await (await fetch(`/api/scan/${slug}`, { method: "POST" })).json();
  if (!r.ok) line(r.error, "error");
};
$("#stop").onclick = () => fetch("/api/stop", { method: "POST" });

document.querySelectorAll(".tab").forEach((t) => {
  t.onclick = () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $("#" + t.dataset.tab).classList.add("active");
  };
});

// --- report drawer -------------------------------------------------------
let reportsCache = [];
$("#drawer-close").onclick = () => $("#drawer").classList.remove("open");
function openReport(id) {
  const r = reportsCache.find((x) => String(x.id) === String(id));
  if (!r) return;
  $("#drawer-title").textContent = `${r.username} — ${r.question_slug}`;
  $("#drawer-body").textContent = r.narrative;
  $("#drawer").classList.add("open");
}

// --- rendering -----------------------------------------------------------
function table(rows, cols, opts = {}) {
  if (!rows.length) return `<p class="dim">Nothing yet.</p>`;
  const head = cols.map(([, label]) => `<th>${label}</th>`).join("");
  const body = rows.map((r) => {
    const attr = opts.rowId ? ` data-id="${esc(r[opts.rowId])}" class="clickable"` : "";
    const tds = cols.map(([k, , fmt]) =>
      `<td>${fmt ? fmt(r[k], r) : esc(r[k])}</td>`).join("");
    return `<tr${attr}>${tds}</tr>`;
  }).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

const short = (v) => esc(String(v ?? "").replace(/_/g, " ").toLowerCase());
const badge = (v) => `<span class="badge">${short(v)}</span>`;
const when = (v) => esc(String(v ?? "").replace("T", " ").replace("+00:00", ""));

// --- setup checklist -----------------------------------------------------
async function refreshSetup() {
  let st;
  try { st = await (await fetch("/api/setup")).json(); }
  catch { return; }

  const steps = [
    { ok: st.chrome_found, title: "Chrome installed",
      done: "Found on this machine",
      todo: "Chrome was not found in the usual locations" },
    { ok: st.browser_running, title: "Browser running",
      done: "Listening on the debugging port",
      todo: "Not running — the scan cannot attach to anything",
      action: st.chrome_found && !st.browser_running
        ? { label: "Start browser", id: "start-browser" } : null },
    { ok: !!st.signed_in_as, title: "Signed in to LeetCode",
      done: `Signed in as ${st.signed_in_as || ""}`,
      todo: st.browser_running
        ? "Sign in yourself in the Chrome window that opened, then re-check"
        : "Start the browser first",
      action: st.browser_running && !st.signed_in_as
        ? { label: "Re-check", id: "recheck" } : null },
    { ok: !st.dry_run, title: "Live reporting", warn: true,
      done: "ON — every scan files reports to LeetCode",
      todo: "Off — reports are composed and stored, nothing is sent. " +
            "Set  dry_run = false  under [safety] in config.toml." },
  ];

  const ready = steps.slice(0, 3).every((s) => s.ok);
  // Once live, the reporting row stays visible and loud: it is the one state
  // where a scan does something irreversible.
  $("#setup").className = "setup" + (ready ? " ready" : "") +
                          (st.dry_run ? "" : " live");
  $("#setup").innerHTML =
    (ready ? "" : `<p class="setup-head">Before scanning</p>`) +
    steps.map((s) => `
      <div class="step ${s.ok ? "ok" : (s.warn ? "off" : "todo")}">
        <span class="dot">${s.ok ? "✓" : (s.warn ? "○" : "!")}</span>
        <span class="step-text">
          <b>${esc(s.title)}</b>
          <span class="dim">${esc(s.ok ? s.done : s.todo)}</span>
        </span>
        ${s.action ? `<button id="${s.action.id}">${esc(s.action.label)}</button>` : ""}
      </div>`).join("");

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
  const dry = cfg.safety.dry_run;
  $("#mode").textContent = dry ? "dry run" : "live reporting";
  $("#mode").className = "pill" + (dry ? "" : " live");

  const st = await (await fetch("/api/stats")).json();
  // Every number here is counted from the stored rows, so a stopped or failed
  // scan adds nothing and rescanning a contest does not inflate anything.
  $("#stats").innerHTML = [
    ["Caught", st.cheating_submissions_caught, "big"],
    ["Reports sent", st.reports_submitted, dry ? "muted" : ""],
    ["Suspicious", st.suspicious_recorded],
    ["Contestants scanned", st.contestants_scanned],
    ["Submissions inspected", st.submissions_scanned],
    ["Contests scanned", st.contests_scanned],
  ].map(([label, value, cls]) =>
    `<div class="stat ${cls || ""}"><span class="n">${value ?? 0}</span>` +
    `<span class="l">${label}</span></div>`).join("");

  // Contestants: one row per username, the view you actually read.
  const users = await (await fetch("/api/by-user")).json();
  $("#users").innerHTML =
    `<p class="dim note">${users.length} contestant(s) with at least one report. ` +
    `Grouping is for display only — no verdict uses a contestant's past.</p>` +
    table(users, [
      ["username", "Contestant", (v) => `<a href="https://leetcode.com/u/${encodeURIComponent(v)}/" target="_blank" rel="noopener">${esc(v)}</a>`],
      ["submissions", "Caught"],
      ["contests", "Contests"],
      ["sent", "Sent"],
      ["reasons", "Reasons", (v) => String(v || "").split(",").map(badge).join(" ")],
      ["last_seen", "Last", when],
    ]);

  reportsCache = await (await fetch("/api/reports")).json();
  $("#reports").innerHTML =
    `<p class="dim note">Click a row to read the exact report text.</p>` +
    table(reportsCache, [
      ["username", "Contestant"],
      ["question_slug", "Problem", (v) => esc(String(v).slice(0, 34))],
      ["reason_code", "Reason", badge],
      ["score", "Score"],
      ["outcome", "Outcome", badge],
      ["created_at", "When", when],
    ], { rowId: "id" });
  $("#reports").querySelectorAll("tr.clickable").forEach((tr) => {
    tr.onclick = () => openReport(tr.dataset.id);
  });

  $("#scans").innerHTML = table(await (await fetch("/api/scans")).json(), [
    ["contest_slug", "Contest"],
    ["started_at", "Started", when],
    ["ranks_scanned", "Contestants"],
    ["submissions_seen", "Inspected"],
    ["flagged", "Flagged"],
    ["reported", "Reported"],
    ["status", "Status", badge],
  ]);
}

refresh();
