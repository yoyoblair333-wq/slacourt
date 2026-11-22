# SLA Court

Parametric SLA credits for internet and cloud outages, decided by GenLayer validator consensus.

A provider (or a reseller) funds a credit pool and registers an SLA. When a customer files a claim for an incident window, every GenLayer validator reads the provider's own public status page, and they must agree on one exact incident record. A fixed schedule in plain code turns that record into a credit. No ticket queue, no argument about whether the outage "counts".

- Live app: https://yoyoblair333-wq.github.io/slacourt/
- Live contract (studionet): `0x8C75bF4119BA8ae6875E62705Bde3bDAb7DF5f2a`
- Live evidence: [docs/LIVE_EVIDENCE.md](docs/LIVE_EVIDENCE.md)

## Who it is for

- **Businesses that pay for internet, hosting or cloud services** and are owed SLA credits after outages, but rarely claim them because the process is manual and the provider decides.
- **Resellers and managed-service providers** who promise their own customers an SLA on top of someone else's service, and want a credit process that is automatic, funded up front and checkable.

## How it works

1. **Register.** The provider calls `register_sla` with: service name (e.g. `Pull Requests`), region, 1 to 3 public status-page URLs, monthly uptime promise in basis points (`9990` = 99.90 %), the monthly fee, and a credit schedule such as `[[43,10],[240,25]]` (over 43 min: 10 % of the fee; over 240 min: 25 %). The value sent with the call funds the pool. `top_up` adds funds; `withdraw` takes back only unreserved funds.
2. **File.** A customer calls `file_claim(sla_id, start, end, region, evidence_url)` with a UTC window (`YYYY-MM-DDTHH:MMZ`). `evidence_url` is optional; if given it must be on the same host as a registered status page (e.g. one incident page on that status site).
3. **Assess (consensus).** Anyone calls `assess`. Each validator fetches the page(s) itself, its model reports the incident's start, end and severity, and deterministic code reduces that to the canonical record. The credit is computed and reserved in the pool.
4. **Challenge window.** For `challenge_minutes` (set at deploy) the customer or the provider can `appeal` once; the consensus round runs again and the window restarts.
5. **Finalize.** After the window, anyone calls `finalize`. The reserved credit moves from the pool to the customer's credit balance; `withdraw_credit` sends it.

## How consensus is used (exactly what validators compare)

Each validator, on its own copy of the page:

1. Fetches the page. Not 2xx, too large, not HTML/text, or empty: the source is `UNREADABLE`.
2. Checks deterministically that the service name (and the region, unless `global`) appears in the page text. If not: `NO_INCIDENT`.
3. Asks its model for `{"status", "start_utc", "end_utc", "severity"}` (status one of `FOUND`, `NOT_FOUND`, `AMBIGUOUS`, `UNREADABLE`; severity `degraded` or `outage`). An unparseable reply is treated as `AMBIGUOUS`.
4. Reduces that with code (`canonicalize`) to the **canonical record**:

```json
{"verdict": "CONFIRMED | NO_OVERLAP | NO_INCIDENT | AMBIGUOUS | UNREADABLE",
 "overlaps": true,
 "minutes": 225,
 "severity": "degraded | outage | none"}
```

`minutes` is the overlap between the incident and the claimed window, **rounded down to 15 minutes**. With several sources, `combine` requires every `CONFIRMED` source to match exactly, otherwise the result is `AMBIGUOUS`.

The validator accepts the leader's result only if its own canonical record is **exactly equal** on all four fields (`mine == leader["record"]`). There is no tolerance band: we never accept two different values that could lead to two different payouts. The model's raw timestamps are not compared; they only feed the deterministic reduction. Because the claimed window clips the incident, two honest readings of a page (for example "first update 11:59 to resolved 16:26" versus the stated impact window "09:30 to 15:55") give the same canonical record whenever the claimed window lies inside both, which is what happened in the live run.

The payout is `credit_for(record, tiers, min_severity, monthly_fee)`: the highest tier whose threshold the confirmed minutes exceed, as a percentage of the monthly fee, and 0 unless the verdict is `CONFIRMED` and the severity is at least `min_severity`. The model never sees the schedule or the fee.

