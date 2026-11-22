#!/usr/bin/env python3
"""
live_run.py - deploy SLA Court to GenLayer studionet and run one real end-to-end claim.

    python scripts/live_run.py [--contract 0x...] [--out docs/live/run.json]

Throwaway keys are created (and funded for free with sim_fundAccount) and kept in
.slacourt/keys.json, which is gitignored. Every value written to the output file is
what the chain returned; nothing is filled in by hand. Re-running resumes: steps
that already have a tx hash are not sent again.

The real incident: GitHub status, "Incident with Pull Requests", 16 Nov 2026
(https://www.githubstatus.com/incidents/2zfqmghmg3s3). The claimed window
12:00-15:45 UTC lies inside the incident under both readings of the page
(first update 11:59 to resolved 16:26, or the stated impact window).
"""

import argparse
import json
import os
import sys
import time

from eth_account import Account
from genlayer_py import create_account, create_client
from genlayer_py.chains import studionet
from genlayer_py.types import TransactionStatus as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = os.path.join(ROOT, ".slacourt", "keys.json")
WEI = 10**18
EXPLORER = "https://explorer-studio.genlayer.com"

SLA = {"service": "Pull Requests", "region": "global", "urls": ["https://www.githubstatus.com/history"],
       "uptime_bp": 9990, "monthly_fee": 1 * WEI, "tiers": "[[43,10],[240,25]]", "min_severity": "degraded",
       "open": True, "deposit": 3 * WEI}
CLAIMS = [
    {"label": "real incident, window inside it", "who": "customer",
     "start": "2026-11-16T12:00Z", "end": "2026-11-16T15:45Z",
     "evidence": "https://www.githubstatus.com/incidents/2zfqmghmg3s3"},
    {"label": "adversarial: window outside the incident", "who": "customer2",
     "start": "2026-11-16T19:00Z", "end": "2026-11-16T21:00Z",
     "evidence": "https://www.githubstatus.com/incidents/2zfqmghmg3s3"},
]


def say(*a):
    print(*a, flush=True)


def hexs(tx):
    h = tx.hex() if hasattr(tx, "hex") else str(tx)
    return h if h.startswith("0x") else "0x" + h


def jsonable(x):
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (bytes, bytearray)):
        return "0x" + bytes(x).hex()
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)


def keys():
    os.makedirs(os.path.dirname(KEYS), exist_ok=True)
    if os.path.exists(KEYS):
        with open(KEYS) as fh:
            k = json.load(fh)
    else:
        k = {}
    for role in ("provider", "customer", "customer2"):
        if role not in k:
            k[role] = "0x" + bytes(create_account().key).hex()
    with open(KEYS, "w") as fh:
        json.dump(k, fh)
    return {r: Account.from_key(v) for r, v in k.items()}


def submit(send, attempts=5):
    for i in range(attempts):
        try:
            return send()
        except Exception as e:
            if i == attempts - 1:
                raise
            say(f"  submit failed ({str(e)[:140]}); retrying in 10s")
            time.sleep(10)


def summarize(t):
    cd = t.get("consensus_data") or {}
    votes = sorted((cd.get("votes") or {}).values())
    lr = cd.get("leader_receipt")
    lr = lr[0] if isinstance(lr, list) and lr else (lr or {})
    blob = json.dumps(jsonable(t))
    err = None
    i = blob.find("[EXPECTED]")
    if i >= 0:
        err = blob[i:i + 160].split('"')[0].split("\\")[0]
    return {"status": t.get("status_name"), "result": t.get("result_name"),
            "execution": lr.get("execution_result"), "votes": votes, "error": err}


def wait(client, tx, until=S.ACCEPTED):
    client.wait_for_transaction_receipt(transaction_hash=tx, status=until, interval=5000, retries=360)
    return client.get_transaction(tx)


