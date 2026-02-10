#!/usr/bin/env python3
"""
veDOLO Dashboard — Auto-updater
Fetches holder data from BeraScan API + locked DOLO amounts from Berachain RPC.
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

# BeraScan API key (optional, higher rate limits with key)
BERASCAN_API_KEY = os.environ.get("BERASCAN_API_KEY", "")


# ===== PHASE 1: Fetch holders from BeraScan =====

def fetch_total_supply():
    """Fetch total minted token count from BeraScan."""
    params = {
        "module": "stats",
        "action": "tokensupply",
        "contractaddress": VEDOLO_CONTRACT,
    }
    if BERASCAN_API_KEY:
        params["apikey"] = BERASCAN_API_KEY
    resp = requests.get(BERASCAN_API, params=params, timeout=30)
    data = resp.json()
    if data.get("status") == "1":
        return int(data["result"])
    return None


def fetch_token_holders_page(page, offset=1000):
    """Fetch one page of token holders from BeraScan."""
    params = {
        "module": "token",
        "action": "tokenholderlist",
        "contractaddress": VEDOLO_CONTRACT,
        "page": page,
        "offset": offset,
    }
    if BERASCAN_API_KEY:
        params["apikey"] = BERASCAN_API_KEY

    for retry in range(3):
        try:
            resp = requests.get(BERASCAN_API, params=params, timeout=30)
            data = resp.json()
            if data.get("status") == "1" and data.get("result"):
                return data["result"]
            if data.get("message") == "No token holder found":
                return []
            time.sleep(1 * (retry + 1))
        except Exception as e:
            print(f"  ⚠️ Page {page} error: {e}")
            time.sleep(2 * (retry + 1))
    return []


def fetch_all_holders():
    """Fetch all veDOLO NFT holders from BeraScan API."""
    print("📡 Phase 1: Fetching holders from BeraScan...")
    all_holders = []
    page = 1

    while True:
        holders = fetch_token_holders_page(page)
        if not holders:
            break
        all_holders.extend(holders)
        print(f"  Page {page}: {len(holders)} entries (total: {len(all_holders)})")
        page += 1
        time.sleep(0.3)

    # Aggregate by address
    address_map = {}
    for entry in all_holders:
        addr = entry.get("TokenHolderAddress", "")
        qty = int(entry.get("TokenHolderQuantity", "0"))
        if addr and qty > 0:
            if addr not in address_map:
                address_map[addr] = {"address": addr, "nft_count": 0, "token_ids": []}
            address_map[addr]["nft_count"] = qty

    print(f"  ✅ Unique holders: {len(address_map)}")
    return list(address_map.values())


def fetch_tokens_for_holder(address, max_tokens=500):
    """Fetch token IDs owned by a specific address."""
    token_ids = []
    page = 1

    while True:
        params = {
            "module": "account",
            "action": "tokennfttx",
            "contractaddress": VEDOLO_CONTRACT,
            "address": address,
            "page": page,
            "offset": 100,
            "sort": "asc",
        }
        if BERASCAN_API_KEY:
            params["apikey"] = BERASCAN_API_KEY

        try:
            resp = requests.get(BERASCAN_API, params=params, timeout=30)
            data = resp.json()

            if data.get("status") != "1" or not data.get("result"):
                break

            for tx in data["result"]:
                tid = int(tx.get("tokenID", 0))
                if tx.get("to", "").lower() == address.lower():
                    if tid not in token_ids:
                        token_ids.append(tid)
                elif tx.get("from", "").lower() == address.lower():
                    if tid in token_ids:
                        token_ids.remove(tid)

            if len(data["result"]) < 100:
                break
            page += 1
            time.sleep(0.25)

        except Exception as e:
            print(f"  ⚠️ Token fetch error for {address[:10]}...: {e}")
            break

    return sorted(token_ids)


def fetch_all_token_ids(holders):
    """Fetch token IDs for all holders using ERC721 enumeration via RPC."""
    print("\n📦 Fetching token IDs via RPC enumeration...")

    # Alternative: use tokenOfOwnerByIndex if available
    # First try to get all token IDs from transfer events
    all_token_ids = set()
    holder_tokens = {}

    # Fetch transfer events to build ownership map
    print("  Fetching Transfer events from BeraScan...")
    ownership = {}  # token_id -> current_owner
    page = 1
    total_events = 0

    while True:
        params = {
            "module": "logs",
            "action": "getLogs",
            "address": VEDOLO_CONTRACT,
            "topic0": "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",  # Transfer
            "page": page,
            "offset": 1000,
            "sort": "asc",
        }
        if BERASCAN_API_KEY:
            params["apikey"] = BERASCAN_API_KEY

        try:
            resp = requests.get(BERASCAN_API, params=params, timeout=60)
            data = resp.json()

            if data.get("status") != "1" or not data.get("result"):
                break

            events = data["result"]
            for event in events:
                topics = event.get("topics", [])
                if len(topics) >= 4:
                    token_id = int(topics[3], 16)
                    to_addr = "0x" + topics[2][-40:]
                    ownership[token_id] = to_addr.lower()
                    all_token_ids.add(token_id)

            total_events += len(events)
            print(f"  Page {page}: {len(events)} events (total: {total_events}, tokens: {len(all_token_ids)})")

            if len(events) < 1000:
                break
            page += 1
            time.sleep(0.3)

        except Exception as e:
            print(f"  ⚠️ Event fetch error on page {page}: {e}")
            time.sleep(2)
            page += 1

    # Build holder -> token_ids map
    ZERO = "0x" + "0" * 40
    active_tokens = 0
    burned_tokens = 0

    for tid, owner in ownership.items():
        if owner == ZERO:
            burned_tokens += 1
            continue
        active_tokens += 1
        checksum_owner = owner  # lowercase
        if checksum_owner not in holder_tokens:
            holder_tokens[checksum_owner] = []
        holder_tokens[checksum_owner].append(tid)

    total_minted = len(all_token_ids)

    print(f"  ✅ Total minted: {total_minted}, Active: {active_tokens}, Burned: {burned_tokens}")

    # Merge into holders
    final_holders = []
    for owner_addr, tids in holder_tokens.items():
        # Try to find checksum match
        final_holders.append({
            "address": owner_addr,
            "nft_count": len(tids),
            "token_ids": sorted(tids),
        })

    return final_holders, {
        "total_minted": total_minted,
        "total_burned": burned_tokens,
        "active_nfts": active_tokens,
        "unique_holders": len(holder_tokens),
    }


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

    # Phase 1: Fetch holders + token IDs from Transfer events
    holders, stats = fetch_all_token_ids(None)

    # Collect all token IDs
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
    from web3 import Web3
    for h in holders:
        try:
            h["address"] = Web3.to_checksum_address(h["address"])
        except Exception:
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
