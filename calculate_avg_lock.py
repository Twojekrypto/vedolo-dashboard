#!/usr/bin/env python3
"""
Calculate average lock duration from oDOLO exercise transactions.
Scans all exercise txs on the Vester contract, extracts lock_end from input data,
computes lock_duration = lock_end - tx_timestamp, and outputs average lock stats.
"""

import requests
import time
import json
import os
from datetime import datetime, timezone

ROUTESCAN_API = "https://api.routescan.io/v2/network/mainnet/evm/80094/etherscan/api"
VESTER_CONTRACT = "0x3E9b9A16743551DA49b5e136C716bBa7932d2cEc"
EXERCISE_METHOD_ID = "0xa88f8139"
PAGE_SIZE = 100
RATE_LIMIT_DELAY = 0.3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "avg_lock_data.json")


def get_all_exercise_txs():
    """Fetch ALL exercise transactions from the Vester contract."""
    all_txs = []
    page = 1

    while True:
        params = {
            "module": "account",
            "action": "txlist",
            "address": VESTER_CONTRACT,
            "startblock": 0,
            "endblock": 99999999,
            "page": page,
            "offset": PAGE_SIZE,
            "sort": "asc"
        }

        resp = requests.get(ROUTESCAN_API, params=params)
        data = resp.json()

        if data.get("status") != "1" or not data.get("result"):
            break

        txs = data["result"]
        # Filter for successful exercise txs
        exercise = [
            tx for tx in txs
            if tx.get("methodId") == EXERCISE_METHOD_ID
            and tx.get("isError") == "0"
            and tx.get("txreceipt_status") == "1"
        ]
        all_txs.extend(exercise)

        print(f"  Page {page}: {len(txs)} txs, {len(exercise)} exercises (total: {len(all_txs)})")

        if len(txs) < PAGE_SIZE:
            break

        page += 1
        time.sleep(RATE_LIMIT_DELAY)

    return all_txs


def extract_lock_duration(tx):
    """Extract lock duration in seconds from exercise tx input data."""
    inp = tx["input"]
    if len(inp) < 266:  # 2 + 8 + 4*64
        return None

    # Param 2 (index 2) = lock_end timestamp
    params_hex = inp[10:]
    lock_end = int(params_hex[2*64:3*64], 16)
    tx_time = int(tx["timeStamp"])

    duration_seconds = lock_end - tx_time
    if duration_seconds <= 0 or duration_seconds > 3 * 365 * 86400:  # sanity: max 3 years
        return None

    return duration_seconds


def main():
    print("=" * 55)
    print("oDOLO Average Lock Duration Calculator")
    print("=" * 55)

    print("\n  Fetching all exercise transactions...")
    txs = get_all_exercise_txs()
    print(f"\n  Total exercise transactions: {len(txs)}")

    durations = []
    for tx in txs:
        dur = extract_lock_duration(tx)
        if dur is not None:
            durations.append(dur)

    if not durations:
        print("  No valid durations found!")
        return

    avg_seconds = sum(durations) / len(durations)
    avg_days = avg_seconds / 86400
    avg_months = avg_days / 30.44
    avg_years = avg_days / 365.25

    # Distribution buckets
    buckets = {"< 1 month": 0, "1-3 months": 0, "3-6 months": 0,
               "6-12 months": 0, "1-2 years": 0}
    for d in durations:
        days = d / 86400
        if days < 30:
            buckets["< 1 month"] += 1
        elif days < 90:
            buckets["1-3 months"] += 1
        elif days < 180:
            buckets["3-6 months"] += 1
        elif days < 365:
            buckets["6-12 months"] += 1
        else:
            buckets["1-2 years"] += 1

    # Average discount (linear: 5% at 7 days, 50% at 730 days)
    avg_discount = 5 + (avg_days - 7) * (50 - 5) / (730 - 7)
    avg_discount = max(5, min(50, avg_discount))

    # Load exercised USD for avg price
    usd_file = os.path.join(SCRIPT_DIR, "exercised_usd.json")
    avg_price = None
    if os.path.exists(usd_file):
        with open(usd_file) as f:
            usd_data = json.load(f)
        total_usdc = usd_data.get("total_usdc", 0)
        # We need total veDOLO exercised - read from contract or approximate
        # For now, use total_txs to see if it matches
        print(f"\n  Exercised USD data: ${total_usdc:,.2f} across {usd_data.get('total_txs', 0)} txs")

    print(f"\n  ╔═══════════════════════════════════════════╗")
    print(f"  ║  Valid durations: {len(durations):>6} / {len(txs)} txs       ║")
    print(f"  ║  Average lock:   {avg_days:>6.1f} days             ║")
    print(f"  ║  Average lock:   {avg_months:>6.1f} months           ║")
    print(f"  ║  Average lock:   {avg_years:>6.2f} years            ║")
    print(f"  ║  Avg discount:   {avg_discount:>6.1f}%                ║")
    print(f"  ╚═══════════════════════════════════════════╝")

    print(f"\n  Distribution:")
    for bucket, count in buckets.items():
        pct = count / len(durations) * 100
        bar = "█" * int(pct / 2)
        print(f"    {bucket:>15}: {count:>5} ({pct:>5.1f}%) {bar}")

    # Save results
    result = {
        "avg_lock_days": round(avg_days, 1),
        "avg_lock_months": round(avg_months, 1),
        "avg_discount_pct": round(avg_discount, 1),
        "total_exercises": len(txs),
        "valid_durations": len(durations),
        "distribution": buckets,
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n  ✅ Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
