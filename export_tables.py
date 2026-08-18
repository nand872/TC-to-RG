#!/usr/bin/env python3
"""
EXPORT TABLES

Writes the summary tables as CSV. The per-address matches already come
out of analyse_depths.py --dump and timeline_new.py, so this covers the
aggregates that until now only existed as markdown.

Reads the databases directly, so the numbers are recomputed rather than
copied out of RESULTS.md and able to drift from it.

    python3 export_tables.py

Writes:
    results_headline.csv    the four headline rows
    results_lags.csv        the three depth 1 intervals, long format
    results_coverage.csv    the coverage figures
    results_monthly.csv     new shielders and depth 1 by month
"""

import csv
import datetime as dt
import sqlite3

OVERLAP_DB = "overlap112.db"
RAILGUN_DB = "railgun.db"
HOP_DB = "onehop.db"
CACHE_DB = "blocktimes11.db"

BUCKETS = [(None, 0, "negative, out of order"), (0, 1, "same day"),
           (1, 7, "1 to 7 days"), (7, 30, "7 to 30 days"),
           (30, 90, "30 to 90 days"), (90, 365, "90 days to 1 year"),
           (365, None, "over a year")]


def load():
    con = sqlite3.connect(OVERLAP_DB)
    exits, payouts, pools = {}, 0, set()
    for payer, target, block in con.execute(
            "SELECT payer, target, block FROM paid"):
        target = target.lower()
        payouts += 1
        pools.add(payer.lower())
        if target not in exits or block < exits[target]:
            exits[target] = block
    units = con.execute("SELECT COUNT(*) FROM done_units").fetchone()[0]
    con.close()

    con = sqlite3.connect(RAILGUN_DB)
    shields = {r[0].lower(): r[1] for r in con.execute(
        "SELECT sender, MIN(block_number) FROM senders GROUP BY sender")}
    con.close()

    con = sqlite3.connect(HOP_DB)
    funding, edges = {}, 0
    for shielder, funder, block in con.execute(
            "SELECT shielder, funder, block FROM funding"):
        funding.setdefault(shielder.lower(), []).append(
            (funder.lower(), block))
        edges += 1
    con.close()
    return exits, shields, funding, payouts, pools, units * 1000, edges


def times():
    try:
        con = sqlite3.connect(CACHE_DB)
        out = {r[0]: r[1] for r in con.execute("SELECT block, ts FROM times")}
        con.close()
        return out
    except Exception:
        return {}


def write(name, header, rows):
    with open(name, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    print("  wrote {:<24} {:,} rows".format(name, len(rows)))


def main():
    exits, shields, funding, payouts, pools, blocks, edges = load()
    stamps = times()

    depth0 = {a for a in shields if a in exits}
    pairs = {}
    for shielder, funders in funding.items():
        if shielder in depth0:
            continue
        for funder, block in funders:
            if funder not in exits:
                continue
            key = (funder, shielder)
            if key not in pairs or block < pairs[key]:
                pairs[key] = block
    depth1 = {s for _, s in pairs}
    total = len(shields)

    def share(n):
        return round(n / total * 100, 4) if total else ""

    write("results_headline.csv",
          ["group", "shielders", "share_percent"],
          [["reached at depth 0 or 1", len(depth0 | depth1),
            share(len(depth0 | depth1))],
           ["depth 0, same address both sides", len(depth0), share(len(depth0))],
           ["depth 1, funded by a withdrawal address", len(depth1),
            share(len(depth1))],
           ["all railgun shielders", total, 100.0]])

    # lags -----------------------------------------------------------
    legs = {"withdrawal to funding": [], "funding to shield": [],
            "end to end": []}
    for (funder, shielder), block in pairs.items():
        paid = stamps.get(block)
        withdrew = stamps.get(exits.get(funder))
        shielded = stamps.get(shields.get(shielder))
        if paid and withdrew:
            legs["withdrawal to funding"].append((paid - withdrew) / 86400.0)
        if paid and shielded:
            legs["funding to shield"].append((shielded - paid) / 86400.0)
        if withdrew and shielded:
            legs["end to end"].append((shielded - withdrew) / 86400.0)

    rows = []
    for leg, days in legs.items():
        if not days:
            continue
        days = sorted(days)
        for low, high, label in BUCKETS:
            count = sum(1 for d in days
                        if (low is None or d > low)
                        and (high is None or d <= high))
            rows.append([leg, label, count,
                         round(count / len(days) * 100, 2)])
        rows.append([leg, "median days", round(days[len(days) // 2], 1), ""])
    if rows:
        write("results_lags.csv", ["interval", "bucket", "count",
                                   "share_percent"], rows)
    else:
        print("  no lag rows, blocktimes11.db is empty. Run timeline_new.py "
              "first.")

    write("results_coverage.csv", ["measure", "value"],
          [["contracts emitting withdrawal events", len(pools)],
           ["withdrawal events collected", payouts],
           ["distinct recipients", len(exits)],
           ["railgun shielders", total],
           ["shielders with at least one funding row",
            len({s for s in shields if s in funding})],
           ["funding edges examined", edges],
           ["blocks swept", blocks],
           ["depth 1 pairs", len(pairs)],
           ["distinct exits at depth 1", len({e for e, _ in pairs})]])

    # monthly --------------------------------------------------------
    if stamps:
        def month(block):
            ts = stamps.get(block)
            return (dt.datetime.fromtimestamp(ts, dt.timezone.utc)
                    .strftime("%Y-%m") if ts else None)

        base, hit = {}, {}
        for address, block in shields.items():
            key = month(block)
            if not key:
                continue
            base[key] = base.get(key, 0) + 1
            if address in depth1:
                hit[key] = hit.get(key, 0) + 1
        rows = []
        running = 0
        for key in sorted(base):
            count = hit.get(key, 0)
            running += count
            rows.append([key, base[key], count, running,
                         round(count / base[key] * 100, 2) if base[key] else ""])
        write("results_monthly.csv",
              ["month", "new_shielders", "depth1", "cumulative_depth1",
               "share_percent"], rows)

    print("\n  Recomputed from the databases, so these match the current "
          "extraction.")


if __name__ == "__main__":
    main()
