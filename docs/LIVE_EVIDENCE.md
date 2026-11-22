# Live evidence (GenLayer studionet)

Everything below was read back from studionet by `scripts/evidence.py`; raw data: [`docs/live/run.json`](live/run.json) and [`docs/live/web_run.json`](live/web_run.json). Studionet is a test network: GEN here has no value. All keys are throwaway test keys.

| Item | Value |
|---|---|
| Contract | `0x8C75bF4119BA8ae6875E62705Bde3bDAb7DF5f2a` |
| Explorer | https://explorer-studio.genlayer.com/address/0x8C75bF4119BA8ae6875E62705Bde3bDAb7DF5f2a |
| Network | studionet (chain 61999, https://studio.genlayer.com/api) |
| Challenge window | 3 min (short for the demo) |
| Provider (throwaway) | `0xdBAb9950c8Ee3F4F469c29B4750076640aE2d98a` |
| Customer #1 (throwaway) | `0xc73Ff5fb68a8A7A2b5A1643563D6A750C86Bc36b` |
| Customer #2 (throwaway) | `0x78f91B0AF2ed3d48AAe74E8Db32bfc566D98Aa2f` |

## The SLA

SLA #1: service **Pull Requests**, status page https://www.githubstatus.com/history, promise 99.90% monthly uptime, monthly fee 1 GEN, credits over 43 min -> 10%, over 240 min -> 25%, funded with 3 GEN, open enrollment (demo).

## The real incidents

1. GitHub status, *Incident with Pull Requests*, 16 Nov 2026: https://www.githubstatus.com/incidents/2zfqmghmg3s3 . The page's first update is 11:59 UTC and it was resolved at 16:26 UTC; the resolution text states merges timed out between 09:30 and 15:55 UTC. The claimed window 12:00-15:45 UTC lies inside both readings.
2. GitHub status, *Incident with Pull Requests*, 13 Nov 2026: https://www.githubstatus.com/incidents/1xzmt89vv61l (filed from the web app, window 16:00-18:00 UTC).

## Transactions (scripted run)

| Step | Tx | Status | Consensus | Execution | Validator votes |
|---|---|---|---|---|---|
| deploy | `0x58e4fa2a0efc621fd59d1845073980853c7b415488d4dfd024e6479cf10b2dbd` | FINALIZED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, idle, idle |
| register_sla (fund 3 GEN) | `0xde618588468ee15e6d3a9ba70589ab01e82702c14f5668fa6e873d0205155d34` | FINALIZED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, idle, idle |
| file_claim #1 (real incident, window inside it) | `0xd7abafc72dd45d7cd652839b913204625d5c3b5bf06248d3aff36dd1c9b9429c` | FINALIZED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, idle, idle |
| file_claim #2 (adversarial: window outside the incident) | `0x94fce436418ca17392db40b6553ee1d82f99e9d79e08b3adb788688b802ca6d5` | FINALIZED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, agree, idle |
| assess #1 (consensus) | `0x8a58935f7d4ddd2a3274f678fbe58236d35b29db640f2be26eb2588c955defa2` | FINALIZED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, idle, idle |
| assess #2 (consensus) | `0x086a3f69276ccc0de66894a23ac00171d9feb7723f8d83b49a1a9ce08d1baedc` | FINALIZED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, idle |
| finalize #1 | `0xde25d55fb890f96463dad01845171dab470815b1cbc8f9dd7cb864d13764a3f6` | FINALIZED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, idle, idle |
| finalize #2 | `0x4b846b096d34b2f1acd7ffad35d886bfd942edf5946fed28a2bb8de48a211233` | FINALIZED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, agree, agree |
| withdraw_credit #1 | `0xdcc6784f8f27f5b59677f90915eb1a6b9c230c28ba808ad34a7d43ee2f62a2e6` | FINALIZED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, idle, idle |

## Transactions (web app run)

| Step | Tx | Status | Consensus | Execution | Validator votes |
|---|---|---|---|---|---|
| file_claim (web app) | `0xb513985f69891bbc8130f17f19a83b7f4521b88d74c2b54043be7ae22b74ed1c` | FINALIZED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, idle, idle |
| assess (web app) | `0x96fc756fa600689bdb925f8dcbaf3760395a9c70fc15778029d04e80011e3b34` | FINALIZED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, idle, idle |
| finalize (provider key; anyone may call) | `0x8a47f67923aa635fc60e6b6dbff427745f1ca4a15530db011624af6fb9b11c5e` | ACCEPTED | MAJORITY_AGREE | SUCCESS | agree, agree, agree, agree, agree |

## Verdicts (contract state now)

| Claim | Window (UTC) | Incident page | Leader's reading | Canonical record | Credit | Status |
|---|---|---|---|---|---|---|
| #1 | 2026-11-16T12:00Z to 2026-11-16T15:45Z | https://www.githubstatus.com/incidents/2zfqmghmg3s3 | FOUND 2026-11-16T09:30 to 2026-11-16T15:55 degraded | CONFIRMED, 225 min, degraded | 0.1 GEN | FINAL |
| #2 | 2026-11-16T19:00Z to 2026-11-16T21:00Z | https://www.githubstatus.com/incidents/2zfqmghmg3s3 | FOUND 2026-11-16T09:30 to 2026-11-16T15:55 degraded | NO_OVERLAP, 0 min, none | 0 GEN | FINAL |
| #3 | 2026-11-13T16:00Z to 2026-11-13T18:00Z | https://www.githubstatus.com/incidents/1xzmt89vv61l | FOUND 2026-11-13T15:47 to 2026-11-13T18:29 degraded | CONFIRMED, 120 min, degraded | 0.1 GEN | FINAL |

Pool now: balance 2.8 GEN, reserved 0 GEN, free 2.8 GEN, credited to customers 0.2 GEN.

## What this shows

- Claim #1: validators independently fetched the live GitHub incident page and agreed on the exact canonical record (CONFIRMED, 225 min, degraded). 225 min is over the 43-min tier and not over 240, so `credit_for` paid 10% of the 1 GEN fee = 0.1 GEN, finalized after the challenge window.
- Claim #2 (adversarial): same incident page, window 19:00-21:00 UTC after the incident ended: validators agreed on NO_OVERLAP and the credit is 0.
- Claim #3 was filed and assessed from the web app with a browser burner key.
- `withdraw_credit` for customer #1 emitted a transfer of 0.1 GEN (triggered tx `0x8d89dd7977fd0cc341d440afab9b1184b5ec9c6cfed923b5577989e4beb6c22d`, status FINALIZED, `value_credited: False`). The chain reports this transfer as NOT credited to the plain wallet (a known studionet behaviour for contract-to-wallet transfers), so the credit left the contract's ledger but did not show up in the wallet balance.

Rendered 2026-11-22T20:23:29Z.
