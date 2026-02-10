#!/usr/bin/env python3
"""
veDOLO Dashboard — Auto-updater
Phase 1: Build ownership map from Transfer events via RPC eth_getLogs (10k block chunks).
Phase 2: Fetch locked DOLO amounts from Berachain RPC (batch calls with caching).
Outputs: vedolo_holders.json, vedolo_holders.csv

Uses progress file to resume from last fetched block — first full run may take ~5-10min,
subsequent runs only fetch new blocks since last time.
"""
import json, time, os, csv, sys
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===== CONFIG =====
VEDOLO_CONTRACT = "0xCB86B75EE6133d179a12D550b09FB3cdB1e141D4"
RPC_URL = "https://berachain.drpc.org/"
LOCKED_SELECTOR = "0xb45a3c0e"  # locked(uint256)
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
CONTRACT_DEPLOY_BLOCK = 4_990_000  # Contract deployed around block 5M
BLOCK_CHUNK = 10_000  # Max per eth_getLogs call on free tier

BATCH_SIZE = 3  # RPC batch size for locked() calls
MAX_WORKERS = 8
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(DATA_DIR, "locked_cache.json")
EVENTS_CACHE = os.path.join(DATA_DIR, "events_cache.json")
OUTPUT_JSON = os.path.join(DATA_DIR, "vedolo_holders.json")
OUTPUT_CSV = os.path.join(DATA_DIR, "vedolo_holders.csv")


# ===== HELPERS =====

def rpc_call(method, params):
    """Single JSON-RPC call."""
    for retry in range(3):
        try:
            resp = requests.post(RPC_URL, json={
                "jsonrpc": "2.0", "method": method, "params": params, "id": 1
            }, timeout=15, headers={"Content-Type": "application/json"})
            data = resp.json()
            if "error" in data:
                if "rate" in str(data["error"]).lower():
                    time.sleep(2 * (retry + 1))
                    continue
                return None, data["error"]
            return data.get("result"), None
        except Exception as e:
            time.sleep(1 * (retry + 1))
    return None, "max retries reached"


def get_latest_block():
    result, err = rpc_call("eth_blockNumber", [])
    if result:
        return int(result, 16)
    raise Exception(f"Failed to get block number: {err}")


# ===== PHASE 1: Fetch Transfer events via RPC =====

def load_events_cache():
    if os.path.exists(EVENTS_CACHE):
        with open(EVENTS_CACHE) as f:
            return json.load(f)
    return {"last_block": CONTRACT_DEPLOY_BLOCK, "events": []}


def save_events_cache(cache):
    tmp = EVENTS_CACHE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, EVENTS_CACHE)


def fetch_logs_chunk(from_block, to_block):
    """Fetch Transfer logs for a single block range."""
    result, err = rpc_call("eth_getLogs", [{
        "address": VEDOLO_CONTRACT,
        "topics": [TRANSFER_TOPIC],
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
    }])
    if result is not None:
        return result
    return []


def fetch_all_transfer_events():
    """Fetch all Transfer events using block-range pagination with caching."""
    print("📡 Phase 1: Fetching Transfer events via RPC...")

    ecache = load_events_cache()
    start_block = ecache["last_block"]
    latest_block = get_latest_block()

    print(f"  Block range: {start_block:,} → {latest_block:,} ({latest_block - start_block:,} blocks)")

    if start_block >= latest_block:
        print("  ✅ Already up to date!")
        return ecache["events"]

    # Build chunk ranges
    chunks = []
    b = start_block
    while b < latest_block:
        end = min(b + BLOCK_CHUNK - 1, latest_block)
        chunks.append((b, end))
        b = end + 1

    print(f"  Chunks to fetch: {len(chunks)}")

    new_events = []
    fetched = 0

    # Fetch chunks with parallelism (4 concurrent to avoid rate limits)
    for i in range(0, len(chunks), 4):
        batch = chunks[i:i+4]

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(fetch_logs_chunk, fb, tb): (fb, tb)
                       for fb, tb in batch}
            for future in as_completed(futures):
                events = future.result()
                for event in events:
                    topics = event.get("topics", [])
                    if len(topics) >= 4:
                        new_events.append({
                            "b": int(event["blockNumber"], 16),
                            "f": "0x" + topics[1][-40:],
                            "t": "0x" + topics[2][-40:],
                            "id": int(topics[3], 16),
                        })
                fetched += len(batch)

        if fetched % 40 == 0 or i + 4 >= len(chunks):
            pct = (fetched / len(chunks)) * 100
            print(f"  Progress: {pct:.0f}% ({fetched}/{len(chunks)} chunks, {len(new_events)} new events)")

        time.sleep(0.1)

    # Merge with existing events & save
    all_events = ecache["events"] + new_events
    ecache["events"] = all_events
    ecache["last_block"] = latest_block
    save_events_cache(ecache)

    print(f"  ✅ Total events: {len(all_events)} ({len(new_events)} new)")
    return all_events


