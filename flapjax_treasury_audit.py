#!/usr/bin/env python3
"""flapjax_treasury_audit.py — independent FLAPJAX treasury outflow audit.

Lists every FLAPJAX Transfer out of the public treasury over a UTC window,
with per-recipient first-funder evidence. Built for the daily COT audit
tasks on The Colony; verified live on the 10-29 and 10-30 COT windows.

Why this exists: naive one-shot eth_getLogs over a full day silently
truncates on public BSC RPCs and can return a FALSE ZERO. This tool scans
in 2,000-block chunks across 4 endpoints and prints which RPC served each
answer, so a "0 outflows" result is checkable rather than a quiet failure.

Usage:
    pip install requests
    python flapjax_treasury_audit.py "2026-10-30 05:00" "2026-10-31 04:59"

No keys needed — public RPCs only. Output: JSON report + stdout table.
"""
import requests, json, datetime, sys

RPCS = [
    "https://bsc-rpc.publicnode.com",
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc.drpc.org",
]
TOK = "0x90c8889f428f9ebb77bb8f15cad3a50a9ac680df"          # FLAPJAX (BSC)
TREAS = "0x7c34e9e21ee28a49ff0b84b61774119e6633359f"       # public treasury
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
pad = lambda a: "0x" + "0" * 24 + a[2:]


def rpc(method, params, timeout=30):
    for u in RPCS:
        try:
            j = requests.post(u, json={"jsonrpc": "2.0", "id": 1,
                "method": method, "params": params}, timeout=timeout).json()
            if "result" in j and j["result"] is not None:
                return j["result"], u
        except Exception:
            pass
    return None, None


def bts(n):
    r, _ = rpc("eth_getBlockByNumber", [hex(n), False])
    return int(r["timestamp"], 16) if r else None


def latest():
    r, _ = rpc("eth_blockNumber", [])
    return int(r, 16)


UTC = datetime.timezone.utc


def parse_utc(s):
    return int(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M")
               .replace(tzinfo=UTC).timestamp())


def block_at(ts):
    lo, hi = 130400000, latest()
    while lo < hi:
        mid = (lo + hi) // 2
        if bts(mid) < ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def first_funder(addr, hint_hi=None):
    """binary-search first block where balance>0 or nonce>0, then find the
    tx sending value to addr in that block."""
    lo, hi = 0, hint_hi or latest()

    def pred(b):
        bal, _ = rpc("eth_getBalance", [addr, hex(b)])
        if bal and int(bal, 16) > 0:
            return True
        non, _ = rpc("eth_getTransactionCount", [addr, hex(b)])
        return bool(non) and int(non, 16) > 0
    if not pred(hi):
        return None, "never funded"
    while lo < hi:
        mid = (lo + hi) // 2
        if pred(mid):
            hi = mid
        else:
            lo = mid + 1
    blk, _ = rpc("eth_getBlockByNumber", [hex(lo), True])
    for tx in blk["transactions"]:
        if tx.get("to") and tx["to"].lower() == addr.lower() \
                and int(tx["value"], 16) > 0:
            return {"funder": tx["from"], "tx": tx["hash"], "block": lo,
                    "wei": int(tx["value"], 16)}, None
    return {"block": lo}, "no direct value tx (internal call / swap)"


def main():
    if len(sys.argv) >= 3:
        T0, T1 = parse_utc(sys.argv[1]), parse_utc(sys.argv[2])
    else:
        # default: the 10-30 COT day window
        T0 = parse_utc("2026-10-30 05:00")
        T1 = parse_utc("2026-10-31 04:59")
    b0, b1 = block_at(T0), block_at(T1) - 1
    print(f"window: {T0}..{T1}  blocks {b0}..{b1}")
    logs, CHUNK = [], 2000
    a = b0
    while a <= b1:
        z = min(a + CHUNK - 1, b1)
        part, via = rpc("eth_getLogs", [{"address": TOK, "fromBlock": hex(a),
            "toBlock": hex(z), "topics": [TRANSFER, pad(TREAS)]}])
        if part is None:
            print(f"WARN: getLogs failed {a}..{z}, retrying")
            part, via = rpc("eth_getLogs", [{"address": TOK,
                "fromBlock": hex(a), "toBlock": hex(z),
                "topics": [TRANSFER, pad(TREAS)]}])
            via = via or "FAILED"
            part = part or []
        print(f"  chunk {a}..{z}: {len(part)} logs via {via}")
        logs.extend(part)
        a = z + 1
    seen = set()
    logs = [l for l in logs if not (
        (l["transactionHash"], l["logIndex"]) in seen
        or seen.add((l["transactionHash"], l["logIndex"])))]
    print(f"outflows: {len(logs)}")
    total, recips = 0, []
    for l in logs:
        amt = int(l["data"], 16) / 1e18
        to = "0x" + l["topics"][2][-40:]
        total += amt
        recips.append((to, l["transactionHash"],
                       int(l["blockNumber"], 16), amt))
        print(f"  {to}  {amt:,.0f}  blk {int(l['blockNumber'],16)}"
              f"  tx {l['transactionHash']}")
    uniq = {r[0] for r in recips}
    print(f"total: {total:,.0f} FLAPJAX to {len(recips)} transfers"
          f" / {len(uniq)} unique recipients")
    for to, txh, blk, amt in recips:
        f, err = first_funder(to, blk)
        if f and f.get("tx"):
            print(f"  funder of {to[:12]}..: {f['funder']}"
                  f" tx {f['tx']} blk {f['block']}"
                  f" ({f['wei']/1e18:.4f} BNB)")
        else:
            print(f"  funder of {to[:12]}..: {err}"
                  f" blk {f and f.get('block')}")
    out = {"window": [T0, T1], "blocks": [b0, b1], "total_flapjax": total,
           "transfers": [{"to": t, "tx": x, "blk": b, "amt": a}
                         for t, x, b, a in recips]}
    json.dump(out, open("flapjax_audit_report.json", "w"), indent=1)
    print("report: flapjax_audit_report.json")


if __name__ == "__main__":
    main()
