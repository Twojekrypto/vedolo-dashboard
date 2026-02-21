#!/usr/bin/env python3
"""
veDOLO Dashboard — Auto-updater (Etherscan V2 API)
Phase 1: Fetches all NFT transfers via Etherscan V2 tokennfttx (paginated, 100% accurate).
Phase 2: Fetches locked DOLO amounts from Berachain RPC (batched, cached).
Outputs: vedolo_holders.json, vedolo_holders.csv
"""
import json, time, os, csv, sys
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===== CONFIG =====
VEDOLO_CONTRACT = "0xCB86B75EE6133d179a12D550b09FB3cdB1e141D4"
ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
CHAIN_ID = 80094  # Berachain
RPC_URL = "https://berachain.drpc.org/"
RPC_URLS = [
    "https://berachain.drpc.org/",
    "https://rpc.berachain.com/",
    "https://berachain-rpc.publicnode.com/",
]
LOCKED_SELECTOR = "0xb45a3c0e"  # locked(uint256)
BALANCE_OF_NFT_SELECTOR = "0xe7e242d4"  # balanceOfNFT(uint256) — current vote weight

BATCH_SIZE = 50
MAX_WORKERS = 4
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(DATA_DIR, "locked_cache.json")
OUTPUT_JSON = os.path.join(DATA_DIR, "vedolo_holders.json")
OUTPUT_CSV = os.path.join(DATA_DIR, "vedolo_holders.csv")

API_KEY = os.environ.get("BERASCAN_API_KEY", "")


# ===== PHASE 1: Fetch all NFT transfers via Etherscan V2 API =====

def fetch_all_nft_transfers():
    """Fetch complete NFT transfer history using startblock/endblock pagination.
    
    Etherscan V2 caps page*offset <= 10,000. To get ALL transactions,
    we paginate by block range: fetch 10k sorted asc, then use the last
    block number as the next startblock.
    """
    print("📡 Phase 1: Fetching NFT transfers via Etherscan V2 API...")

    if not API_KEY:
        print("❌ BERASCAN_API_KEY not set! Cannot fetch data.")
        sys.exit(1)

    all_txs = []
    seen_hashes = set()  # Deduplicate txs spanning block boundaries
    start_block = 0

    while True:
        params = {
            "chainid": CHAIN_ID,
            "module": "account",
            "action": "tokennfttx",
            "contractaddress": VEDOLO_CONTRACT,
            "startblock": start_block,
            "endblock": 99999999,
            "page": 1,
            "offset": 10000,
            "sort": "asc",
            "apikey": API_KEY,
        }

        for retry in range(3):
            try:
                resp = requests.get(ETHERSCAN_V2, params=params, timeout=30)
                data = resp.json()

                if data.get("status") == "1" and isinstance(data.get("result"), list):
                    results = data["result"]

                    # Deduplicate (same block may appear in consecutive calls)
                    new_count = 0
                    for tx in results:
                        tx_key = tx.get("hash", "") + tx.get("tokenID", "")
                        if tx_key not in seen_hashes:
                            seen_hashes.add(tx_key)
                            all_txs.append(tx)
                            new_count += 1

                    print(f"  Block {start_block}+: {len(results)} txs, {new_count} new (total: {len(all_txs)})")

                    if len(results) < 10000:
                        # Got all remaining transfers
                        print(f"  ✅ Fetched all {len(all_txs)} NFT transfers")
                        return all_txs

                    # Move startblock to the last block in results
                    last_block = int(results[-1].get("blockNumber", start_block))
                    if last_block == start_block:
                        # Edge case: >10k txs in same block. Skip to next block.
                        start_block = last_block + 1
                    else:
                        start_block = last_block

                    time.sleep(0.25)  # Rate limit
                    break

                elif "rate" in str(data.get("result", "")).lower() or "max rate" in str(data.get("message", "")).lower():
                    print(f"  Rate limited, waiting {2*(retry+1)}s...")
                    time.sleep(2 * (retry + 1))
                    continue

                else:
                    if data.get("message") == "No transactions found" or (
                        isinstance(data.get("result"), str) and "No transactions" in data["result"]):
                        print(f"  ✅ Fetched all {len(all_txs)} NFT transfers")
                        return all_txs
                    print(f"  ⚠️ API: {data.get('message')}: {str(data.get('result',''))[:100]}")
                    if all_txs:
                        return all_txs
                    sys.exit(1)

            except Exception as e:
                print(f"  Error: {e}, retry {retry+1}/3")
                time.sleep(2 * (retry + 1))
        else:
            print(f"  ❌ Failed after 3 retries at block {start_block}")
            break

    return all_txs




