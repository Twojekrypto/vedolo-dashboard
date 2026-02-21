#!/usr/bin/env python3
"""
Fetch veDOLO early exit penalty data from on-chain Withdraw events.

For each Withdraw event, analyzes the transaction receipt to calculate:
- Burn fee (5% of locked DOLO, transferred to address(0))
- Recoup fee (variable %, transferred to oDOLO vester)
- DOLO returned to user

Outputs: early_exits.json with aggregated stats + per-exit details.

Usage:
    python3 fetch_early_exits.py

Requires BERASCAN_API_KEY environment variable.
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===== CONFIG =====
VEDOLO_CONTRACT = "0xCB86B75EE6133d179a12D550b09FB3cdB1e141D4"
DOLO_TOKEN = "0x0F81001eF0A83ecCE5ccebf63EB302c70a39a654"
ODOLO_VESTER = "0x3E9b9A16743551DA49b5e136C716bBa7932d2cEc"

# Event topics (keccak256)
WITHDRAW_TOPIC = "0x02f25270a4d87bea75db541cdfe559334a275b4a233520ed6c0a2429667cca94"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
CHAIN_ID = 80094  # Berachain
RPC_URLS = [
    "https://berachain-rpc.publicnode.com/",
    "https://berachain.drpc.org/",
    "https://rpc.berachain.com/",
]
ZERO_ADDR = "0x0000000000000000000000000000000000000000"

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(DATA_DIR, "early_exits.json")
CACHE_FILE = os.path.join(DATA_DIR, "early_exits_cache.json")

API_KEY = os.environ.get("BERASCAN_API_KEY", "")


def rpc_call(method, params, retries=3):
    """Make an RPC call with fallback across multiple providers."""
    for rpc_idx, rpc_url in enumerate(RPC_URLS):
        for attempt in range(retries):
            try:
                resp = requests.post(rpc_url, json={
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params,
                    "id": 1
                }, timeout=20)
                data = resp.json()
                if "result" in data:
                    return data["result"]
                if "error" in data:
                    if attempt < retries - 1:
                        time.sleep(0.5 * (attempt + 1))
                        continue
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(0.5 * (attempt + 1))
    return None


def fetch_withdraw_events():
    """Fetch all Withdraw events from the veDOLO contract using RPC getLogs with pagination."""
    print("📡 Phase 1: Fetching Withdraw events...")

    # Get latest block
    latest_block = int(rpc_call("eth_blockNumber", []), 16)
    print(f"  Latest block: {latest_block:,}")

    all_logs = []
    block = 0
    step = 10000  # 10K block pages (RPC limit for free tier)

    while block <= latest_block:
        to_block = min(block + step - 1, latest_block)

        result = rpc_call("eth_getLogs", [{
            "address": VEDOLO_CONTRACT,
            "topics": [WITHDRAW_TOPIC],
            "fromBlock": hex(block),
            "toBlock": hex(to_block)
        }])

        if result:
            all_logs.extend(result)
            if len(result) > 0:
                print(f"  Block {block:,}-{to_block:,}: {len(result)} events (total: {len(all_logs)})")

        block = to_block + 1

        # Small delay to avoid rate limits
        if block % 100000 == 0:
            time.sleep(0.1)

    print(f"  ✅ Found {len(all_logs)} total Withdraw events")
    return all_logs


def decode_withdraw_event(log):
    """Decode a Withdraw event log into structured data."""
    provider = "0x" + log["topics"][1][26:]  # indexed address
    data = log.get("data", "0x")[2:]

    token_id = int(data[0:64], 16)
    value = int(data[64:128], 16) / 1e18  # DOLO returned to user
    ts = int(data[128:192], 16)

    return {
        "provider": provider.lower(),
        "token_id": token_id,
        "value": value,
        "timestamp": ts,
        "block": int(log["blockNumber"], 16),
        "tx_hash": log["transactionHash"],
    }


def fetch_receipt_and_calc_penalty(tx_hash):
    """Fetch transaction receipt and calculate penalty from Transfer events."""
    receipt = rpc_call("eth_getTransactionReceipt", [tx_hash])
    if not receipt:
        return None

    burn_amount = 0.0
    recoup_amount = 0.0
    user_amount = 0.0
    user_addr = None

    dolo_lower = DOLO_TOKEN.lower()
    vedolo_lower = VEDOLO_CONTRACT.lower()
    zero_lower = ZERO_ADDR.lower()
    vester_lower = ODOLO_VESTER.lower()

    for log in receipt.get("logs", []):
        # Only look at DOLO token Transfer events
        if log["address"].lower() != dolo_lower:
            continue
        if not log["topics"] or log["topics"][0] != TRANSFER_TOPIC:
            continue
        if len(log["topics"]) < 3:
            continue

        from_addr = "0x" + log["topics"][1][26:]
        to_addr = "0x" + log["topics"][2][26:]
        amount = int(log.get("data", "0x0"), 16) / 1e18

        from_addr_l = from_addr.lower()
        to_addr_l = to_addr.lower()

        # Transfer FROM veDOLO contract
        if from_addr_l == vedolo_lower:
            if to_addr_l == zero_lower:
                burn_amount += amount  # Burn fee
            elif to_addr_l == vester_lower:
                recoup_amount += amount  # Recoup fee (to oDOLO vester)
            elif to_addr_l.startswith("0xcfc30d38"):
                recoup_amount += amount  # Recoup fee (to secondary address)
            else:
                user_amount += amount  # DOLO returned to user
                user_addr = to_addr_l

    total_penalty = burn_amount + recoup_amount
    original_locked = burn_amount + recoup_amount + user_amount

    return {
        "burn_fee": round(burn_amount, 4),
        "recoup_fee": round(recoup_amount, 4),
        "total_penalty": round(total_penalty, 4),
        "original_locked": round(original_locked, 4),
        "user_received": round(user_amount, 4),
        "penalty_pct": round((total_penalty / original_locked * 100) if original_locked > 0 else 0, 2),
        "is_early_exit": total_penalty > 0,
    }


def main():
    print("=" * 60)
    print("🔄 veDOLO Early Exit Penalty — Data Fetcher")
    print(f"   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # Load cache
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        print(f"  📦 Loaded {len(cache)} cached tx receipts")

    # Phase 1: Fetch all Withdraw events
    logs = fetch_withdraw_events()
    if not logs:
        print("⚠️ No Withdraw events found!")
        sys.exit(0)

    # Phase 2: Decode events
    print(f"\n📊 Phase 2: Decoding {len(logs)} Withdraw events...")
    events = []
    for log in logs:
        ev = decode_withdraw_event(log)
        events.append(ev)

    # Phase 3: Fetch receipts and calculate penalties
    print(f"\n💰 Phase 3: Calculating penalties for {len(events)} events...")

    # Check which tx_hashes need receipts
    tx_hashes_needed = [ev["tx_hash"] for ev in events if ev["tx_hash"] not in cache]
    print(f"  Cached: {len(events) - len(tx_hashes_needed)}/{len(events)}")
    print(f"  To fetch: {len(tx_hashes_needed)}")

    # Fetch receipts for uncached transactions (parallel for speed)
    if tx_hashes_needed:
        done = 0
        errors = 0
        MAX_WORKERS = 8

        def fetch_one(tx_hash):
            return tx_hash, fetch_receipt_and_calc_penalty(tx_hash)

        chunks = [tx_hashes_needed[i:i+MAX_WORKERS] for i in range(0, len(tx_hashes_needed), MAX_WORKERS)]
        for chunk_idx, chunk in enumerate(chunks):
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = [executor.submit(fetch_one, th) for th in chunk]
                for future in as_completed(futures):
                    tx_hash, result = future.result()
                    if result:
                        cache[tx_hash] = result
                    else:
                        errors += 1
                    done += 1

            if (chunk_idx + 1) % 10 == 0 or (chunk_idx + 1) == len(chunks):
                print(f"  Progress: {done:,}/{len(tx_hashes_needed):,} (errors: {errors})")
                with open(CACHE_FILE, "w") as f:
                    json.dump(cache, f)

            time.sleep(0.05)  # Small delay between batches

        # Final cache save
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)


    # Phase 4: Merge data and calculate stats
    print(f"\n📈 Phase 4: Computing statistics...")

    early_exits = []
    normal_exits = []
    total_burn = 0
    total_recoup = 0
    total_penalty_dolo = 0
    total_original_locked = 0

    for ev in events:
        penalty = cache.get(ev["tx_hash"])
        if not penalty:
            continue

        entry = {**ev, **penalty}
        entry["date"] = datetime.utcfromtimestamp(ev["timestamp"]).strftime("%Y-%m-%d")

        if penalty.get("is_early_exit"):
            early_exits.append(entry)
            total_burn += penalty["burn_fee"]
            total_recoup += penalty["recoup_fee"]
            total_penalty_dolo += penalty["total_penalty"]
            total_original_locked += penalty["original_locked"]
        else:
            normal_exits.append(entry)

    # Sort by timestamp
    early_exits.sort(key=lambda x: x["timestamp"], reverse=True)

    # Calculate aggregate stats
    stats = {
        "total_early_exits": len(early_exits),
        "total_normal_exits": len(normal_exits),
        "total_withdrawals": len(events),
        "total_burn_fee_dolo": round(total_burn, 2),
        "total_recoup_fee_dolo": round(total_recoup, 2),
        "total_penalty_dolo": round(total_penalty_dolo, 2),
        "total_original_locked": round(total_original_locked, 2),
        "avg_penalty_pct": round(
            (total_penalty_dolo / total_original_locked * 100) if total_original_locked > 0 else 0, 2
        ),
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    output = {
        "stats": stats,
        "early_exits": early_exits,
    }

    # Save full data for analysis
    full_file = os.path.join(DATA_DIR, "early_exits_full.json")
    with open(full_file, "w") as f:
        json.dump(output, f)
    print(f"\n💾 Saved: early_exits_full.json ({os.path.getsize(full_file) / 1024:.0f} KB)")

    # Save slim stats-only for the dashboard (fast loading)
    with open(OUTPUT_FILE, "w") as f:
        json.dump({"stats": stats}, f, indent=2)
    print(f"💾 Saved: early_exits.json ({os.path.getsize(OUTPUT_FILE)} bytes)")


    print(f"\n💾 Saved: early_exits.json")
    print(f"   Early exits: {stats['total_early_exits']}")
    print(f"   Normal exits: {stats['total_normal_exits']}")
    print(f"   Total burn fee: {stats['total_burn_fee_dolo']:,.2f} DOLO")
    print(f"   Total recoup fee: {stats['total_recoup_fee_dolo']:,.2f} DOLO")
    print(f"   Total penalty: {stats['total_penalty_dolo']:,.2f} DOLO")
    print(f"   Avg penalty: {stats['avg_penalty_pct']:.1f}%")
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
