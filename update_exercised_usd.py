#!/usr/bin/env python3
"""
Incremental update of Exercised Volume in USD.
Reads existing exercised_usd.json, scans only NEW transactions since last block,
and updates the total. Run periodically (cron, GitHub Action, etc).
"""

import requests
import time
import json
import os
from datetime import datetime, timezone

ROUTESCAN_API = "https://api.routescan.io/v2/network/mainnet/evm/80094/etherscan/api"
VESTER_CONTRACT = "0x3E9b9A16743551DA49b5e136C716bBa7932d2cEc"
USDC_E_CONTRACT = "0x549943e04f40284185054145c6e4e9568c1d3241".lower()
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
EXERCISE_METHOD_ID = "0xa88f8139"
USDC_DECIMALS = 6
PAGE_SIZE = 100
RATE_LIMIT_DELAY = 0.3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "exercised_usd.json")


def load_existing():
    """Load existing data or return defaults."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"total_usdc": 0, "total_txs": 0, "last_block": 0}


def save_data(data):
    """Save updated data."""
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  ✅ Saved to {DATA_FILE}")


def get_new_transactions(start_block):
    """Fetch transactions after start_block."""
    all_txs = []
    page = 1

    while True:
        params = {
            "module": "account",
            "action": "txlist",
            "address": VESTER_CONTRACT,
            "startblock": start_block + 1,
            "endblock": 99999999,
            "page": page,
            "offset": PAGE_SIZE,
            "sort": "asc"
        }

        resp = requests.get(ROUTESCAN_API, params=params)
        data = resp.json()

        if data["status"] != "1" or not data["result"]:
            break

        txs = data["result"]
        all_txs.extend(txs)

        if len(txs) < PAGE_SIZE:
            break

        page += 1
        time.sleep(RATE_LIMIT_DELAY)

    return all_txs


def get_usdc_from_receipt(tx_hash):
    """Get USDC.e payment from transaction receipt."""
    params = {
        "module": "proxy",
        "action": "eth_getTransactionReceipt",
        "txhash": tx_hash
    }

    resp = requests.get(ROUTESCAN_API, params=params)
    data = resp.json()

    if "result" not in data or data["result"] is None:
        return None

    for log in data["result"].get("logs", []):
        if (log["address"].lower() == USDC_E_CONTRACT and
            len(log["topics"]) >= 3 and
            log["topics"][0] == TRANSFER_TOPIC):
            to_addr = "0x" + log["topics"][2][26:].lower()
            if to_addr == VESTER_CONTRACT.lower():
                return int(log["data"], 16) / (10 ** USDC_DECIMALS)

    return None


def main():
    print("=" * 50)
    print("oDOLO Exercised Volume — Incremental Update")
    print("=" * 50)

    existing = load_existing()
    last_block = existing.get("last_block", 0)
    total_usdc = existing.get("total_usdc", 0)
    total_txs = existing.get("total_txs", 0)

    print(f"  Current total: ${total_usdc:,.2f} ({total_txs} txs)")
    print(f"  Last block: {last_block}")
    print()

    # Fetch new transactions
    print("  Fetching new transactions...")
    new_txs = get_new_transactions(last_block)
    print(f"  Found {len(new_txs)} new transactions")

    # Filter exercise txs
    exercise_txs = [
        tx for tx in new_txs
        if tx.get("methodId") == EXERCISE_METHOD_ID
        and tx.get("isError") == "0"
        and tx.get("txreceipt_status") == "1"
    ]
    print(f"  New exercise transactions: {len(exercise_txs)}")

    if not exercise_txs and not new_txs:
        print("  No new data. Done.")
        return

    # Process new exercise transactions
    new_usdc = 0
    max_block = last_block

    for i, tx in enumerate(exercise_txs):
        amount = get_usdc_from_receipt(tx["hash"])
        block = int(tx["blockNumber"])
        max_block = max(max_block, block)

        if amount is not None:
            new_usdc += amount
            total_txs += 1
            ts = int(tx["timeStamp"])
            date = time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts))
            print(f"    [{i+1}/{len(exercise_txs)}] {date} | {amount:>10,.2f} USDC")

        time.sleep(RATE_LIMIT_DELAY)

    # Update max_block from ALL new txs (not just exercise)
    for tx in new_txs:
        block = int(tx["blockNumber"])
        max_block = max(max_block, block)

    total_usdc += new_usdc

    # Save
    result = {
        "total_usdc": round(total_usdc, 2),
        "total_txs": total_txs,
        "last_block": max_block,
        "period": existing.get("period", "2025-06-26") .split(" to ")[0] + " to " + datetime.now(timezone.utc).strftime("%Y-%m-%d")
    }

    save_data(result)

    print()
    print(f"  New volume:   +${new_usdc:,.2f}")
    print(f"  ╔═══════════════════════════════════════╗")
    print(f"  ║  TOTAL: ${total_usdc:>14,.2f} USDC       ║")
    print(f"  ╚═══════════════════════════════════════╝")


if __name__ == "__main__":
    main()
