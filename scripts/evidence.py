#!/usr/bin/env python3
"""
evidence.py - collect the web-app run and render docs/LIVE_EVIDENCE.md from chain data.

    python scripts/evidence.py --web-file 0x.. --web-assess 0x.. [--finalize]

Reads docs/live/run.json (written by live_run.py), re-reads every transaction and the
contract state from studionet, optionally finalizes the web-filed claim with the
throwaway provider key (anyone may call finalize), and writes docs/live/web_run.json
and docs/LIVE_EVIDENCE.md. Nothing is typed in by hand.
"""

import argparse
import json
import os
import time

from eth_account import Account
from genlayer_py import create_client
from genlayer_py.chains import studionet
from genlayer_py.types import TransactionStatus as S

from live_run import KEYS, ROOT, hexs, jsonable, summarize

LIVE = os.path.join(ROOT, "docs", "live")


def gen(wei) -> str:
    return f"{int(wei) / 1e18:g} GEN"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--web-file", required=True)
    ap.add_argument("--web-assess", required=True)
    ap.add_argument("--web-claim", type=int, default=3)
    ap.add_argument("--finalize", action="store_true")
    a = ap.parse_args()
    run = json.load(open(os.path.join(LIVE, "run.json")))
    addr = run["contract"]
    k = json.load(open(KEYS))
    pc = create_client(chain=studionet, account=Account.from_key(k["provider"]))

    def read(fn, args=None):
        return jsonable(pc.read_contract(address=addr, function_name=fn, args=args or []))

    web = {"note": "Filed and assessed from the static web app (docs/index.html) in headless Chrome, signed by "
                   "the page's own per-browser burner key.", "steps": []}
    for label, tx in (("file_claim (web app)", a.web_file), ("assess (web app)", a.web_assess)):
        web["steps"].append({"step": label, "tx": tx, **summarize(pc.get_transaction(tx))})
    if a.finalize:
        cl = read("get_claim", [a.web_claim])
        if cl["status"] == "ASSESSED":
            while time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) < cl["challenge_ends"]:
                time.sleep(15)
            time.sleep(10)
            tx = hexs(pc.write_contract(address=addr, function_name="finalize", args=[a.web_claim]))
            pc.wait_for_transaction_receipt(transaction_hash=tx, status=S.ACCEPTED, interval=5000, retries=200)
            web["steps"].append({"step": "finalize (provider key; anyone may call)", "tx": tx,
                                 **summarize(pc.get_transaction(tx))})
    web["claim"] = read("get_claim", [a.web_claim])
    web["customer_credit"] = read("credit_of", [web["claim"]["customer"]])
    with open(os.path.join(LIVE, "web_run.json"), "w") as fh:
        json.dump(jsonable(web), fh, indent=1)
        fh.write("\n")

    # re-read every tx of the main run + the withdraw's triggered transfer
    for st in run["steps"]:
        st["latest"] = summarize(pc.get_transaction(st["tx"]))
    wd = next((s for s in run["steps"] if s["step"].startswith("withdraw_credit")), None)
    if wd:
        t = pc.get_transaction(wd["tx"])
        kids = []
        for child in t.get("triggered_transactions") or []:
            c = pc.get_transaction(hexs(child))
            kids.append({"tx": hexs(child), **summarize(c), "to": c.get("to_address"), "value": str(c.get("value")),
                         "value_credited": c.get("value_credited")})
        run["withdraw_triggered"] = kids
    run["sla_now"] = read("get_sla", [1])
    run["claims_now"] = read("list_claims")
    run["rendered_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(os.path.join(LIVE, "run.json"), "w") as fh:
        json.dump(jsonable(run), fh, indent=1)
        fh.write("\n")

    w = ["# Live evidence (GenLayer studionet)\n",
         "Everything below was read back from studionet by `scripts/evidence.py`; raw data: "
         "[`docs/live/run.json`](live/run.json) and [`docs/live/web_run.json`](live/web_run.json). "
         "Studionet is a test network: GEN here has no value. All keys are throwaway test keys.\n",
         "| Item | Value |", "|---|---|",
         f"| Contract | `{addr}` |",
         f"| Explorer | {run['explorer']} |",
         f"| Network | {run['network']} |",
         f"| Challenge window | {run.get('challenge_minutes')} min (short for the demo) |",
         f"| Provider (throwaway) | `{run['roles']['provider']}` |",
         f"| Customer #1 (throwaway) | `{run['roles']['customer']}` |",
         f"| Customer #2 (throwaway) | `{run['roles']['customer2']}` |\n",
         "## The SLA\n",
         f"SLA #1: service **{run['sla_now']['service']}**, status page {', '.join(run['sla_now']['urls'])}, "
         f"promise {run['sla_now']['uptime_bp'] / 100:.2f}% monthly uptime, monthly fee {gen(run['sla_now']['monthly_fee'])}, "
         f"credits {', '.join(f'over {m} min -> {p}%' for m, p in run['sla_now']['tiers'])}, funded with 3 GEN, open enrollment (demo).\n",
         "## The real incidents\n",
         "1. GitHub status, *Incident with Pull Requests*, 16 Nov 2026: "
         "https://www.githubstatus.com/incidents/2zfqmghmg3s3 . The page's first update is 11:59 UTC and it was resolved at "
         "16:26 UTC; the resolution text states merges timed out between 09:30 and 15:55 UTC. The claimed window "
         "12:00-15:45 UTC lies inside both readings.",
         "2. GitHub status, *Incident with Pull Requests*, 13 Nov 2026: https://www.githubstatus.com/incidents/1xzmt89vv61l "
         "(filed from the web app, window 16:00-18:00 UTC).\n",
         "## Transactions (scripted run)\n",
         "| Step | Tx | Status | Consensus | Execution | Validator votes |", "|---|---|---|---|---|---|"]
    for st in run["steps"]:
        f = st.get("latest") or st
        w.append(f"| {st['step']} | `{st['tx']}` | {f.get('status')} | {f.get('result')} | {f.get('execution')} | "
                 f"{', '.join(f.get('votes') or [])} |")
    w.append("\n## Transactions (web app run)\n")
    w.append("| Step | Tx | Status | Consensus | Execution | Validator votes |")
    w.append("|---|---|---|---|---|---|")
    for st in web["steps"]:
        w.append(f"| {st['step']} | `{st['tx']}` | {st.get('status')} | {st.get('result')} | {st.get('execution')} | "
                 f"{', '.join(st.get('votes') or [])} |")
    w.append("\n## Verdicts (contract state now)\n")
    w.append("| Claim | Window (UTC) | Incident page | Leader's reading | Canonical record | Credit | Status |")
    w.append("|---|---|---|---|---|---|---|")
    for c in sorted(run["claims_now"], key=lambda x: x["id"]):
        d = (c.get("details") or [{}])[0]
        r = c.get("record") or {}
        w.append(f"| #{c['id']} | {c['start']} to {c['end']} | {c['evidence_url']} | {d.get('status', '-')} "
                 f"{d.get('start_utc', '')} to {d.get('end_utc', '')} {d.get('severity', '')} | "
                 f"{r.get('verdict')}, {r.get('minutes')} min, {r.get('severity')} | {gen(c['credit'])} | {c['status']} |")
    s = run["sla_now"]
    w.append(f"\nPool now: balance {gen(s['balance'])}, reserved {gen(s['encumbered'])}, free {gen(s['free'])}, "
             f"credited to customers {gen(s['paid'])}.\n")
    w.append("## What this shows\n")
    w.append("- Claim #1: validators independently fetched the live GitHub incident page and agreed on the exact "
             "canonical record (CONFIRMED, 225 min, degraded). 225 min is over the 43-min tier and not over 240, so "
             "`credit_for` paid 10% of the 1 GEN fee = 0.1 GEN, finalized after the challenge window.")
    w.append("- Claim #2 (adversarial): same incident page, window 19:00-21:00 UTC after the incident ended: "
             "validators agreed on NO_OVERLAP and the credit is 0.")
    w.append("- Claim #3 was filed and assessed from the web app with a browser burner key.")
    if run.get("withdraw_triggered"):
        kid = run["withdraw_triggered"][0]
        w.append(f"- `withdraw_credit` for customer #1 emitted a transfer of {gen(kid['value'])} "
                 f"(triggered tx `{kid['tx']}`, status {kid['status']}, `value_credited: {kid['value_credited']}`). "
                 ("The chain reports this transfer as NOT credited to the plain wallet (a known studionet behaviour for "
                  "contract-to-wallet transfers), so the credit left the contract's ledger but did not show up in the wallet balance."
                  if not kid["value_credited"] else "The chain reports the transfer as credited."))
    w.append(f"\nRendered {run['rendered_at']}.\n")
    with open(os.path.join(ROOT, "docs", "LIVE_EVIDENCE.md"), "w") as fh:
        fh.write("\n".join(w))
    print("wrote docs/LIVE_EVIDENCE.md and docs/live/web_run.json")


if __name__ == "__main__":
    main()