def build_ownership(txs):
    """Build current ownership map from NFT transfers."""
    print("\n📊 Building ownership map...")
    ZERO = "0x0000000000000000000000000000000000000000"

    # Sort by block number and transaction index for correct ordering
    txs.sort(key=lambda t: (int(t.get("blockNumber", 0)), int(t.get("transactionIndex", 0))))

    ownership = {}  # token_id -> current_owner
    all_minted = set()

    for tx in txs:
        token_id = int(tx.get("tokenID", 0))
        from_addr = tx.get("from", "").lower()
        to_addr = tx.get("to", "").lower()

        if from_addr == ZERO.lower():
            all_minted.add(token_id)

        ownership[token_id] = to_addr

    # Count stats
    burned = sum(1 for addr in ownership.values() if addr == ZERO.lower())

    active_owners = {}
    for tid, owner in ownership.items():
        if owner == ZERO.lower():
            continue
        if owner not in active_owners:
            active_owners[owner] = []
        active_owners[owner].append(tid)

    stats = {
        "total_minted": len(all_minted),
        "total_burned": burned,
        "active_nfts": len(all_minted) - burned,
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


# ===== PHASE 2: Fetch locked DOLO + PHASE 3: Fetch vote weights =====

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
    """Fetch locked DOLO for all token IDs."""
    print(f"\n🔒 Phase 2: Fetching locked DOLO for {len(all_token_ids):,} tokens...")

    cache = load_cache()
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
                save_cache(cache)
            time.sleep(0.15)

        save_cache(cache)
        print(f"  ✅ Done. Errors: {errors}/{len(missing):,}")
    else:
        print("  ✅ All cached!")

    return cache


def make_vote_batch_call(token_ids):
    """True JSON-RPC batch call for balanceOfNFT(uint256) — much faster than individual calls."""
    s = requests.Session()
    batch = []
    for i, tid in enumerate(token_ids):
        encoded = hex(tid)[2:].zfill(64)
        batch.append({
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": VEDOLO_CONTRACT, "data": BALANCE_OF_NFT_SELECTOR + encoded}, "latest"],
            "id": i
        })

    out = {}
    for rpc_url in RPC_URLS:
        for retry in range(3):
            try:
                resp = s.post(rpc_url, json=batch, timeout=30,
                              headers={"Content-Type": "application/json"})
                if resp.status_code == 429:
                    time.sleep(1 * (retry + 1))
                    continue
                resp.raise_for_status()
                results = resp.json()
                if not isinstance(results, list):
                    time.sleep(0.5 * (retry + 1))
                    continue
                for r in results:
                    idx = r.get("id", 0)
                    if idx < len(token_ids):
                        tid = token_ids[idx]
                        if "result" in r and r["result"] and len(r["result"]) > 2:
                            val = int(r["result"], 16)
                            out[tid] = val / 1e18
                        else:
                            out[tid] = 0.0
                # Fill any missing
                for tid in token_ids:
                    if tid not in out:
                        out[tid] = 0.0
                return out
            except Exception as e:
                if retry < 2:
                    time.sleep(0.5 * (retry + 1))
        # If this RPC failed, try next one
        if out:
            return out

    # Final fallback: all zeros
    for tid in token_ids:
        if tid not in out:
            out[tid] = 0.0
    return out


def fetch_vote_weights(all_token_ids):
    """Fetch current vote weights for all tokens using true JSON-RPC batch calls.
    Much faster than individual calls — sends BATCH_SIZE calls per request."""
    print(f"\n⚖️  Phase 3: Fetching vote weights for {len(all_token_ids):,} tokens...")

    vote_weights = {}
    chunks = [all_token_ids[i:i+BATCH_SIZE] for i in range(0, len(all_token_ids), BATCH_SIZE)]
    done = 0
    chunk_idx = 0

    while chunk_idx < len(chunks):
        window = chunks[chunk_idx:chunk_idx + MAX_WORKERS]

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(make_vote_batch_call, c): ci for ci, c in enumerate(window)}
            for future in as_completed(futures):
                for tid, weight in future.result().items():
                    vote_weights[tid] = weight
                    done += 1

        chunk_idx += len(window)
        pct = (done / len(all_token_ids)) * 100 if all_token_ids else 100
        print(f"  Progress: {pct:.0f}% ({done:,}/{len(all_token_ids):,})")
        time.sleep(0.1)

    print(f"  ✅ Done. {len(vote_weights):,} vote weights fetched.")
    return vote_weights


# ===== MAIN =====

