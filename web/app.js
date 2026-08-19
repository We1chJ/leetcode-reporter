const $ = (s) => document.querySelector(s);
const logbody = $("#logbody");

function line(text, cls = "") {
  const t = new Date().toLocaleTimeString();
  logbody.innerHTML += `<span class="dim">${t}</span> <span class="${cls}">${text}</span>\n`;
  logbody.parentElement.scrollTop = 1e9;
}

// --- live event stream ---------------------------------------------------
const es = new EventSource("/api/stream");
es.onmessage = (m) => {
  const ev = JSON.parse(m.data);
  if (ev.type === "log") line(ev.msg, ev.level === "warn" ? "warn" : ev.level === "error" ? "error" : "");
  else if (ev.type === "progress") $("#status").textContent = `rank ${ev.rank} — ${ev.user}`;
  else if (ev.type === "scan_start") line(`Scan started: ${ev.contest}${ev.dry_run ? " (dry run)" : ""}`, "warn");
  else if (ev.type === "report") line(`REPORT ${ev.user} / ${ev.question} — ${ev.reason} (${ev.score}) → ${ev.outcome}`, "good");
  else if (ev.type === "scan_end") {
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

// --- tables --------------------------------------------------------------
function table(rows, cols) {
  if (!rows.length) return `<p class="dim">Nothing yet.</p>`;
  const head = cols.map(([, label]) => `<th>${label}</th>`).join("");
  const body = rows.map((r) =>
    `<tr>${cols.map(([k, , cls]) => `<td class="${cls || ""}">${r[k] ?? ""}</td>`).join("")}</tr>`
  ).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

async function refresh() {
  const cfg = await (await fetch("/api/config")).json();
  const dry = cfg.safety.dry_run;
  $("#mode").textContent = dry ? "dry run" : "live reporting";
  $("#mode").className = "pill" + (dry ? "" : " live");

  $("#offenders").innerHTML = table(await (await fetch("/api/offenders")).json(), [
    ["username", "User"], ["report_count", "Reports"],
    ["contest_count", "Contests"], ["first_seen", "First seen"],
    ["last_seen", "Last seen"],
  ]);
  $("#reports").innerHTML = table(await (await fetch("/api/reports")).json(), [
    ["username", "User"], ["contest_slug", "Contest"],
    ["question_slug", "Problem"], ["reason_code", "Reason"],
    ["score", "Score"], ["outcome", "Outcome"],
    ["narrative", "Narrative", "narrative"],
  ]);
  $("#scans").innerHTML = table(await (await fetch("/api/scans")).json(), [
    ["contest_slug", "Contest"], ["started_at", "Started"],
    ["ranks_scanned", "Scanned"], ["flagged", "Flagged"],
    ["reported", "Reported"], ["status", "Status"],
  ]);
}

refresh();
