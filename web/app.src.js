// SLA Court web app. Reads the live studionet contract with genlayer-js and lets a visitor
// file / assess / finalize a claim with a per-browser burner key (testnet only, no real money).
import { createClient, createAccount, generatePrivateKey } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

export const CONTRACT = "0x8C75bF4119BA8ae6875E62705Bde3bDAb7DF5f2a";
const RPC = "https://studio.genlayer.com/api";
const EXPLORER = "https://explorer-studio.genlayer.com";
const KEY = "slacourt.studionet-burner.v1";
const WEI = 10n ** 18n;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const plain = (v) => {
  if (v instanceof Map) return Object.fromEntries([...v].map(([k, x]) => [k, plain(x)]));
  if (Array.isArray(v)) return v.map(plain);
  if (typeof v === "bigint") return Number(v) <= Number.MAX_SAFE_INTEGER ? Number(v) : v.toString();
  return v;
};
const gen = (wei) => {
  const w = BigInt(wei || 0);
  const whole = w / WEI, frac = (w % WEI).toString().padStart(18, "0").replace(/0+$/, "").slice(0, 4);
  return frac ? `${whole}.${frac} GEN` : `${whole} GEN`;
};
const short = (a) => (a ? a.slice(0, 6) + "…" + a.slice(-4) : "");

const reader = createClient({ chain: studionet });
let writer = null, account = null;

function burner() {
  let k = localStorage.getItem(KEY);
  if (!k) { k = generatePrivateKey(); localStorage.setItem(KEY, k); }
  account = createAccount(k);
  writer = createClient({ chain: studionet, account });
  $("me").textContent = account.address;
  return account;
}

async function read(fn, args = []) {
  return plain(await reader.readContract({ address: CONTRACT, functionName: fn, args }));
}

async function fund(addr) {
  // studionet test faucet (sim_fundAccount); free, testnet only.
  await fetch(RPC, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "sim_fundAccount", params: [addr, 10 * 1e18] }) }).catch(() => {});
}

async function send(fn, args, label) {
  const log = $("log");
  if (!writer) burner();
  log.textContent = `${label}: funding test key…`;
  await fund(account.address);
  log.textContent = `${label}: sending…`;
  try {
    const hash = await writer.writeContract({ address: CONTRACT, functionName: fn, args, value: 0n });
    log.innerHTML = `${esc(label)}: tx <code>${esc(hash)}</code> sent, waiting for validators (a consensus round can take a few minutes)…`;
    const r = await writer.waitForTransactionReceipt({ hash, status: "ACCEPTED", interval: 4000, retries: 200 });
    const res = r?.consensus_data?.leader_receipt?.[0]?.execution_result ?? r?.result_name ?? "";
    log.innerHTML = `${esc(label)}: tx <code>${esc(hash)}</code> accepted (${esc(res)}).`;
  } catch (e) {
    log.textContent = `${label} failed: ${String(e?.message || e).slice(0, 300)}`;
  }
  await refresh();
}

function tiersText(t) { return (t || []).map(([m, p]) => `over ${m} min → ${p}%`).join(", "); }

function slaCard(s) {
  return `<article class="card">
    <h3>#${s.id} · ${esc(s.service)} <span class="tag">${esc(s.region)}</span></h3>
    <dl>
      <dt>Promise</dt><dd>${(s.uptime_bp / 100).toFixed(2)}% monthly uptime (allows ${(s.allowed_downtime_min_x10 / 10).toFixed(1)} min / 30 days)</dd>
      <dt>Credits</dt><dd>${esc(tiersText(s.tiers))} of ${gen(s.monthly_fee)} monthly fee · min severity ${esc(s.min_severity)}</dd>
      <dt>Status pages</dt><dd>${s.urls.map((u) => `<a href="${esc(u)}" rel="noopener" target="_blank">${esc(u)}</a>`).join("<br>")}</dd>
      <dt>Pool</dt><dd><b class="gold">${gen(s.balance)}</b> · reserved ${gen(s.encumbered)} · free ${gen(s.free)} · credited ${gen(s.paid)}</dd>
      <dt>Provider</dt><dd><code>${esc(short(s.provider))}</code> · ${s.open_enrollment ? "open enrollment (demo)" : "enrolled customers only"} · ${s.claims} claim(s)</dd>
    </dl></article>`;
}