def main():
    print("=" * 60)
    print("🔄 veDOLO Dashboard — Data Update (Etherscan V2)")
    print(f"   {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # Phase 1: Fetch all NFT transfers
    txs = fetch_all_nft_transfers()

    if not txs:
        print("⚠️  No transfers found! Keeping existing data.")
        sys.exit(0)

    holders, stats = build_ownership(txs)

    if not holders:
        print("⚠️  No holders found!")
        sys.exit(0)

    # Collect all active token IDs
    all_token_ids = sorted({tid for h in holders for tid in h["token_ids"]})

    # Phase 2: Fetch locked DOLO
    cache = fetch_locked_dolo(all_token_ids)

    # Phase 3: Fetch vote weights (always fresh — decays over time)
    vote_weights = fetch_vote_weights(all_token_ids)

    # Merge locked DOLO + vote weights into holders
    print("\n📊 Merging data...")
    total_locked_dolo = 0
    total_vote_weight = 0
    for holder in holders:
        holder_dolo = 0
        holder_vote = 0
        token_details = []
        earliest_end = float('inf')
        latest_end = 0

        for tid in holder["token_ids"]:
            ld = cache.get(str(tid), {"amount": 0, "end": 0})
            amt = ld.get("amount", 0)
            end = ld.get("end", 0)
            vw = vote_weights.get(tid, 0)
            holder_dolo += amt
            holder_vote += vw
            if end > 0:
                earliest_end = min(earliest_end, end)
                latest_end = max(latest_end, end)
            token_details.append({"id": tid, "dolo": round(amt, 2), "end": end, "vote_weight": round(vw, 4)})

        holder["total_dolo"] = round(holder_dolo, 2)
        holder["total_vote_weight"] = round(holder_vote, 4)
        holder["earliest_lock_end"] = earliest_end if earliest_end != float('inf') else 0
        holder["latest_lock_end"] = latest_end
        holder["token_details"] = token_details
        total_locked_dolo += holder_dolo
        total_vote_weight += holder_vote

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
    stats["total_vote_weight"] = round(total_vote_weight, 4)

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
        writer.writerow(["Rank", "Address", "NFT_Count", "Total_DOLO", "Vote_Weight",
                         "Earliest_Lock_End", "Latest_Lock_End", "Token_IDs"])
        for h in holders:
            writer.writerow([
                h["rank"], h["address"], h["nft_count"], h["total_dolo"],
                h.get("total_vote_weight", 0),
                datetime.utcfromtimestamp(h["earliest_lock_end"]).strftime('%Y-%m-%d') if h["earliest_lock_end"] > 0 else "",
                datetime.utcfromtimestamp(h["latest_lock_end"]).strftime('%Y-%m-%d') if h["latest_lock_end"] > 0 else "",
                ";".join(str(t) for t in h["token_ids"])
            ])

    print(f"\n💾 Saved: vedolo_holders.json + .csv")
    print(f"   Locked DOLO: {total_locked_dolo:,.2f}")
    print(f"   Vote Weight: {total_vote_weight:,.2f}")
    print(f"   Holders: {len(holders):,}")

    print(f"\n🏆 TOP 5:")
    for h in holders[:5]:
        print(f"   #{h['rank']:<4} {h['address'][:12]}… {h['nft_count']:>4} NFT  {h['total_dolo']:>14,.2f} DOLO  {h.get('total_vote_weight',0):>12,.2f} veDOLO")

    print("\n✅ Update complete!")

    # Auto-generate dolo_price.json for GitHub Pages (no CORS proxy needed)
    update_dolo_price()


def update_dolo_price():
    """Fetch CoinGecko data and save as static JSON for the dashboard."""
    print("\n💰 Updating dolo_price.json...")
    price_file = os.path.join(DATA_DIR, "dolo_price.json")
    try:
        cg = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=dolomite&vs_currencies=usd"
            "&include_market_cap=true&include_24hr_vol=true&include_24hr_change=true",
            timeout=15
        ).json()
        coins = requests.get(
            "https://api.coingecko.com/api/v3/coins/dolomite"
            "?localization=false&tickers=false&community_data=false&developer_data=false",
            timeout=15
        ).json()

        d = cg.get("dolomite", {})
        md = coins.get("market_data", {})
        data = {
            "price": d.get("usd", 0),
            "market_cap": d.get("usd_market_cap", 0),
            "volume_24h": d.get("usd_24h_vol", 0),
            "change_24h": d.get("usd_24h_change", 0),
            "circulating_supply": md.get("circulating_supply", 0),
            "total_supply": md.get("total_supply", 0),
            "fdv": md.get("fully_diluted_valuation", {}).get("usd", 0),
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }
        with open(price_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"   Price: ${data['price']:.4f}  MC: ${data['market_cap']:,.0f}  FDV: ${data['fdv']:,.0f}")
    except Exception as e:
        print(f"   ⚠️ dolo_price.json update failed: {e}")


if __name__ == "__main__":
    main()
