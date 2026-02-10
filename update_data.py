#!/usr/bin/env python3
"""
veDOLO Dashboard — Auto-updater
Phase 1: Fetches holders + token ownership from BeraScan Transfer events (paginated by block range).
Phase 2: Fetches locked DOLO amounts from Berachain RPC (batch calls with caching).
Outputs: vedolo_holders.json, vedolo_holders.csv
"""
import json, time, os, csv, sys
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===== CONFIG =====
VEDOLO_CONTRACT = "0xCB86B75EE6133d179a12D550b09FB3cdB1e141D4"
BERASCAN_API = "https://api.berascan.com/api"
RPC_URL = "https://berachain.drpc.org/"
LOCKED_SELECTOR = "0xb45a3c0e"  # locked(uint256)

BATCH_SIZE = 3
MAX_WORKERS = 8
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(DATA_DIR, "locked_cache.json")
OUTPUT_JSON = os.path.join(DATA_DIR, "vedolo_holders.json")
OUTPUT_CSV = os.path.join(DATA_DIR, "vedolo_holders.csv")

BERASCAN_API_KEY = os.environ.get("BERASCAN_API_KEY", "")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# ===== HELPERS =====

def api_params(extra=None):
    params = {}
    if BERASCAN_API_KEY:
        params["apikey"] = BERASCAN_API_KEY
    if extra:
        params.update(extra)
    return params


def api_get(params, timeout=60):
    """Make a BeraScan API call with retry logic."""
    for retry in range(3):
        try:
            resp = requests.get(BERASCAN_API, params=params, timeout=timeout)
            data = resp.json()
            if data.get("status") == "1":
                return data.get("result", [])
            if "rate limit" in data.get("message", "").lower() or "max rate" in data.get("result", "").lower() if isinstance(data.get("result"), str) else False:
                print(f"    Rate limited, waiting {2*(retry+1)}s...")
                time.sleep(2 * (retry + 1))
                continue
            return data.get("result", [])
        except Exception as e:
            print(f"    API error: {e}, retry {retry+1}/3")
            time.sleep(2 * (retry + 1))
    return []


def get_latest_block():
    """Get the latest block number from RPC."""
    resp = requests.post(RPC_URL, json={
        "jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1
    }, timeout=10)
    return int(resp.json()["result"], 16)


# ===== PHASE 1: Build ownership from NFT transfers =====

def fetch_nft_transfers():
    """Fetch all ERC-721 transfers for the veDOLO contract using tokennfttx API."""
    print("📡 Phase 1: Fetching NFT transfer history from BeraScan...")
    all_txs = []
    page = 1
    offset = 10000

    while True:
        params = api_params({
            "module": "account",
            "action": "tokennfttx",
            "contractaddress": VEDOLO_CONTRACT,
            "address": "",  # all addresses
            "page": page,
            "offset": offset,
            "sort": "asc",
        })
        # tokennfttx doesn't need address — use token approach
        # Actually BeraScan needs an address for tokennfttx, 
        # so let's use getLogs with block ranges instead
        break

    # Use getLogs approach with block range pagination
    return fetch_transfers_via_logs()


def fetch_transfers_via_logs():
    """Fetch Transfer events using getLogs with block range pagination."""
    print("  Using getLogs with block range pagination...")
    
    latest_block = get_latest_block()
    print(f"  Latest block: {latest_block}")
    
    all_events = []
    BLOCK_RANGE = 50000  # 50k blocks per query
    from_block = 0
    
    while from_block <= latest_block:
        to_block = min(from_block + BLOCK_RANGE - 1, latest_block)
        
        params = api_params({
            "module": "logs",
            "action": "getLogs",
            "address": VEDOLO_CONTRACT,
            "topic0": TRANSFER_TOPIC,
            "fromBlock": from_block,
            "toBlock": to_block,
        })
        
        result = api_get(params)
        
        if isinstance(result, list) and len(result) > 0:
            all_events.extend(result)
            print(f"  Blocks {from_block}-{to_block}: {len(result)} events (total: {len(all_events)})")
        elif isinstance(result, str) and "No records" in result:
            pass 
        
        from_block = to_block + 1
        time.sleep(0.25)  # Rate limiting
    
    print(f"  ✅ Total Transfer events: {len(all_events)}")
    return all_events


