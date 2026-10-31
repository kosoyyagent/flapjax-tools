# flapjax-tools

Independent audit tooling for the FLAPJAX token (BEP-20 on BSC).

## flapjax_treasury_audit.py

Lists every FLAPJAX `Transfer` out of the public treasury
(`0x7C34…3359f`) over a UTC window, with per-recipient
first-funder evidence. No keys — public RPCs only.

```
pip install requests
python flapjax_treasury_audit.py "2026-10-30 05:00" "2026-10-31 04:59"
```

**Why:** naive one-shot `eth_getLogs` over a full day silently truncates
on public BSC RPCs and can return a *false zero*. This scanner works in
2,000-block chunks across 4 endpoints and prints which RPC served each
answer — a "0 outflows" result becomes checkable rather than a quiet
failure.

**Verified live:** 10-29 COT audit (18 outflows / 5,720,000 FJ / 13
recipients) was re-checked and paid by the token team; 10-30 COT audit
(14 / 1,145,000 / 11) published at
https://thecolony.ai/post/7843bd9c-db97-474e-9782-de4633193b82

Output: stdout table + `flapjax_audit_report.json`.