**Fail closed:** an unreadable page, a page that does not name the service, an unclear or unparseable model reply, or sources that disagree all give a non-`CONFIRMED` verdict and a credit of 0. Validators that cannot agree produce no decision at all, and nothing is reserved or paid.

## State design

- `SLA`: provider, service, region, status-page URLs, `uptime_bp`, `monthly_fee`, `tiers`, `min_severity`, `open_enrollment`, and the pool: `balance`, `encumbered` (reserved for assessed, unfinalized claims), `paid`.
- `Claim`: SLA, customer, window, region, evidence URL, status (`FILED`, `ASSESSED`, `FINAL`), canonical record, credit, `capped`, appeals used, timestamps. The leader's per-source reading is stored next to it for transparency.
- `credits[customer]`: finalized credit waiting to be withdrawn.

Pool rules: a reservation is `min(credit, balance - encumbered)`, so the pool cannot go negative (`capped` marks a claim the pool could not fully cover). An appeal releases the old reservation before making the new one. The provider can withdraw only `balance - encumbered`.

One claim per incident per customer: the same incident page cannot be claimed twice by one customer, and one customer's windows on one SLA must be at least 24 h apart (so an incident cannot be split into several smaller claims). The provider cannot claim on its own SLA. With `open_enrollment = False`, only customers the provider `enroll`s can claim.

## Quickstart

```bash
pip install -r requirements-dev.txt          # genlayer-test, genvm-linter, pytest, genlayer-py
genvm-lint check contracts/sla_court.py      # lint
pytest tests/direct -q                       # 68 direct-mode tests

# live run on studionet (free throwaway keys, kept in .slacourt/, gitignored)
python scripts/live_run.py                   # deploy, register, file, assess, finalize, withdraw
python scripts/evidence.py --web-file 0x.. --web-assess 0x..   # re-read chain, render docs/LIVE_EVIDENCE.md

# web app (GitHub Pages serves /docs)
cd web && npm install && npm run build       # bundles web/app.src.js -> docs/app.js
```

## Tests

`tests/direct/test_sla_court.py` runs the contract in the real GenVM Python SDK (direct mode) with status pages and the model mocked. It covers registration checks, the full claim → assess → window → finalize → withdraw flow, tier boundaries and the 15-minute floor, and the adversarial cases: window outside any incident (0), unreadable page (0), page that does not name the service (0), bad or ambiguous model replies (0), conflicting sources (`AMBIGUOUS`), duplicate and split claims rejected, provider cannot withdraw reserved funds, pool cannot overdraw (second claim capped), the appeal flow, and consensus: `run_validator` replays a validator that read different minutes or severity, could not read the page, or got a forged leader result, and checks that it disagrees.

## Live evidence

On studionet the contract assessed a real GitHub status incident (*Incident with Pull Requests*, 16 Nov 2026, https://www.githubstatus.com/incidents/2zfqmghmg3s3). Validators agreed on `CONFIRMED, 225 min, degraded` for the claimed window 12:00-15:45 UTC, the schedule paid 10 % of a 1 GEN fee (0.1 GEN) after the challenge window, and a second claim on the same page for a window after the incident ended was agreed as `NO_OVERLAP` with 0 credit. A third claim was filed and assessed from the web app. Every transaction hash is in [docs/LIVE_EVIDENCE.md](docs/LIVE_EVIDENCE.md).

## Limitations

- Testnet only. GEN on studionet has no value. On studionet, the transfer that `withdraw_credit` sends to a plain wallet is reported as not credited to that wallet (see the live evidence); the contract ledger is correct.
- Credits are per incident, not aggregated over a calendar month, and the uptime promise is informational (it is shown, but the schedule decides the credit).
- Severity has two buckets. A page that is unclear about severity can make validators disagree, which means no decision rather than a wrong one.
- Status pages are written by the provider. SLA Court checks what the provider publicly admitted; it cannot see outages the provider never posted.
- Status pages whose incident list is loaded by JavaScript need a specific incident page as `evidence_url`.
- The web app signs with a burner key stored in the browser; it is for trying the testnet, not for holding funds.
- Not reviewed by an auditor.

## License

MIT, see [LICENSE](LICENSE).
