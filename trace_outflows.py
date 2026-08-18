#!/usr/bin/env python3
"""
Trace post-withdrawal outflows from Tornado withdrawal recipients.

This module now works as an explicit multi-phase pipeline:

1. collect raw outbound actions from currently known frontier EOAs
2. classify unseen recipients in bulk
3. build seed-relative paths and edges locally from cached actions

This separation keeps expensive RPC work reusable across reruns and makes hop
experiments much cheaper.
"""

import argparse
import bisect
import hashlib
import json
import multiprocessing
import queue
import sqlite3
import threading
import time
from collections import defaultdict

from protocol_labels import classify_contract
import sweep_rpc as sweep

SEEDS_DB = "tornado_withdrawals.db"
OUT_DB = "tornado_outflows.db"

ADDRESS_CHUNK = 500
FAST_ADDRESS_CANDIDATES = (500, 1000, 2000, 4000, 8000)
DEFAULT_PROCESSES = 4
TRACE_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS nodes (
           address TEXT PRIMARY KEY,
           kind TEXT,
           category TEXT,
           label TEXT,
           first_seen_block INTEGER
       )""",
    """CREATE TABLE IF NOT EXISTS actions (
           sender TEXT,
           recipient TEXT,
           block INTEGER,
           tx_hash TEXT,
           trace_address TEXT,
           tx_index INTEGER,
           action_type TEXT,
           call_type TEXT,
           selector TEXT,
           recipient_kind TEXT,
           recipient_category TEXT,
           recipient_label TEXT,
           PRIMARY KEY (tx_hash, trace_address, sender, recipient)
       )""",
    "CREATE INDEX IF NOT EXISTS i_actions_sender ON actions(sender, block)",
    "CREATE INDEX IF NOT EXISTS i_actions_recipient ON actions(recipient, block)",
    """CREATE TABLE IF NOT EXISTS seed_paths (
           seed TEXT,
           address TEXT,
           hop INTEGER,
           reached_block INTEGER,
           parent_address TEXT,
           via_tx_hash TEXT,
           PRIMARY KEY (seed, address)
       )""",
    "CREATE INDEX IF NOT EXISTS i_seed_paths_address ON seed_paths(address, hop)",
    """CREATE TABLE IF NOT EXISTS seed_edges (
           seed TEXT,
           hop_from INTEGER,
           sender TEXT,
           recipient TEXT,
           block INTEGER,
           tx_hash TEXT,
           trace_address TEXT,
           recipient_kind TEXT,
           recipient_category TEXT,
           recipient_label TEXT,
           PRIMARY KEY (seed, tx_hash, trace_address, sender, recipient)
       )""",
    "CREATE INDEX IF NOT EXISTS i_seed_edges_seed_hop ON seed_edges(seed, hop_from)",
    """CREATE TABLE IF NOT EXISTS address_scans (
           address TEXT PRIMARY KEY,
           from_block INTEGER,
           to_block INTEGER
       )""",
    """CREATE TABLE IF NOT EXISTS collect_windows (
           scan_key TEXT,
           shard INTEGER,
           start_block INTEGER,
           PRIMARY KEY (scan_key, shard, start_block)
       )""",
]


def chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def load_seeds(path):
    con = sqlite3.connect(path)
    seeds = {
        row[0].lower(): row[1]
        for row in con.execute(
            "SELECT recipient, MIN(block) FROM withdrawals GROUP BY recipient"
        )
    }
    con.close()
    return seeds


def init_db(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    for statement in TRACE_SCHEMA:
        con.execute(statement)
    con.commit()
    return con


def db_path_of(con):
    return con.execute("PRAGMA database_list").fetchone()[2]


def ensure_seed_paths(con, seeds):
    # Every withdrawal recipient starts as hop 0 in its own seed-relative path.
    # Later hops are derived locally from the cached action table.
    for address, block in seeds.items():
        con.execute(
            "INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?)",
            (address, "eoa", "seed", "tornado withdrawal recipient", block),
        )
        con.execute(
            "INSERT OR IGNORE INTO seed_paths VALUES (?,?,?,?,?,?)",
            (address, address, 0, block, None, None),
        )
    con.commit()


def action_selector(action):
    data = (action.get("input") or action.get("init") or "0x").lower()
    return data[:10] if len(data) >= 10 else None


def trace_key(item):
    trace_address = item.get("traceAddress") or []
    return ".".join(str(part) for part in trace_address)


def parse_actions(traces):
    rows = []
    recipients = set()
    for item in traces or []:
        if item.get("error"):
            continue
        action = item.get("action") or {}
        sender = (action.get("from") or "").lower()
        recipient = (action.get("to") or "").lower()
        if not sender or not recipient or sender == recipient:
            continue
        # We keep raw actions intentionally lean here. The expensive semantic
        # work happens later in separate classify/build phases.
        block = sweep.hex_block(item.get("blockNumber"))
        tx_hash = (item.get("transactionHash") or "").lower()
        selector = action_selector(action)
        rows.append(
            (
                sender,
                recipient,
                block,
                tx_hash,
                trace_key(item),
                sweep.hex_block(item.get("transactionPosition")),
                item.get("type") or "call",
                action.get("callType"),
                selector,
            )
        )
        recipients.add(recipient)
    return rows, recipients


def probe_trace_cap(node, sample_address):
    """Discover the widest block range this node accepts for trace_filter."""
    return sweep.discover_cap(
        node,
        "trace_filter",
        lambda low, high: [{
            "fromBlock": hex(low),
            "toBlock": hex(high),
            "fromAddress": [sample_address],
        }],
    )


def probe_fast_address_cap(node, addresses, window_cap):
    """Pick an address-list size by throughput, not the maximum the node accepts.

    127k addresses can succeed and still be a bad idea: each call posts several
    megabytes and the node has to filter all of them. A few thousand addresses
    per 1,000-block window is usually much faster overall.
    """
    if not addresses:
        return ADDRESS_CHUNK

    probe_from = 12_000_000
    probe_to = probe_from + window_cap - 1
    best_cap = min(ADDRESS_CHUNK, len(addresses))
    best_score = 0.0

    for cap in FAST_ADDRESS_CANDIDATES:
        cap = min(cap, len(addresses))
        print("    timing {:,} addresses over {:,} blocks...".format(cap, window_cap), flush=True)
        started = time.time()
        try:
            node.call(
                "trace_filter",
                [{
                    "fromBlock": hex(probe_from),
                    "toBlock": hex(probe_to),
                    "fromAddress": addresses[:cap],
                }],
                timeout=60,
            )
        except Exception as problem:
            print("    failed: {}".format(str(problem)[:100]), flush=True)
            break
        elapsed = max(time.time() - started, 0.001)
        # Total runtime scales with (calls * time/call) and calls scale as 1/cap,
        # so cap/elapsed is the right thing to maximize.
        score = cap / elapsed
        print(
            "    {:,} addresses: {:.2f}s  ({:,.0f} addr/s)".format(cap, elapsed, score),
            flush=True,
        )
        if score > best_score:
            best_score = score
            best_cap = cap
        if cap >= len(addresses):
            break
    return best_cap


def fetch_trace_window(node, low, high, addresses, stop):
    payload = [{
        "fromBlock": hex(low),
        "toBlock": hex(high),
        "fromAddress": addresses,
    }]
    try:
        traces = node.call("trace_filter", payload, timeout=180, stop=stop)
        rows, _ = parse_actions(traces)
        return rows, None
    except sweep.Overflow as problem:
        message = str(problem).lower()
        if len(addresses) > 1 and "block range" not in message:
            mid = len(addresses) // 2
            left, err = fetch_trace_window(node, low, high, addresses[:mid], stop)
            if err:
                return left, err
            right, err = fetch_trace_window(node, low, high, addresses[mid:], stop)
            return left + right, err
        return [], "trace_filter failed {:,}-{:,}: {}".format(low, high, str(problem)[:120])
    except Exception as problem:
        return [], "trace_filter failed {:,}-{:,}: {}".format(low, high, str(problem)[:120])


def classify_address_group_worker(task):
    rpc_url, addresses = task
    node = sweep.Node(url=rpc_url)
    result = {}
    calls = [("eth_getCode", [address, "latest"]) for address in addresses]
    try:
        codes = node.batch(calls, timeout=120)
    except Exception:
        return {address: "unknown" for address in addresses}
    for address, code in zip(addresses, codes):
        result[address] = "contract" if code and code != "0x" else "eoa"
    return result


def frontier_for_hop(con, hop):
    return [
        row[0]
        for row in con.execute(
            "SELECT DISTINCT address FROM seed_paths WHERE hop = ?",
            (hop,),
        )
    ]


def needs_scan_rows(con, frontier_addresses, head_block):
    frontier = set(frontier_addresses)
    scanned = {
        address: (from_block, to_block)
        for address, from_block, to_block in con.execute(
            "SELECT address, from_block, to_block FROM address_scans"
        )
    }
    rows = []
    for address, reached in con.execute(
        "SELECT address, MIN(reached_block) FROM seed_paths GROUP BY address"
    ):
        if address not in frontier or reached is None:
            continue
        prior = scanned.get(address)
        # We never want to recollect an address if we already scanned from the
        # same or earlier entry point up to the current head.
        if prior and prior[0] <= reached and prior[1] >= head_block:
            continue
        rows.append((address, reached))
    return rows


def store_action_rows(con, rows):
    inserted = 0
    node_rows = []
    action_rows = []
    for sender, recipient, block, tx_hash, trace_addr, tx_index, action_type, call_type, selector in rows:
        node_rows.append((sender, "eoa", "eoa", None, block))
        node_rows.append((recipient, None, None, None, block))
        action_rows.append(
            (
                sender,
                recipient,
                block,
                tx_hash,
                trace_addr,
                tx_index,
                action_type,
                call_type,
                selector,
                None,
                None,
                None,
            )
        )
    before = con.total_changes
    if node_rows:
        con.executemany("INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?)", node_rows)
    if action_rows:
        con.executemany(
            "INSERT OR IGNORE INTO actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            action_rows,
        )
    inserted = max(con.total_changes - before, 0)
    return inserted


def collect_actions(con, frontier_addresses, head_block, rpc_url=None, processes=1):
    if not frontier_addresses:
        return 0

    needs_scan = needs_scan_rows(con, frontier_addresses, head_block)
    if not needs_scan:
        return 0

    grouped = sorted(needs_scan, key=lambda item: item[1])
    node = sweep.Node(url=rpc_url) if rpc_url else sweep.Node()
    sample_address = grouped[0][0]
    sweep.probe_gzip(node, ("eth_blockNumber", []))
    window_cap = probe_trace_cap(node, sample_address)
    print("  timing address-list sizes for throughput...", flush=True)
    address_cap = probe_fast_address_cap(
        node, [address for address, _ in grouped], window_cap
    )
    shards = list(chunked(grouped, address_cap))
    addr_hash = hashlib.sha1(
        ",".join(sorted(address for address, _ in grouped)).encode()
    ).hexdigest()[:16]
    scan_key = "{}:a{}:w{}".format(addr_hash, address_cap, window_cap)

    done = {
        (shard, start)
        for shard, start in con.execute(
            "SELECT shard, start_block FROM collect_windows WHERE scan_key = ?",
            (scan_key,),
        )
    }
    jobs = []
    for shard_index, shard in enumerate(shards):
        current = min(reached for _, reached in shard)
        while current <= head_block:
            stop_at = min(current + window_cap - 1, head_block)
            if (shard_index, current) not in done:
                jobs.append((shard_index, current, stop_at))
            current = stop_at + 1

    rpc_guess = len(jobs)
    print(
        "  collecting {:,} address(es) in {:,} shard(s), blocks to {:,}, "
        "trace window {:,}, address cap {:,}".format(
            len(needs_scan), len(shards), head_block, window_cap, address_cap
        ),
        flush=True,
    )
    print(
        "  {:,} window calls remaining (gzip {})".format(
            rpc_guess, "on" if getattr(sweep, "_use_gzip", False) else "off"
        ),
        flush=True,
    )
    if not jobs:
        for address, reached in needs_scan:
            con.execute(
                "INSERT OR REPLACE INTO address_scans VALUES (?,?,?)",
                (address, reached, head_block),
            )
        con.commit()
        return 0

    shard_addresses = []
    shard_starts = []
    for shard in shards:
        shard_addresses.append([address for address, _ in shard])
        shard_starts.append([reached for _, reached in shard])
    reached_at = dict(needs_scan)
    out_db = db_path_of(con)
    workers = max(1, processes)
    work = queue.Queue()
    results = queue.Queue(maxsize=sweep.QUEUE_DEPTH)
    stop = threading.Event()
    for job in jobs:
        work.put(job)
    for _ in range(workers):
        work.put(None)

    def worker():
        local = sweep.Node(url=rpc_url) if rpc_url else sweep.Node()
        while not stop.is_set():
            job = work.get()
            if job is None:
                return
            shard_index, low, high = job
            starts = shard_starts[shard_index]
            live_to = bisect.bisect_right(starts, high)
            addresses = shard_addresses[shard_index][:live_to]
            if not addresses:
                results.put(("ok", (shard_index, low, high, [])))
                continue
            rows, error = fetch_trace_window(
                local, low, high, addresses, stop
            )
            if error:
                results.put(("failed", (shard_index, low, high, error)))
                continue
            kept = [row for row in rows if row[2] >= reached_at.get(row[0], 0)]
            results.put(("ok", (shard_index, low, high, kept)))

    def writer():
        nonlocal inserted, failed, finished
        wcon = sqlite3.connect(out_db, timeout=120, check_same_thread=False)
        wcon.execute("PRAGMA journal_mode=WAL")
        wcon.execute("PRAGMA synchronous=NORMAL")
        pending = 0
        while True:
            try:
                item = results.get(timeout=2)
            except queue.Empty:
                if not any(thread.is_alive() for thread in threads) and results.empty():
                    break
                continue
            kind, payload = item
            if kind == "ok":
                shard_index, low, high, rows = payload
                added = store_action_rows(wcon, rows)
                wcon.execute(
                    "INSERT OR IGNORE INTO collect_windows VALUES (?,?,?)",
                    (scan_key, shard_index, low),
                )
                pending += added + 1
                if pending >= 5000:
                    wcon.commit()
                    pending = 0
                with counter_lock:
                    inserted += added
                    finished += 1
            else:
                shard_index, low, high, error = payload
                with counter_lock:
                    failed += 1
                    finished += 1
                    if failed <= 5:
                        print("    {}".format(error), flush=True)
            results.task_done()
        wcon.commit()
        wcon.close()

    inserted = 0
    failed = 0
    finished = 0
    counter_lock = threading.Lock()
    print("  starting {:,} collector thread(s)".format(workers), flush=True)
    print("  Ctrl-C is safe; completed windows are saved\n", flush=True)
    threads = [
        threading.Thread(target=worker, daemon=True) for _ in range(workers)
    ]
    for thread in threads:
        thread.start()
    writer_thread = threading.Thread(target=writer, daemon=True)
    writer_thread.start()

    started = time.time()
    try:
        while finished < rpc_guess and not stop.is_set():
            time.sleep(5)
            elapsed = time.time() - started
            with counter_lock:
                done_jobs = finished
                got = inserted
                lost = failed
            rate = done_jobs / elapsed if elapsed else 0
            remaining = rpc_guess - done_jobs
            eta = remaining / rate if rate else 0
            print(
                "  {:,}/{:,} windows  {:.1f}%  actions {:,}  failed {:,}  "
                "{:,.1f}/s  eta {}    ".format(
                    done_jobs,
                    rpc_guess,
                    100.0 * done_jobs / rpc_guess if rpc_guess else 100,
                    got,
                    lost,
                    rate,
                    sweep.format_duration(eta),
                ),
                flush=True,
            )
    except KeyboardInterrupt:
        print("\n  stopping, please wait...", flush=True)
        stop.set()

    for thread in threads:
        thread.join(timeout=30)
    stop.set()
    writer_thread.join(timeout=120)

    if failed:
        print(
            "  WARNING: {:,} window(s) failed; they were not marked done "
            "and will be retried on the next run.".format(failed),
            flush=True,
        )
    else:
        remaining = con.execute(
            "SELECT COUNT(*) FROM collect_windows WHERE scan_key = ?",
            (scan_key,),
        ).fetchone()[0]
        expected = 0
        for shard in shards:
            current = min(reached for _, reached in shard)
            while current <= head_block:
                expected += 1
                current = min(current + window_cap - 1, head_block) + 1
        if remaining >= expected:
            for address, reached in needs_scan:
                con.execute(
                    "INSERT OR REPLACE INTO address_scans VALUES (?,?,?)",
                    (address, reached, head_block),
                )
            con.commit()
    return inserted


def fetch_contract_flags(addresses, rpc_url=None, processes=1):
    groups = list(chunked(sorted(addresses), 200))
    tasks = [(rpc_url or sweep.NODE, group) for group in groups]
    if processes > 1 and len(tasks) > 1:
        with multiprocessing.Pool(processes=processes) as pool:
            parts = pool.imap_unordered(classify_address_group_worker, tasks)
            parts = list(parts)
    else:
        parts = [classify_address_group_worker(task) for task in tasks]
    kinds = {}
    for part in parts:
        kinds.update(part)
    return kinds


def classify_pending_nodes(con, rpc_url=None, processes=1):
    pending = [
        row[0]
        for row in con.execute(
            "SELECT address FROM nodes WHERE kind IS NULL OR kind = 'unknown'"
        )
    ]
    if not pending:
        return 0

    print("  classifying {:,} unseen address(es)".format(len(pending)))
    kinds = fetch_contract_flags(pending, rpc_url=rpc_url, processes=processes)
    updated = 0
    for address in pending:
        kind = kinds.get(address, "unknown")
        category = "eoa" if kind == "eoa" else ("contract" if kind == "contract" else "unknown")
        before = con.total_changes
        con.execute(
            "UPDATE nodes SET kind = COALESCE(kind, ?), category = COALESCE(category, ?) WHERE address = ?",
            (kind, category, address),
        )
        if con.total_changes > before:
            updated += 1
    con.commit()
    return updated


def enrich_pending_actions(con):
    # Actions are enriched after address-level classification. That lets us tag
    # the same raw trace row as eoa/dex/railgun/token contract without slowing
    # down the collection loop itself.
    rows = con.execute(
        "SELECT sender, recipient, selector FROM actions "
        "WHERE recipient_kind IS NULL OR recipient_category IS NULL"
    ).fetchall()
    if not rows:
        return 0

    node_meta = {
        row[0]: row[1:]
        for row in con.execute("SELECT address, kind, category, label FROM nodes")
    }
    updated = 0
    for sender, recipient, selector in rows:
        kind, category, label = node_meta.get(recipient, (None, None, None))
        if kind == "contract":
            kind, category, label = classify_contract(recipient, selector)
            con.execute(
                "UPDATE nodes SET category = ?, label = COALESCE(label, ?) WHERE address = ?",
                (category, label, recipient),
            )
        elif kind == "eoa":
            category = "eoa"
            label = None
        else:
            kind = kind or "unknown"
            category = category or "unknown"
            label = label or None
        con.execute(
            "UPDATE actions SET recipient_kind = ?, recipient_category = ?, recipient_label = ? "
            "WHERE sender = ? AND recipient = ? AND selector IS ?",
            (kind, category, label, sender, recipient, selector),
        )
        updated += 1
    con.commit()
    return updated


def clear_materialized_graph(con):
    # Seed-relative paths are derived from cached actions, so they can always be
    # rebuilt locally if hop depth or classification rules change.
    con.execute("DELETE FROM seed_edges")
    con.execute("DELETE FROM seed_paths WHERE hop > 0")
    con.commit()


def materialize_hop(con, hop):
    frontier = frontier_for_hop(con, hop)
    if not frontier:
        return 0

    added = 0
    path_rows = con.execute(
        "SELECT seed, address, reached_block FROM seed_paths WHERE hop = ?",
        (hop,),
    ).fetchall()
    by_address = defaultdict(list)
    for seed, address, reached_block in path_rows:
        by_address[address].append((seed, reached_block))

    query = (
        "SELECT sender, recipient, block, tx_hash, trace_address, recipient_kind, recipient_category, recipient_label "
        "FROM actions WHERE sender IN ({}) ORDER BY block"
    ).format(",".join("?" for _ in frontier))

    for sender, recipient, block, tx_hash, trace_address, recipient_kind, recipient_category, recipient_label in con.execute(
        query, frontier
    ):
        for seed, reached_block in by_address.get(sender, []):
            if block < reached_block:
                continue
            con.execute(
                "INSERT OR IGNORE INTO seed_edges VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    seed,
                    hop,
                    sender,
                    recipient,
                    block,
                    tx_hash,
                    trace_address,
                    recipient_kind,
                    recipient_category,
                    recipient_label,
                ),
            )
            # Only EOAs expand the frontier. Contract interactions are recorded
            # as edges but do not fan out into all contract recipients.
            if recipient_kind == "eoa":
                before = con.total_changes
                con.execute(
                    "INSERT OR IGNORE INTO seed_paths VALUES (?,?,?,?,?,?)",
                    (seed, recipient, hop + 1, block, sender, tx_hash),
                )
                if con.total_changes > before:
                    added += 1
    con.commit()
    return added


def build_paths(con, max_hops):
    clear_materialized_graph(con)
    total_added = 0
    for hop in range(max_hops):
        # Each hop uses the already-cached action table, so experimenting with
        # `--max-hops` is mostly local DB work instead of more RPC work.
        added = materialize_hop(con, hop)
        print("  built hop {} -> {} with {:,} new address(es)".format(hop, hop + 1, added))
        total_added += added
        if not added:
            break
    return total_added


def report(con):
    seeds = con.execute("SELECT COUNT(DISTINCT seed) FROM seed_paths").fetchone()[0]
    nodes = con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    actions = con.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
    edges = con.execute("SELECT COUNT(*) FROM seed_edges").fetchone()[0]
    print("=" * 70)
    print("OUTFLOW GRAPH")
    print("=" * 70)
    print("  seeds                {:>12,}".format(seeds))
    print("  nodes                {:>12,}".format(nodes))
    print("  actions              {:>12,}".format(actions))
    print("  seed edges           {:>12,}".format(edges))
    print()
    for category, count in con.execute(
        "SELECT recipient_category, COUNT(*) FROM seed_edges GROUP BY recipient_category ORDER BY 2 DESC"
    ):
        print("  {:<20} {:>10,}".format(category or "unknown", count))


def run_pipeline(args):
    if args.rpc_url:
        sweep.set_node_url(args.rpc_url)

    seeds = load_seeds(args.seeds_db)
    con = init_db(args.out_db)
    ensure_seed_paths(con, seeds)

    node = sweep.Node()
    head_block = args.to_block or int(node.call("eth_blockNumber", []), 16)

    for hop in range(args.max_hops + 1):
        frontier = frontier_for_hop(con, hop)
        if not frontier:
            break
        print("\nHop {} frontier: {:,} address(es)".format(hop, len(frontier)))
        # Phase 1: collect raw actions for the current frontier.
        collected = collect_actions(
            con, frontier, head_block, rpc_url=args.rpc_url, processes=args.processes
        )
        print("  collected {:,} raw action(s)".format(collected))
        # Phase 2: classify any unseen recipients and enrich the cached actions.
        classified = classify_pending_nodes(
            con, rpc_url=args.rpc_url, processes=args.processes
        )
        enriched = enrich_pending_actions(con)
        print("  classified {:,} node(s), enriched {:,} action(s)".format(classified, enriched))
        if hop == args.max_hops:
            break
        # Phase 3: build the next hop locally from the cached action table.
        added = materialize_hop(con, hop)
        print("  added {:,} address(es) to hop {}".format(added, hop + 1))
        if not added:
            break

    report(con)
    con.close()


def export_graph(args):
    con = sqlite3.connect(args.out_db)
    graph = {
        "nodes": [
            {
                "address": address,
                "kind": kind,
                "category": category,
                "label": label,
                "first_seen_block": first_seen_block,
            }
            for address, kind, category, label, first_seen_block in con.execute(
                "SELECT address, kind, category, label, first_seen_block FROM nodes"
            )
        ],
        "seed_paths": [
            {
                "seed": seed,
                "address": address,
                "hop": hop,
                "reached_block": reached_block,
                "parent_address": parent_address,
                "via_tx_hash": via_tx_hash,
            }
            for seed, address, hop, reached_block, parent_address, via_tx_hash in con.execute(
                "SELECT seed, address, hop, reached_block, parent_address, via_tx_hash FROM seed_paths"
            )
        ],
        "seed_edges": [
            {
                "seed": seed,
                "hop_from": hop_from,
                "sender": sender,
                "recipient": recipient,
                "block": block,
                "tx_hash": tx_hash,
                "trace_address": trace_address,
                "recipient_kind": recipient_kind,
                "recipient_category": recipient_category,
                "recipient_label": recipient_label,
            }
            for seed, hop_from, sender, recipient, block, tx_hash, trace_address, recipient_kind, recipient_category, recipient_label in con.execute(
                "SELECT seed, hop_from, sender, recipient, block, tx_hash, trace_address, recipient_kind, recipient_category, recipient_label FROM seed_edges"
            )
        ],
    }
    con.close()
    with open(args.json_out, "w") as handle:
        json.dump(graph, handle, indent=2, sort_keys=True)
    print("wrote {}".format(args.json_out))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Trace post-withdrawal outflows from Tornado recipients.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--seeds-db", default=SEEDS_DB, help="withdrawal collector output DB")
    parser.add_argument("--out-db", default=OUT_DB, help="SQLite DB for traced actions and paths")
    parser.add_argument("--max-hops", type=int, default=1, help="maximum EOA-to-EOA hop depth")
    parser.add_argument("--to-block", type=int, default=None, help="stop tracing at this block")
    parser.add_argument("--rpc-url", default=None, help="Ethereum JSON-RPC URL")
    parser.add_argument(
        "--processes",
        type=int,
        default=DEFAULT_PROCESSES,
        help="collector threads and classifier processes for RPC-heavy phases",
    )
    parser.add_argument("--collect-only", action="store_true", help="only collect raw actions for currently known frontier addresses")
    parser.add_argument("--classify-only", action="store_true", help="only classify unknown nodes and enrich raw actions")
    parser.add_argument("--build-only", action="store_true", help="only rebuild seed-relative paths from cached actions")
    parser.add_argument("--export-json", action="store_true", help="export the current graph to JSON")
    parser.add_argument("--json-out", default="tornado_outflows.json", help="JSON export path")
    return parser


def main():
    args = build_parser().parse_args()
    if args.export_json:
        export_graph(args)
        return

    if args.rpc_url:
        sweep.set_node_url(args.rpc_url)

    seeds = load_seeds(args.seeds_db)
    con = init_db(args.out_db)
    ensure_seed_paths(con, seeds)

    if args.collect_only:
        node = sweep.Node()
        head_block = args.to_block or int(node.call("eth_blockNumber", []), 16)
        for hop in range(args.max_hops + 1):
            frontier = frontier_for_hop(con, hop)
            if not frontier:
                break
            print("\nHop {} frontier: {:,} address(es)".format(hop, len(frontier)))
            collected = collect_actions(
                con, frontier, head_block, rpc_url=args.rpc_url, processes=args.processes
            )
            print("  collected {:,} raw action(s)".format(collected))
        con.close()
        return

    if args.classify_only:
        classified = classify_pending_nodes(
            con, rpc_url=args.rpc_url, processes=args.processes
        )
        enriched = enrich_pending_actions(con)
        print("classified {:,} node(s), enriched {:,} action(s)".format(classified, enriched))
        con.close()
        return

    if args.build_only:
        build_paths(con, args.max_hops)
        report(con)
        con.close()
        return

    con.close()
    run_pipeline(args)


if __name__ == "__main__":
    main()