def build_ownership(events):
    """Build current ownership map from Transfer events."""
    print("\n📊 Building ownership map...")
    ZERO = "0x" + "0" * 40
    ownership = {}  # token_id -> current_owner

    for event in events:
        topics = event.get("topics", [])
        if len(topics) >= 4:
            token_id = int(topics[3], 16)
            to_addr = "0x" + topics[2][-40:].lower()
            ownership[token_id] = to_addr

    # Count stats
    all_token_ids = set(ownership.keys())
    burned = sum(1 for addr in ownership.values() if addr == ZERO)
    active_owners = {}
    
    for tid, owner in ownership.items():
        if owner == ZERO:
            continue
        if owner not in active_owners:
            active_owners[owner] = []
        active_owners[owner].append(tid)

    stats = {
        "total_minted": len(all_token_ids),
        "total_burned": burned,
        "active_nfts": len(all_token_ids) - burned,
        "unique_holders": len(active_owners),
    }

    holders = []
    for addr, tids in active_owners.items():
        holders.append({
            "address": addr,
            "nft_count": len(tids),
            "token_ids": sorted(tids),
        })

    print(f"  Minted: {stats['total_minted']}, Burned: {stats['total_burned']}, Active: {stats['active_nfts']}")
    print(f"  Unique holders: {stats['unique_holders']}")

    return holders, stats


# ===== PHASE 2: Fetch locked DOLO =====

def make_batch_call(token_ids):
    """Batch RPC call for locked(uint256) — up to BATCH_SIZE tokens."""
    s = requests.Session()
    batch = []
    for i, tid in enumerate(token_ids):
        encoded = hex(tid)[2:].zfill(64)
        batch.append({
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": VEDOLO_CONTRACT, "data": LOCKED_SELECTOR + encoded}, "latest"],
            "id": i
        })

    out = {}
    for retry in range(3):
        try:
            resp = s.post(RPC_URL, json=batch, timeout=15,
                          headers={"Content-Type": "application/json"})
            if resp.status_code == 429:
                time.sleep(1 * (retry + 1))
                continue
            resp.raise_for_status()
            results = resp.json()
            for r in results:
                idx = r["id"]
                tid = token_ids[idx]
                if "result" in r and r["result"] and len(r["result"]) >= 66:
                    raw = r["result"]
                    amount_raw = int(raw[2:66], 16)
                    if amount_raw >= 2**127:
                        amount_raw -= 2**128
                    end_raw = int(raw[66:130], 16)
                    out[tid] = {"amount": amount_raw / 1e18, "end": end_raw}
                else:
                    out[tid] = {"amount": 0, "end": 0}
            return out
        except Exception as e:
            if retry < 2:
                time.sleep(0.5 * (retry + 1))

    for tid in token_ids:
        if tid not in out:
            out[tid] = {"amount": 0, "end": 0, "error": True}
    return out


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, CACHE_FILE)


