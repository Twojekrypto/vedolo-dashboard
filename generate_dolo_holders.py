#!/usr/bin/env python3
"""
DOLO Token Holders — ERC-20 holder generator (ETH + Berachain)
Fetches all ERC-20 Transfer events for DOLO on both chains,
computes balances, merges holders, and outputs dolo_holders.json.
"""
import json, time, os, sys
import requests
from datetime import datetime

# ===== CONFIG =====
DOLO_CONTRACT = "0x0F81001eF0A83ecCE5ccebf63EB302c70a39a654"
ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
ZERO = "0x0000000000000000000000000000000000000000"

CHAINS = {
    "eth": {"chain_id": 1, "name": "Ethereum", "env_key": "ETHERSCAN_API_KEY"},
    "bera": {"chain_id": 80094, "name": "Berachain", "env_key": "ETHERSCAN_API_KEY"},
}

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_JSON = os.path.join(DATA_DIR, "dolo_holders.json")

# Minimum balance to include (filter dust)
MIN_BALANCE = 1.0  # 1 DOLO


def fetch_erc20_transfers(chain_key):
    """Fetch all ERC-20 Transfer events for DOLO on a given chain."""
    cfg = CHAINS[chain_key]
    api_key = os.environ.get(cfg["env_key"], "")
    if not api_key:
        print(f"  ⚠️  {cfg['env_key']} not set — skipping {cfg['name']}")
        return []

    print(f"\n📡 Fetching DOLO transfers on {cfg['name']}...")

    all_txs = []
    seen = set()
    start_block = 0
    consecutive_errors = 0

    while True:
        params = {
            "chainid": cfg["chain_id"],
            "module": "account",
            "action": "tokentx",
            "contractaddress": DOLO_CONTRACT,
            "startblock": start_block,
            "endblock": 99999999,
            "page": 1,
            "offset": 10000,
            "sort": "asc",
            "apikey": api_key,
        }

        for retry in range(5):
            try:
                resp = requests.get(ETHERSCAN_V2, params=params, timeout=60)
                data = resp.json()

                if data.get("status") == "1" and isinstance(data.get("result"), list):
                    results = data["result"]
                    new_count = 0
                    for tx in results:
                        tx_key = tx.get("hash", "") + tx.get("logIndex", "")
                        if tx_key not in seen:
                            seen.add(tx_key)
                            all_txs.append(tx)
                            new_count += 1

                    print(f"  Block {start_block}+: {len(results)} txs, {new_count} new (total: {len(all_txs)})")
                    consecutive_errors = 0

                    if len(results) < 10000:
                        print(f"  ✅ {cfg['name']}: {len(all_txs)} transfers")
                        return all_txs

                    last_block = int(results[-1].get("blockNumber", start_block))
                    start_block = last_block if last_block != start_block else last_block + 1
                    time.sleep(0.3)
                    break

                elif "rate" in str(data.get("result", "")).lower() or "max rate" in str(data.get("message", "")).lower():
                    wait_time = 3 * (retry + 1)
                    print(f"  Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    if "No transactions" in str(data.get("result", "")):
                        print(f"  ✅ {cfg['name']}: {len(all_txs)} transfers")
                        return all_txs
                    print(f"  ⚠️ API: {data.get('message')}: {str(data.get('result',''))[:200]}")
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        print(f"  ❌ Too many consecutive errors, returning {len(all_txs)} transfers so far")
                        return all_txs
                    time.sleep(2 * (retry + 1))
                    continue

            except requests.exceptions.Timeout:
                print(f"  Timeout (retry {retry+1}/5), waiting {3*(retry+1)}s...")
                time.sleep(3 * (retry + 1))
            except Exception as e:
                print(f"  Error: {e}, retry {retry+1}/5")
                time.sleep(2 * (retry + 1))
        else:
            consecutive_errors += 1
            print(f"  ❌ Failed after 5 retries at block {start_block}")
            if consecutive_errors >= 3:
                print(f"  ❌ Aborting {cfg['name']} — returning {len(all_txs)} transfers")
                break
            # Try next block range
            start_block += 10000

    return all_txs


def build_balances(txs, chain_key):
    """Build address -> balance map from ERC-20 transfers."""
    balances = {}
    decimals = 18

    # Sort by block + logIndex for correct ordering
    txs.sort(key=lambda t: (int(t.get("blockNumber", 0)), int(t.get("logIndex", 0))))

    for tx in txs:
        from_addr = tx.get("from", "").lower()
        to_addr = tx.get("to", "").lower()
        value_raw = int(tx.get("value", "0"))
        value = value_raw / (10 ** decimals)

        if from_addr != ZERO.lower():
            balances[from_addr] = balances.get(from_addr, 0) - value
        if to_addr != ZERO.lower():
            balances[to_addr] = balances.get(to_addr, 0) + value

    # Filter out zero/negative/dust balances
    result = {}
    for addr, bal in balances.items():
        if bal >= MIN_BALANCE:
            result[addr] = round(bal, 4)

    print(f"  {chain_key.upper()}: {len(result)} holders with ≥{MIN_BALANCE} DOLO")
    return result


def merge_holders(eth_balances, bera_balances):
    """Merge holders from both chains into a single list."""
    all_addrs = set(eth_balances.keys()) | set(bera_balances.keys())

    holders = []
    for addr in all_addrs:
        bal_eth = eth_balances.get(addr, 0)
        bal_bera = bera_balances.get(addr, 0)
        total = round(bal_eth + bal_bera, 4)

        chains = []
        if bal_eth >= MIN_BALANCE:
            chains.append("eth")
        if bal_bera >= MIN_BALANCE:
            chains.append("bera")

        holders.append({
            "address": addr,
            "balance": total,
            "balance_eth": round(bal_eth, 4) if bal_eth >= MIN_BALANCE else 0,
            "balance_bera": round(bal_bera, 4) if bal_bera >= MIN_BALANCE else 0,
            "chains": chains,
        })

    # Sort by total balance descending
    holders.sort(key=lambda h: h["balance"], reverse=True)

    # Assign ranks
    for i, h in enumerate(holders, 1):
        h["rank"] = i

    # Checksum addresses
    try:
        from web3 import Web3
        for h in holders:
            try:
                h["address"] = Web3.to_checksum_address(h["address"])
            except Exception:
                pass
    except ImportError:
        # Capitalize hex manually (basic checksum)
        pass

    return holders


def main():
    print("=" * 60)
    print("🔄 DOLO Token Holders — Generator (ETH + BERA)")
    print(f"   {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # Fetch transfers from both chains
    eth_txs = fetch_erc20_transfers("eth")
    bera_txs = fetch_erc20_transfers("bera")

    if not eth_txs and not bera_txs:
        print("⚠️  No transfers found on any chain!")
        sys.exit(1)

    # Build balances
    print("\n📊 Building balance maps...")
    eth_balances = build_balances(eth_txs, "eth") if eth_txs else {}
    bera_balances = build_balances(bera_txs, "bera") if bera_txs else {}

    # Merge
    print("\n🔀 Merging holders across chains...")
    holders = merge_holders(eth_balances, bera_balances)

    # Stats
    eth_only = sum(1 for h in holders if h["chains"] == ["eth"])
    bera_only = sum(1 for h in holders if h["chains"] == ["bera"])
    both_chains = sum(1 for h in holders if len(h["chains"]) == 2)
    total_supply = sum(h["balance"] for h in holders)

    stats = {
        "total_holders": len(holders),
        "eth_holders": sum(1 for h in holders if "eth" in h["chains"]),
        "bera_holders": sum(1 for h in holders if "bera" in h["chains"]),
        "both_chains": both_chains,
        "total_supply": round(total_supply, 2),
    }

    output = {
        "contract": DOLO_CONTRACT,
        "timestamp": datetime.utcnow().isoformat(),
        "stats": stats,
        "holders": holders,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n💾 Saved: dolo_holders.json")
    print(f"   Total holders: {stats['total_holders']:,}")
    print(f"   ETH only: {eth_only:,}  |  BERA only: {bera_only:,}  |  Both: {both_chains:,}")
    print(f"   Total supply tracked: {total_supply:,.2f} DOLO")

    print(f"\n🏆 TOP 10:")
    for h in holders[:10]:
        chains = "+".join(c.upper() for c in h["chains"])
        print(f"   #{h['rank']:<4} {h['address'][:12]}… {h['balance']:>14,.2f} DOLO  [{chains}]")

    print("\n✅ Done!")


if __name__ == "__main__":
    main()