class Run:
    def __init__(self, path):
        self.path = path
        self.s = json.load(open(path)) if os.path.exists(path) else {}
        self.s.setdefault("network", "studionet (chain 61999, https://studio.genlayer.com/api)")
        self.s.setdefault("steps", [])

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as fh:
            json.dump(jsonable(self.s), fh, indent=1)
            fh.write("\n")

    def do(self, client, label, send):
        for st in self.s["steps"]:
            if st["step"] == label and st.get("tx"):
                say(f"[skip] {label}: {st['tx']}")
                return st
        say(f"[send] {label}")
        tx = hexs(submit(send))
        st = {"step": label, "tx": tx, "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self.s["steps"].append(st)
        self.save()
        t = wait(client, tx)
        st.update(summarize(t))
        self.save()
        say(f"  {tx} {st['status']} {st['result']} exec={st['execution']} votes={st['votes']} err={st['error']}")
        return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract")
    ap.add_argument("--challenge-minutes", type=int, default=3)
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "live", "run.json"))
    a = ap.parse_args()
    k = keys()
    run = Run(a.out)
    clients = {r: create_client(chain=studionet, account=acct) for r, acct in k.items()}
    run.s["roles"] = {r: acct.address for r, acct in k.items()}
    for r, acct in k.items():
        if not run.s.get("funded_" + r):
            clients[r].fund_account(acct.address, 20 * WEI)
            run.s["funded_" + r] = True
    run.save()
    pc = clients["provider"]

    addr = a.contract or run.s.get("contract")
    if not addr:
        code = open(os.path.join(ROOT, "contracts", "sla_court.py"), encoding="utf-8").read()
        st = run.do(pc, "deploy", lambda: pc.deploy_contract(code=code, args=[a.challenge_minutes]))
        r = pc.get_transaction_receipt(transaction_hash=st["tx"]) if hasattr(pc, "get_transaction_receipt") else None
        t = pc.get_transaction(st["tx"])
        addr = (t.get("data") or {}).get("contract_address") or t.get("recipient") or t.get("to_address")
        if not addr and r:
            addr = (r.get("data") or {}).get("contract_address")
        run.s["contract"] = addr
        run.s["challenge_minutes"] = a.challenge_minutes
        run.save()
    run.s["explorer"] = f"{EXPLORER}/address/{addr}"
    say("contract", addr)

    def read(fn, args=None):
        return pc.read_contract(address=addr, function_name=fn, args=args or [])

    if read("stats")["slas"] < 1:
        run.do(pc, "register_sla (fund 3 GEN)", lambda: pc.write_contract(
            address=addr, function_name="register_sla", value=SLA["deposit"],
            args=[SLA["service"], SLA["region"], SLA["urls"], SLA["uptime_bp"], SLA["monthly_fee"], SLA["tiers"],
                  SLA["min_severity"], SLA["open"]]))
    run.s["sla_after_register"] = read("get_sla", [1])
    run.save()

    for i, c in enumerate(CLAIMS):
        cc = clients[c["who"]]
        run.do(cc, f"file_claim #{i + 1} ({c['label']})", lambda c=c, cc=cc: cc.write_contract(
            address=addr, function_name="file_claim", args=[1, c["start"], c["end"], "", c["evidence"]]))
    for i, c in enumerate(CLAIMS):
        cc = clients[c["who"]]
        run.do(cc, f"assess #{i + 1} (consensus)", lambda i=i, cc=cc: cc.write_contract(
            address=addr, function_name="assess", args=[i + 1]))
        run.s.setdefault("claims_after_assess", {})[str(i + 1)] = read("get_claim", [i + 1])
        run.save()

    # wait out the challenge window, then finalize both
    for i, c in enumerate(CLAIMS):
        cl = read("get_claim", [i + 1])
        if cl["status"] != "ASSESSED":
            continue
        ends = cl["challenge_ends"]
        while time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) < ends:
            say(f"  waiting for challenge window to close at {ends}")
            time.sleep(20)
        time.sleep(15)
        cc = clients[c["who"]]
        run.do(cc, f"finalize #{i + 1}", lambda i=i, cc=cc: cc.write_contract(
            address=addr, function_name="finalize", args=[i + 1]))
    run.s["claims_final"] = {str(i + 1): read("get_claim", [i + 1]) for i in range(len(CLAIMS))}
    cust = k["customer"].address
    run.s["credit_before_withdraw"] = read("credit_of", [cust])
    if int(run.s["credit_before_withdraw"]) > 0:
        run.do(clients["customer"], "withdraw_credit #1", lambda: clients["customer"].write_contract(
            address=addr, function_name="withdraw_credit", args=[]))
    run.s["credit_after_withdraw"] = read("credit_of", [cust])
    run.s["sla_final"] = read("get_sla", [1])
    run.s["stats"] = read("stats")
    # refresh every tx's final status
    for st in run.s["steps"]:
        try:
            st["latest"] = summarize(pc.get_transaction(st["tx"]))
        except Exception as e:
            st["latest"] = {"error": str(e)[:120]}
    run.s["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    run.save()
    say("wrote", a.out)


if __name__ == "__main__":
    main()