def build_ownership(events):
    """Build current ownership map from Transfer events."""
    print("\n📊 Building ownership map...")
    ZERO = "0x" + "0" * 40
    ownership = {}  # token_id -> current_owner

    # Sort by block to ensure correct order
    events.sort(key=lambda e: (e["b"], e["id"]))

    for event in events:
        ownership[event["id"]] = event["t"]

    # Build stats
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

    print(f"  Minted: {stats['total_minted']:,}  Burned: {stats['total_burned']:,}  Active: {stats['active_nfts']:,}")
    print(f"  Unique holders: {stats['unique_holders']:,}")

    return holders, stats


# ===== PHASE 2: Fetch locked DOLO =====

def make_batch_call(token_ids):
    """Batch RPC call for locked(uint256)."""
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


def load_locked_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_locked_cache(cache):
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, CACHE_FILE)


def fetch_locked_dolo(all_token_ids):
    """Fetch locked DOLO for all token IDs."""
    print(f"\n🔒 Phase 2: Fetching locked DOLO for {len(all_token_ids):,} tokens...")

    cache = load_locked_cache()
    cached_ids = {int(k) for k in cache.keys()}
    missing = [tid for tid in all_token_ids if tid not in cached_ids]
    print(f"  Cached: {len(all_token_ids) - len(missing):,}/{len(all_token_ids):,}")
    print(f"  To fetch: {len(missing):,}")

    if missing:
        chunks = [missing[i:i+BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
        errors = 0
        done = 0
        chunk_idx = 0

        while chunk_idx < len(chunks):
            window = chunks[chunk_idx:chunk_idx + MAX_WORKERS]

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(make_batch_call, c): ci for ci, c in enumerate(window)}
                for future in as_completed(futures):
                    for tid, data_item in future.result().items():
                        cache[str(tid)] = data_item
                        done += 1
                        if "error" in data_item:
                            errors += 1

            chunk_idx += len(window)
            if chunk_idx % 50 == 0 or chunk_idx >= len(chunks):
                pct = (done / len(missing)) * 100
                print(f"  Progress: {pct:.0f}% ({done:,}/{len(missing):,}) | Errors: {errors}")
                save_locked_cache(cache)
            time.sleep(0.15)

        save_locked_cache(cache)
        print(f"  ✅ Done. Errors: {errors}/{len(missing):,}")
    else:
        print("  ✅ All cached!")

    return cache


# ===== MAIN =====

def main():
    print("=" * 60)
    print("🔄 veDOLO Dashboard — Data Update")
    print(f"   {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # Phase 1: Fetch Transfer events
    events = fetch_all_transfer_events()

    if not events:
        print("⚠️  No events found! Keeping existing data.")
        sys.exit(0)

    holders, stats = build_ownership(events)

    if not holders:
        print("⚠️  No holders found!")
        sys.exit(0)

    # Collect all active token IDs
    all_token_ids = sorted({tid for h in holders for tid in h["token_ids"]})

    # Phase 2: Fetch locked DOLO
    cache = fetch_locked_dolo(all_token_ids)

    # Merge locked DOLO into holders
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

    # Sort & rank
    holders.sort(key=lambda h: h["total_dolo"], reverse=True)
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
        pass

    stats["total_locked_dolo"] = round(total_locked_dolo, 2)

    output = {
        "contract": VEDOLO_CONTRACT,
        "network": "berachain",
        "timestamp": datetime.utcnow().isoformat(),
        "stats": stats,
        "holders": holders,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Rank", "Address", "NFT_Count", "Total_DOLO",
                         "Earliest_Lock_End", "Latest_Lock_End", "Token_IDs"])
        for h in holders:
            writer.writerow([
                h["rank"], h["address"], h["nft_count"], h["total_dolo"],
                datetime.utcfromtimestamp(h["earliest_lock_end"]).strftime('%Y-%m-%d') if h["earliest_lock_end"] > 0 else "",
                datetime.utcfromtimestamp(h["latest_lock_end"]).strftime('%Y-%m-%d') if h["latest_lock_end"] > 0 else "",
                ";".join(str(t) for t in h["token_ids"])
            ])

    print(f"\n💾 Saved: vedolo_holders.json + .csv")
    print(f"   Locked DOLO: {total_locked_dolo:,.2f}")
    print(f"   Holders: {len(holders):,}")

    print(f"\n🏆 TOP 5:")
    for h in holders[:5]:
        print(f"   #{h['rank']:<4} {h['address'][:12]}… {h['nft_count']:>4} NFT  {h['total_dolo']:>14,.2f} DOLO")

    print("\n✅ Update complete!")


if __name__ == "__main__":
    main()
