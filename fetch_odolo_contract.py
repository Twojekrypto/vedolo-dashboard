#!/usr/bin/env python3
"""
Fetch oDOLO contract data via Berachain RPC and save as static JSON.
Replicates the RPC calls the browser currently makes, but runs server-side
in GitHub Actions for reliability.
"""

import json
import os
import requests
from datetime import datetime, timezone

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(DATA_DIR, "odolo_contract_data.json")

ODOLO_TOKEN = "0x02E513b5B54eE216Bf836ceb471507488fC89543"
ODOLO_VESTER = "0x3E9b9A16743551DA49b5e136C716bBa7932d2cEc"

# Function selectors
SEL = {
    "totalSupply": "0x18160ddd",
    "balanceOf": "0x70a08231",
    "decimals": "0x313ce567",
    "promisedTokens": "0x5e17b694",
    "pushedTokens": "0x818c16e2",
    "availableTokens": "0x69bb4dc2",
}

RPC_URLS = [
    "https://rpc.berachain.com/",
    "https://berachain-rpc.publicnode.com/",
    "https://berachain.drpc.org/",
]

VESTER_PADDED = ODOLO_VESTER.replace("0x", "").lower().zfill(64)


def rpc_batch(url, calls, timeout=15):
    """Execute a batch of eth_call requests."""
    batch = []
    for i, (to, data) in enumerate(calls):
        batch.append({
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"],
            "id": i + 1
        })

    resp = requests.post(url, json=batch, timeout=timeout)
    resp.raise_for_status()
    results = resp.json()

    if isinstance(results, list):
        results.sort(key=lambda r: r.get("id", 0))
        return [r.get("result", "0x0") for r in results]

    # Single response (shouldn't happen with batch, but handle it)
    return [results.get("result", "0x0")]


def decode_uint256(hex_str):
    """Decode a hex string to integer."""
    if not hex_str or hex_str in ("0x", "0x0"):
        return 0
    clean = hex_str.replace("0x", "")[:64]
    return int(clean, 16) if clean else 0


def main():
    print("📡 Fetching oDOLO contract data via RPC...")

    for url in RPC_URLS:
        try:
            print(f"   Trying {url}...")

            # Batch 1: Token data
            batch1 = rpc_batch(url, [
                (ODOLO_TOKEN, SEL["totalSupply"]),
                (ODOLO_TOKEN, SEL["decimals"]),
                (ODOLO_TOKEN, SEL["balanceOf"] + VESTER_PADDED),
            ])

            # Batch 2: Vester data
            batch2 = rpc_batch(url, [
                (ODOLO_VESTER, SEL["promisedTokens"]),
                (ODOLO_VESTER, SEL["pushedTokens"]),
                (ODOLO_VESTER, SEL["availableTokens"]),
            ])

            decimals = decode_uint256(batch1[1]) or 18
            divisor = 10 ** decimals

            data = {
                "totalSupply": decode_uint256(batch1[0]) / divisor,
                "inVesterBalance": decode_uint256(batch1[2]) / divisor,
                "promisedTokens": decode_uint256(batch2[0]) / divisor,
                "pushedTokens": decode_uint256(batch2[1]) / divisor,
                "availableTokens": decode_uint256(batch2[2]) / divisor,
                "decimals": decimals,
                "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "rpc_source": url,
            }

            # Derived
            data["inCirculation"] = data["totalSupply"] - data["availableTokens"] - data["promisedTokens"]

            with open(OUTPUT_FILE, "w") as f:
                json.dump(data, f, indent=2)

            print(f"   ✅ Saved odolo_contract_data.json")
            print(f"   Total Supply: {data['totalSupply']:,.2f}")
            print(f"   Available in Vester: {data['availableTokens']:,.2f}")
            print(f"   Exercised (pushed): {data['pushedTokens']:,.2f}")
            print(f"   In Circulation: {data['inCirculation']:,.2f}")
            return

        except Exception as e:
            print(f"   ⚠️ RPC failed ({url}): {e}")
            continue

    print("   ❌ All RPC endpoints failed!")
    if os.path.exists(OUTPUT_FILE):
        print(f"   Keeping existing {OUTPUT_FILE}")
    else:
        print(f"   No existing file — cannot create placeholder")


if __name__ == "__main__":
    main()