function claimRow(c, now) {
  const r = c.record || {};
  const mine = account && c.customer.toLowerCase() === account.address.toLowerCase();
  let act = "";
  if (c.status === "FILED") act = `<button data-act="assess" data-id="${c.id}">Assess</button>`;
  else if (c.status === "ASSESSED" && now >= c.challenge_ends) act = `<button data-act="finalize" data-id="${c.id}">Finalize</button>`;
  else if (c.status === "ASSESSED") act = `<span class="muted">window until ${esc(c.challenge_ends.slice(11, 16))} UTC</span>`;
  const d = (c.details || [])[0] || {};
  return `<tr>
    <td>#${c.id}${mine ? ' <span class="tag">you</span>' : ""}</td>
    <td>SLA #${c.sla_id}</td>
    <td>${esc(c.start)} → ${esc(c.end)}${c.evidence_url ? `<br><a href="${esc(c.evidence_url)}" target="_blank" rel="noopener">incident page</a>` : ""}</td>
    <td>${esc(c.status)}</td>
    <td><b class="${r.verdict === "CONFIRMED" ? "ok" : "no"}">${esc(r.verdict || "-")}</b>${r.verdict ? `<br><span class="muted">${r.minutes} min · ${esc(r.severity)}</span>` : ""}
      ${d.start_utc ? `<br><span class="muted">leader read ${esc(d.start_utc)}–${esc(d.end_utc)}</span>` : ""}</td>
    <td class="gold">${gen(c.credit)}${c.capped ? " (capped)" : ""}</td>
    <td>${act}</td></tr>`;
}

async function refresh() {
  try {
    const [stats, slas, claims] = await Promise.all([read("stats"), read("list_slas"), read("list_claims")]);
    $("stats").textContent = `${stats.slas} SLA(s) · ${stats.claims} claim(s) · challenge window ${stats.challenge_minutes} min · minutes rounded down to ${stats.round_to_minutes}`;
    $("slas").innerHTML = slas.map(slaCard).join("") || "<p class='muted'>No SLAs yet.</p>";
    const now = new Date().toISOString().slice(0, 19) + "Z";
    $("claims").innerHTML = claims.map((c) => claimRow(c, now)).join("") || "<tr><td colspan=7 class='muted'>No claims yet.</td></tr>";
    if (account) {
      const cr = await read("credit_of", [account.address]);
      $("credit").textContent = gen(cr);
      $("withdraw").disabled = BigInt(cr) <= 0n;
    }
  } catch (e) {
    $("stats").textContent = "Could not read the contract: " + String(e?.message || e).slice(0, 200);
  }
}

document.addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-act]");
  if (!b) return;
  const id = Number(b.dataset.id);
  send(b.dataset.act, [id], `${b.dataset.act} claim #${id}`);
});

$("claimform").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  const t = (v) => (v.length === 16 ? v + "Z" : v);
  send("file_claim", [Number(f.get("sla")), t(f.get("start")), t(f.get("end")), "", f.get("evidence") || ""], "file claim");
});
$("wallet").addEventListener("click", () => { burner(); refresh(); });
$("withdraw").addEventListener("click", () => send("withdraw_credit", [], "withdraw credit"));
$("addr").innerHTML = `<a href="${EXPLORER}/address/${CONTRACT}" target="_blank" rel="noopener"><code>${CONTRACT}</code></a>`;
if (localStorage.getItem(KEY)) burner();
refresh();
setInterval(refresh, 30000);
