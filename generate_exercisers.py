#!/usr/bin/env python3
"""
Generate exercisers_by_address.json with per-address aggregation AND per-tx details
including lock duration, oDOLO amount, and price per veDOLO.
"""

import requests
import time
import json
from collections import defaultdict
from datetime import datetime

ROUTESCAN_API = "https://api.routescan.io/v2/network/mainnet/evm/80094/etherscan/api"
VESTER_CONTRACT = "0x3E9b9A16743551DA49b5e136C716bBa7932d2cEc"
USDC_E_CONTRACT = "0x549943e04f40284185054145c6e4e9568c1d3241".lower()
ODOLO_CONTRACT = "0x02e513b5b54ee216bf836ceb471507488fc89543".lower()
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
EXERCISE_METHOD_ID = "0xa88f8139"
USDC_DECIMALS = 6
ODOLO_DECIMALS = 18

PAGE_SIZE = 100
RATE_LIMIT_DELAY = 0.2


def get_all_transactions():
    all_txs = []
    page = 1
    while True:
        print(f"  Fetching page {page}...")
        params = {
            "module": "account", "action": "txlist",
            "address": VESTER_CONTRACT,
            "startblock": 0, "endblock": 99999999,
            "page": page, "offset": PAGE_SIZE, "sort": "asc"
        }
        resp = requests.get(ROUTESCAN_API, params=params)
        data = resp.json()
        if data["status"] != "1" or not data["result"]:
            break
        txs = data["result"]
        all_txs.extend(txs)
        if (page % 10 == 0):
            print(f"    Total: {len(all_txs)}")
        if len(txs) < PAGE_SIZE:
            break
        page += 1
        time.sleep(RATE_LIMIT_DELAY)
    return all_txs


def extract_lock_duration(tx):
    """Extract lock duration in days from tx input data."""
    inp = tx["input"]
    if len(inp) < 266:
        return None
    params_hex = inp[10:]
    lock_end = int(params_hex[2*64:3*64], 16)
    tx_time = int(tx["timeStamp"])
    duration_seconds = lock_end - tx_time
    if duration_seconds <= 0 or duration_seconds > 3 * 365 * 86400:
        return None
    return round(duration_seconds / 86400, 1)


def get_tx_details_from_receipt(tx_hash):
    """Get USDC.e amount AND oDOLO amount from a tx receipt."""
    params = {
        "module": "proxy",
        "action": "eth_getTransactionReceipt",
        "txhash": tx_hash
    }
    resp = requests.get(ROUTESCAN_API, params=params)
    data = resp.json()
    if "result" not in data or data["result"] is None:
        return None, None

    usdc_amount = None
    odolo_amount = None

    for log in data["result"].get("logs", []):
        if len(log["topics"]) < 3 or log["topics"][0] != TRANSFER_TOPIC:
            continue

        token_addr = log["address"].lower()
        to_addr = "0x" + log["topics"][2][26:].lower()

        # USDC.e payment: from user TO vester
        if token_addr == USDC_E_CONTRACT and to_addr == VESTER_CONTRACT.lower():
            usdc_amount = int(log["data"], 16) / (10 ** USDC_DECIMALS)

        # oDOLO burn: from vester TO 0x0 (burn address) during exercise
        # The burned oDOLO amount = veDOLO received (1:1)
        if token_addr == ODOLO_CONTRACT:
            from_addr = "0x" + log["topics"][1][26:].lower()
            to_addr_check = "0x" + log["topics"][2][26:].lower()
            if from_addr == VESTER_CONTRACT.lower() and to_addr_check == "0x0000000000000000000000000000000000000000":
                raw = log.get("data", "0x")
                if len(raw) > 2:
                    odolo_amount = int(raw, 16) / (10 ** ODOLO_DECIMALS)

    return usdc_amount, odolo_amount


def main():
    print("=" * 60)
    print("oDOLO Exercisers — Enhanced Data Generator")
    print("=" * 60)

    print("\n[1/3] Fetching Vester transactions...")
    all_txs = get_all_transactions()
    print(f"  Total: {len(all_txs)}")

    exercise_txs = [
        tx for tx in all_txs
        if tx.get("methodId") == EXERCISE_METHOD_ID
        and tx.get("isError") == "0"
        and tx.get("txreceipt_status") == "1"
    ]
    print(f"\n[2/3] Exercise transactions: {len(exercise_txs)}")

    print("\n[3/3] Scanning receipts for USDC.e + oDOLO amounts + lock durations...")
    address_data = defaultdict(lambda: {
        "total_usdc": 0, "exercises": 0, "lock_days_sum": 0,
        "lock_count": 0, "first": None, "last": None, "txs": []
    })
    errors = 0

    for i, tx in enumerate(exercise_txs):
        tx_hash = tx["hash"]
        addr = tx["from"].lower()
        timestamp = int(tx["timeStamp"])
        date_str = time.strftime("%Y-%m-%d", time.gmtime(timestamp))

        usdc_amount, odolo_amount = get_tx_details_from_receipt(tx_hash)
        lock_days = extract_lock_duration(tx)

        if usdc_amount is not None:
            d = address_data[addr]
            d["total_usdc"] += usdc_amount
            d["exercises"] += 1
            if lock_days is not None:
                d["lock_days_sum"] += lock_days
                d["lock_count"] += 1
            if d["first"] is None or date_str < d["first"]:
                d["first"] = date_str
            if d["last"] is None or date_str > d["last"]:
                d["last"] = date_str

            # Per-tx detail
            vedolo_amount = odolo_amount if odolo_amount else None
            price_per_vedolo = None
            if usdc_amount and vedolo_amount and vedolo_amount > 0:
                price_per_vedolo = round(usdc_amount / vedolo_amount, 6)

            d["txs"].append({
                "hash": tx_hash,
                "date": date_str,
                "usdc": round(usdc_amount, 2),
                "vedolo": round(vedolo_amount, 2) if vedolo_amount else None,
                "price": price_per_vedolo,
                "lock_days": lock_days
            })
        else:
            errors += 1

        if (i + 1) % 100 == 0 or i == len(exercise_txs) - 1:
            print(f"  [{i+1}/{len(exercise_txs)}] Addresses: {len(address_data)}")

        time.sleep(RATE_LIMIT_DELAY)

    # Build sorted list
    exercisers = []
    for addr, d in address_data.items():
        avg_lock = round(d["lock_days_sum"] / d["lock_count"], 1) if d["lock_count"] > 0 else None
        exercisers.append({
            "address": addr,
            "total_usdc": round(d["total_usdc"], 2),
            "exercises": d["exercises"],
            "avg_lock_days": avg_lock,
            "first": d["first"],
            "last": d["last"],
            "txs": d["txs"]
        })

    exercisers.sort(key=lambda x: x["total_usdc"], reverse=True)

    result = {
        "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_addresses": len(exercisers),
        "total_usdc": round(sum(e["total_usdc"] for e in exercisers), 2),
        "total_exercises": sum(e["exercises"] for e in exercisers),
        "exercisers": exercisers
    }

    with open("exercisers_by_address.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"DONE!")
    print(f"  Unique addresses:  {len(exercisers)}")
    print(f"  Total USDC.e:      ${result['total_usdc']:,.2f}")
    print(f"  Total exercises:   {result['total_exercises']}")
    print(f"  Errors:            {errors}")
    print(f"  Saved to exercisers_by_address.json")


if __name__ == "__main__":
    main()
