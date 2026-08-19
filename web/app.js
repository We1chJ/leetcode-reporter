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
    line(`Scan ${ev.status}: ${ev.scanned} scanned, ${ev.flagged} flagged, ${ev.reported} reported`, "warn");
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

async function refresh() {
  const cfg = await (await fetch("/api/config")).json();
  const dry = cfg.safety.dry_run;
  $("#mode").textContent = dry ? "dry run" : "live reporting";
  $("#mode").className = "pill" + (dry ? "" : " live");

  const st = await (await fetch("/api/stats")).json();
  $("#stats").innerHTML = [
    ["Caught", st.cheating_submissions_caught, "big"],
    ["Reports sent", st.reports_submitted, dry ? "muted" : ""],
    ["Suspicious", st.suspicious_recorded],
    ["Submissions scanned", st.submissions_scanned],
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
    ["ranks_scanned", "Scanned"],
    ["flagged", "Flagged"],
    ["reported", "Reported"],
    ["status", "Status", badge],
  ]);
}

refresh();
