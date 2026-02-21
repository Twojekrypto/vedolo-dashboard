#!/usr/bin/env python3
"""
Calculate total Exercised Volume in USD by scanning all closePositionAndBuyTokens
transactions on the Vester contract and summing USDC.e Transfer amounts.
"""

import requests
import time
import json

ROUTESCAN_API = "https://api.routescan.io/v2/network/mainnet/evm/80094/etherscan/api"
VESTER_CONTRACT = "0x3E9b9A16743551DA49b5e136C716bBa7932d2cEc"
USDC_E_CONTRACT = "0x549943e04f40284185054145c6e4e9568c1d3241".lower()
# ERC20 Transfer event topic
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
# closePositionAndBuyTokens method ID
EXERCISE_METHOD_ID = "0xa88f8139"
# USDC.e has 6 decimals
USDC_DECIMALS = 6

PAGE_SIZE = 100
RATE_LIMIT_DELAY = 0.3  # seconds between API calls


def get_all_transactions():
    """Fetch all transactions to the Vester contract."""
    all_txs = []
    page = 1
    
    while True:
        print(f"  Fetching transactions page {page}...")
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
        
        if data["status"] != "1" or not data["result"]:
            break
        
        txs = data["result"]
        all_txs.extend(txs)
        print(f"    Got {len(txs)} transactions (total: {len(all_txs)})")
        
        if len(txs) < PAGE_SIZE:
            break
        
        page += 1
        time.sleep(RATE_LIMIT_DELAY)
    
    return all_txs


def get_exercise_transactions(all_txs):
    """Filter only successful closePositionAndBuyTokens transactions."""
    exercise_txs = []
    for tx in all_txs:
        if (tx.get("methodId") == EXERCISE_METHOD_ID and 
            tx.get("isError") == "0" and
            tx.get("txreceipt_status") == "1"):
            exercise_txs.append(tx)
    return exercise_txs


def get_usdc_amount_from_receipt(tx_hash):
    """Get the USDC.e payment amount from a transaction receipt."""
    params = {
        "module": "proxy",
        "action": "eth_getTransactionReceipt",
        "txhash": tx_hash
    }
    
    resp = requests.get(ROUTESCAN_API, params=params)
    data = resp.json()
    
    if "result" not in data or data["result"] is None:
        return None
    
    receipt = data["result"]
    logs = receipt.get("logs", [])
    
    # Find USDC.e Transfer event FROM user TO Vester contract
    # This is the payment: user sends USDC.e to Vester
    for log in logs:
        if (log["address"].lower() == USDC_E_CONTRACT and
            len(log["topics"]) >= 3 and
            log["topics"][0] == TRANSFER_TOPIC):
            
            # topics[1] = from, topics[2] = to
            to_addr = "0x" + log["topics"][2][26:].lower()
            
            # Payment is FROM user TO vester contract
            if to_addr == VESTER_CONTRACT.lower():
                amount_hex = log["data"]
                amount_raw = int(amount_hex, 16)
                amount_usd = amount_raw / (10 ** USDC_DECIMALS)
                return amount_usd
    
    return None


def main():
    print("=" * 60)
    print("oDOLO Exercised Volume Calculator (USD)")
    print("=" * 60)
    print()
    
    # Step 1: Get all transactions
    print("[1/3] Fetching all Vester contract transactions...")
    all_txs = get_all_transactions()
    print(f"  Total transactions: {len(all_txs)}")
    print()
    
    # Step 2: Filter exercise transactions
    print("[2/3] Filtering exercise (closePositionAndBuyTokens) transactions...")
    exercise_txs = get_exercise_transactions(all_txs)
    print(f"  Exercise transactions: {len(exercise_txs)}")
    print()
    
    # Step 3: Get USDC.e amounts from each receipt
    print("[3/3] Scanning receipts for USDC.e payments...")
    total_usdc = 0.0
    processed = 0
    errors = 0
    details = []
    
    for i, tx in enumerate(exercise_txs):
        tx_hash = tx["hash"]
        timestamp = int(tx["timeStamp"])
        date_str = time.strftime("%Y-%m-%d %H:%M", time.gmtime(timestamp))
        
        amount = get_usdc_amount_from_receipt(tx_hash)
        
        if amount is not None:
            total_usdc += amount
            processed += 1
            details.append({
                "date": date_str,
                "tx": tx_hash[:10] + "...",
                "from": tx["from"][:10] + "...",
                "usdc": amount
            })
            print(f"  [{i+1}/{len(exercise_txs)}] {date_str} | {amount:>12,.2f} USDC | Running total: {total_usdc:>14,.2f}")
        else:
            errors += 1
            print(f"  [{i+1}/{len(exercise_txs)}] {date_str} | ⚠️ No USDC.e transfer found | tx: {tx_hash[:16]}...")
        
        time.sleep(RATE_LIMIT_DELAY)
    
    # Summary
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Total exercise transactions:  {len(exercise_txs)}")
    print(f"  Successfully processed:       {processed}")
    print(f"  Errors/missing:               {errors}")
    print()
    print(f"  ╔══════════════════════════════════════════╗")
    print(f"  ║  TOTAL EXERCISED VOLUME:                 ║")
    print(f"  ║  ${total_usdc:>14,.2f} USDC                ║")
    print(f"  ╚══════════════════════════════════════════╝")
    print()
    
    # Save detailed results to JSON
    result = {
        "total_exercise_txs": len(exercise_txs),
        "processed": processed,
        "errors": errors,
        "total_usdc": total_usdc,
        "details": details
    }
    
    with open("exercised_volume_results.json", "w") as f:
        json.dump(result, f, indent=2)
    
    print("  Detailed results saved to exercised_volume_results.json")


if __name__ == "__main__":
    main()
