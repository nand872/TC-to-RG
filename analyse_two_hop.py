#!/usr/bin/env python3
"""
TWO HOP 112

    Tornado pool -> B -> M -> C -> Railgun shield

B withdrew. B paid M. M paid C. C shielded. Three addresses between the
pool and the shield, where depth 1 had two.

WHY THIS DIRECTION

The obvious approach is to ask who funded the 56,960 addresses that
funded shielders. That is backwards expansion and it does not terminate:
measured at 745 edges per block, projecting to roughly eleven billion
rows, because every address has an unbounded number of possible funders.

This asks the opposite question. What did the withdrawal addresses pay?
That set is bounded, because an exit is one account making a handful of
onward payments. The intermediates never enter a query at all. They are
matched locally against onehop.db, which costs nothing.

TWO THINGS THAT MAKE IT AFFORDABLE

An exit cannot pay anyone before it exists. Each address enters the
filter only for blocks after its own withdrawal, so early windows carry
a short list and it grows over time. This is causal ordering, not a time
window, and it cuts the upload substantially.

Addresses that turn out to be services rather than participants are
retired once they exceed MAX_ROWS_PER_PAYER and recorded in hot_keys, so
one exchange deposit address cannot dominate the run.

    python3 analyse_two_hop.py --check     sizes and projected cost, no node
    python3 analyse_two_hop.py             sweep, resumable, Ctrl-C safe
    python3 analyse_two_hop.py --result    join and report
    python3 analyse_two_hop.py --result --dump
"""

import argparse
import bisect
import sqlite3
import threading

import rpc as c

OVERLAP_DB = "overlap112.db"
RAILGUN_DB = "railgun.db"

# Point this at funding_all.db instead if you have merged the token layer.
HOP_DB = "onehop.db"

OUT_DB = "twohop112.db"

# An address making more than this many payments is a service. 0 disables.
MAX_ROWS_PER_PAYER = 250_000

# Exits are admitted to the filter in blocks of this size, rounded up, so
# the live list changes rarely enough to cache. Over inclusion is safe,
# under inclusion would lose edges.
ADMIT_STEP = 100_000

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS paid (payer TEXT, target TEXT, block INTEGER)",
]

_sorted_exits = []
_admit_blocks = []
_sweeper = None
_cache = {}
_cache_lock = threading.Lock()


def load_exits():
    """address -> first block it was paid by a pool."""
    con = sqlite3.connect(OVERLAP_DB)
    first = {}
    for target, block in con.execute("SELECT target, block FROM paid"):
        target = target.lower()
        if target not in first or block < first[target]:
            first[target] = block
    con.close()
    return first


def load_funding():
    """funder -> list of (shielder, block it paid that shielder)"""
    con = sqlite3.connect(HOP_DB)
    table = {}
    rows = 0
    last = 0
    for shielder, funder, block in con.execute(
            "SELECT shielder, funder, block FROM funding"):
        table.setdefault(funder.lower(), []).append((shielder.lower(), block))
        rows += 1
        last = max(last, block or 0)
    con.close()
    return table, rows, last


def load_shielders():
    con = sqlite3.connect(RAILGUN_DB)
    shields = {r[0].lower(): r[1] for r in con.execute(
        "SELECT sender, MIN(block_number) FROM senders GROUP BY sender")}
    con.close()
    return shields


# ----------------------------------------------------------------------