def fetch_locked_dolo(all_token_ids):
    """Fetch locked DOLO for all token IDs using batched RPC."""
    print(f"\n🔒 Phase 2: Fetching locked DOLO for {len(all_token_ids)} tokens...")

    cache = load_cache()
    cached_ids = {int(k) for k in cache.keys()}
    missing = [tid for tid in all_token_ids if tid not in cached_ids]
    print(f"  Cache: {len(all_token_ids) - len(missing)}/{len(all_token_ids)}")
    print(f"  To fetch: {len(missing)}")

    if missing:
        chunks = [missing[i:i+BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
        total_chunks = len(chunks)
        errors = 0
        done = 0
        chunk_idx = 0

        while chunk_idx < total_chunks:
            window = chunks[chunk_idx:chunk_idx + MAX_WORKERS]

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(make_batch_call, chunk): ci for ci, chunk in enumerate(window)}
                for future in as_completed(futures):
                    result = future.result()
                    for tid, data_item in result.items():
                        cache[str(tid)] = data_item
                        done += 1
                        if "error" in data_item:
                            errors += 1

            chunk_idx += len(window)

            if chunk_idx % 50 == 0 or chunk_idx >= total_chunks:
                pct = (done / len(missing)) * 100
                print(f"  Progress: {pct:.1f}% ({done}/{len(missing)}) | Errors: {errors}")
                save_cache(cache)

            time.sleep(0.15)

        save_cache(cache)
        print(f"  ✅ Done. Errors: {errors}/{len(missing)}")
    else:
        print("  ✅ All tokens cached!")

    return cache


# ===== MAIN =====

def main():
    print("=" * 60)
    print("🔄 veDOLO Dashboard — Data Update")
    print(f"   {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # Phase 1: Fetch transfer events and build ownership
    events = fetch_nft_transfers()
    
    if not events:
        print("⚠️  No transfer events found! Check API key or rate limits.")
        print("   Keeping existing data.")
        sys.exit(0)

    holders, stats = build_ownership(events)

    if not holders:
        print("⚠️  No holders found! Keeping existing data.")
        sys.exit(0)

    # Collect all active token IDs
    all_token_ids = set()
    for h in holders:
        for tid in h["token_ids"]:
            all_token_ids.add(tid)
    all_token_ids = sorted(all_token_ids)

    # Phase 2: Fetch locked DOLO
    cache = fetch_locked_dolo(all_token_ids)

    # Merge locked DOLO into holder data
    print("\n📊 Merging data...")
    total_locked_dolo = 0
    for holder in holders:
        holder_dolo = 0
        token_details = []
        earliest_end = float('inf')
        latest_end = 0

        for tid in holder["token_ids"]:
            ld = cache.get(str(tid), {"amount": 0, "end": 0})
            amt = ld.get("amount", 0)
            end = ld.get("end", 0)
            holder_dolo += amt
            if end > 0:
                earliest_end = min(earliest_end, end)
                latest_end = max(latest_end, end)
            token_details.append({"id": tid, "dolo": round(amt, 2), "end": end})

        holder["total_dolo"] = round(holder_dolo, 2)
        holder["earliest_lock_end"] = earliest_end if earliest_end != float('inf') else 0
        holder["latest_lock_end"] = latest_end
        holder["token_details"] = token_details
        total_locked_dolo += holder_dolo

    # Sort by DOLO descending, assign ranks
    holders.sort(key=lambda h: h["total_dolo"], reverse=True)
    for i, h in enumerate(holders, 1):
        h["rank"] = i

    # Fix address checksums
    try:
        from web3 import Web3
        for h in holders:
            try:
                h["address"] = Web3.to_checksum_address(h["address"])
            except Exception:
                pass
    except ImportError:
        # web3 not available, use simple checksum
        pass

    stats["total_locked_dolo"] = round(total_locked_dolo, 2)

    # Build output
    output = {
        "contract": VEDOLO_CONTRACT,
        "network": "berachain",
        "timestamp": datetime.utcnow().isoformat(),
        "stats": stats,
        "holders": holders,
    }

    # Save JSON
    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    # Save CSV
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Rank", "Address", "NFT_Count", "Total_DOLO", "Earliest_Lock_End", "Latest_Lock_End", "Token_IDs"])
        for h in holders:
            writer.writerow([
                h["rank"], h["address"], h["nft_count"],
                h["total_dolo"],
                datetime.utcfromtimestamp(h["earliest_lock_end"]).strftime('%Y-%m-%d') if h["earliest_lock_end"] > 0 else "",
                datetime.utcfromtimestamp(h["latest_lock_end"]).strftime('%Y-%m-%d') if h["latest_lock_end"] > 0 else "",
                ";".join(str(t) for t in h["token_ids"])
            ])

    # Ensure cache file exists for git
    if not os.path.exists(CACHE_FILE):
        save_cache({})

    print(f"\n💾 Saved: {OUTPUT_JSON}")
    print(f"💾 CSV: {OUTPUT_CSV}")
    print(f"   Total Locked DOLO: {total_locked_dolo:,.2f}")
    print(f"   Holders: {len(holders)}")

    print(f"\n🏆 TOP 5 by DOLO:")
    for h in holders[:5]:
        print(f"   #{h['rank']:<4} {h['address'][:12]}... {h['nft_count']:>4} NFT  {h['total_dolo']:>14,.2f} DOLO")

    print("\n✅ Update complete!")


if __name__ == "__main__":
    main()