def live_exits(high):
    """Every exit that had withdrawn by this point, minus retired ones."""
    admitted = ((high // ADMIT_STEP) + 1) * ADMIT_STEP
    hot_size = len(_sweeper.hot) if _sweeper else 0
    key = (admitted, hot_size)
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    cut = bisect.bisect_right(_admit_blocks, admitted)
    addresses = [a for a in _sorted_exits[:cut]]
    if hot_size:
        hot = _sweeper.hot
        addresses = [a for a in addresses if a not in hot]
    with _cache_lock:
        if len(_cache) > 8:
            _cache.clear()
        _cache[key] = addresses
    return addresses


def build(low, high):
    return "trace_filter", [{"fromBlock": hex(low), "toBlock": hex(high),
                             "fromAddress": live_exits(high)}]


def rows(traces):
    out = []
    for item in traces or []:
        if item.get("error"):
            continue
        action = item.get("action") or {}
        if action.get("callType") in c.SKIP_CALL_TYPES:
            continue
        if action.get("value") in ("0x0", "0x", "0x00", None):
            continue
        sender, target = action.get("from"), action.get("to")
        if not sender or not target:
            continue
        sender, target = sender.lower(), target.lower()
        if sender == target:
            continue
        out.append((sender, target, c.hex_block(item.get("blockNumber"))))
    return out


# ----------------------------------------------------------------------


def describe():
    exits = load_exits()
    funding, funding_rows, last_funding = load_funding()
    shields = load_shielders()

    intermediates = set(funding)
    already = intermediates & set(exits)

    print("=" * 72)
    print("INPUTS")
    print("=" * 72)
    print("  withdrawal addresses        {:>10,}   from {}".format(
        len(exits), OVERLAP_DB))
    print("  railgun shielders           {:>10,}   from {}".format(
        len(shields), RAILGUN_DB))
    print("  addresses that funded one   {:>10,}   from {}".format(
        len(intermediates), HOP_DB))
    print("  funding edges               {:>10,}".format(funding_rows))
    print("\n  of those funders, {:,} are themselves withdrawal addresses,"
          "\n  which is depth 1 and already counted.".format(len(already)))
    return exits, funding, shields, last_funding


def check(exits, last_funding):
    start = min(exits.values())
    end = last_funding
    span = end - start + 1
    cap = 1000
    calls = span / float(cap)

    # average live list size across the range, given exits enter over time
    blocks = sorted(exits.values())
    total = 0
    steps = 40
    for i in range(steps):
        point = start + (span * i) // steps
        total += bisect.bisect_right(blocks, point)
    average = total / steps

    print("\n" + "=" * 72)
    print("PROJECTED COST")
    print("=" * 72)
    print("  blocks                {:,} to {:,}".format(start, end))
    print("  calls at a 1,000 cap  {:>12,.0f}".format(calls))
    print("  filter, full set      {:>12,.2f} MB per call".format(
        len(exits) * 45 / 1e6))
    print("  filter, average       {:>12,.2f} MB per call".format(
        average * 45 / 1e6))
    print("  upload, full set      {:>12,.0f} GB".format(
        len(exits) * 45 / 1e6 * calls / 1000))
    print("  upload, time bounded  {:>12,.0f} GB".format(
        average * 45 / 1e6 * calls / 1000))
    print("\n  The second figure is what this will actually cost, because an")
    print("  exit only enters the filter for blocks after its withdrawal.")


def sweep(args):
    global _sorted_exits, _admit_blocks, _sweeper
    exits, funding, shields, last_funding = describe()
    if not exits:
        raise SystemExit("\n  No withdrawal addresses loaded.")

    pairs = sorted((block, address) for address, block in exits.items())
    _admit_blocks = [b for b, _ in pairs]
    _sorted_exits = [a for _, a in pairs]

    start = args.from_block or min(exits.values())
    end = args.to_block or last_funding or 0
    if not end:
        raise SystemExit("\n  onehop.db has no funding blocks.")
    check(exits, end)

    node = c.Node()
    c.probe_gzip(node, ("trace_filter", [{
        "fromBlock": hex(1_000_000), "toBlock": hex(1_000_009),
        "fromAddress": [_sorted_exits[0]]}]))
    cap = c.discover_cap(node, "trace_filter", lambda a, b: [{
        "fromBlock": hex(a), "toBlock": hex(b),
        "fromAddress": [_sorted_exits[0]]}])
    print("\n  server range cap      {:>12,} blocks\n".format(cap))

    sweeper = c.RangeSweeper(
        OUT_DB, SCHEMA, "INSERT INTO paid VALUES (?,?,?)",
        build, rows, hub_index=0, hub_limit=MAX_ROWS_PER_PAYER,
        workers=args.workers, label="payments")
    _sweeper = sweeper
    sweeper.run(start, end)

    con = sqlite3.connect(OUT_DB)
    con.execute("CREATE INDEX IF NOT EXISTS i_2_payer ON paid(payer)")
    con.execute("CREATE INDEX IF NOT EXISTS i_2_target ON paid(target)")
    con.commit()
    print("\n  rows            {:,}".format(
        con.execute("SELECT COUNT(*) FROM paid").fetchone()[0]))
    print("  distinct targets  {:,}".format(
        con.execute("SELECT COUNT(DISTINCT target) FROM paid").fetchone()[0]))
    con.close()
    print("\n  Run with --result.")


# ----------------------------------------------------------------------


def result(args):
    exits, funding, shields, _ = describe()
    exit_set = set(exits)

    con = sqlite3.connect(OUT_DB)
    blocks, failed, retired = c.coverage(OUT_DB)

    depth0 = {a for a in shields if a in exit_set}

    depth1 = set()
    for shielder, funders in load_funding_by_shielder().items():
        if shielder in depth0:
            continue
        if any(f in exit_set for f, _ in funders):
            depth1.add(shielder)

    reached = set()
    chains = []
    depth2 = set()
    out_of_order = 0
    edges = 0

    for payer, target, block in con.execute(
            "SELECT payer, target, block FROM paid"):
        edges += 1
        if payer not in exit_set:
            continue
        reached.add(target)
        if target in exit_set or target in shields:
            continue
        for shielder, funded_at in funding.get(target, ()):
            if shielder in depth0 or shielder in depth1:
                continue
            depth2.add(shielder)
            ordered = block <= funded_at
            if not ordered:
                out_of_order += 1
            chains.append((payer, target, shielder, block, funded_at,
                           ordered))
    con.close()

    print("\n" + "=" * 72)
    print("COVERAGE")
    print("=" * 72)
    print("  blocks swept          {:>10,}".format(blocks))
    print("  failed ranges         {:>10,}".format(failed))
    print("  payers retired        {:>10,}".format(retired))
    if failed or retired:
        print("\n  Not complete. State this before quoting counts.")

    print("\n" + "=" * 72)
    print("FORWARD REACH")
    print("=" * 72)
    print("  payments by exits     {:>10,}".format(edges))
    print("  addresses they paid   {:>10,}".format(len(reached)))
    print("  of those, funders of a shielder {:>8,}".format(
        len(reached & set(funding))))
    print("\n  The second figure is the candidate layer. Compare it against")
    print("  {:,} withdrawal addresses to see how fast the set grows per hop."
          .format(len(exit_set)))

    print("\n" + "=" * 72)
    print("RESULTS BY DEPTH")
    print("=" * 72)
    print("  depth 0   exit shields                    {:>8,}".format(
        len(depth0)))
    print("  depth 1   exit funds the shielder         {:>8,}".format(
        len(depth1)))
    print("  depth 2   exit funds a funder of it       {:>8,}".format(
        len(depth2)))
    print("  " + "-" * 50)
    print("  reached at depth 0, 1 or 2                {:>8,} of {:,}".format(
        len(depth0 | depth1 | depth2), len(shields)))
    print("\n  Each shielder is counted at the shortest depth that reaches")
    print("  it, so the three groups do not overlap.")

    print("\n  depth 2 chains                           {:>8,}".format(
        len(chains)))
    print("  distinct intermediates involved           {:>8,}".format(
        len({m for _, m, _, _, _, _ in chains})))
    print("  distinct exits involved                   {:>8,}".format(
        len({e for e, _, _, _, _, _ in chains})))
    print("\n  reported, not filtered")
    print("    exit paid after the intermediate funded {:>8,}".format(
        out_of_order))

    if args.dump and chains:
        with open("depth2.csv", "w") as handle:
            handle.write("exit,intermediate,shielder,exit_paid_block,"
                         "intermediate_funded_block,ordered\n")
            for row in sorted(chains, key=lambda r: r[3]):
                handle.write(",".join(str(x) for x in row) + "\n")
        print("\n  wrote depth2.csv, {:,} rows".format(len(chains)))


def load_funding_by_shielder():
    con = sqlite3.connect(HOP_DB)
    table = {}
    for shielder, funder, block in con.execute(
            "SELECT shielder, funder, block FROM funding"):
        table.setdefault(shielder.lower(), []).append((funder.lower(), block))
    con.close()
    return table


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--result", action="store_true")
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--from-block", type=int, default=None)
    parser.add_argument("--to-block", type=int, default=None)
    parser.add_argument("--workers", type=int, default=c.WORKERS)
    args = parser.parse_args()

    if args.check:
        exits, _, _, last = describe()
        check(exits, args.to_block or last)
        print("\n  Nothing swept. Run without --check to start.")
    elif args.result:
        result(args)
    else:
        sweep(args)


if __name__ == "__main__":
    main()
