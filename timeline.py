#!/usr/bin/env python3
"""
TIMELINE 112

The one hop timeline. Depth 1 only.

    Tornado pool  ->  address B  ->  address C  ->  Railgun shield

B withdrew from a Tornado ETH pool. B then paid C. C shielded. B and C
are different addresses, so this is not the overlap case, which is depth
zero and lives in the other timeline file.

Counted per shielder, by the month C first shielded, against the total
number of addresses that first shielded that month. Read the share
column. Raw counts follow Railgun's own growth, so a busy month for one
hop shielders is usually just a busy month for Railgun.

Standalone. Reads the three databases directly and imports nothing from
the other scripts. Needs only requests.

    python3 timeline.py

Writes timeline_onehop.csv and TIMELINE_ONEHOP.md.
"""

import datetime as dt
import sqlite3

import requests

NODE = "http://88.218.224.19:8546"

OVERLAP_DB = "overlap112.db"
RAILGUN_DB = "railgun.db"
HOP_DB = "onehop.db"
CACHE_DB = "blocktimes11.db"

# Payouts from Tornado pools above which an address is a relayer, not a
# withdrawal recipient.
RELAYER_CUTOFF = 10_000_000

DESIGNATION = "2022-08"
LAUNCH_BLOCK = 13_700_000
LAUNCH_LABEL = "December 2021"

MERGE_BLOCK = 15_537_393
MERGE_EPOCH = 1_663_224_120
BATCH = 100


def approx(block):
    seconds = (12 * (block - MERGE_BLOCK) if block >= MERGE_BLOCK
               else -13.3 * (MERGE_BLOCK - block))
    return dt.datetime.fromtimestamp(
        MERGE_EPOCH + seconds, dt.timezone.utc).strftime("%b %Y")


def month_of(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m")


# ----------------------------------------------------------------------
# loading


def load_exits():
    """Addresses paid by a Tornado pool, with relayers removed."""
    con = sqlite3.connect(OVERLAP_DB)
    hits, first_seen = {}, {}
    for target, block in con.execute("SELECT target, block FROM paid"):
        hits[target] = hits.get(target, 0) + 1
        if target not in first_seen or block < first_seen[target]:
            first_seen[target] = block
    try:
        failed = con.execute("SELECT COUNT(*) FROM failed_ranges").fetchone()[0]
    except Exception:
        failed = 0
    low, high = con.execute(
        "SELECT MIN(block), MAX(block) FROM paid WHERE block > 0").fetchone()
    con.close()
    exits = {a: first_seen[a] for a, n in hits.items() if n <= RELAYER_CUTOFF}
    return exits, len(hits) - len(exits), failed, low, high


def load_shielders():
    con = sqlite3.connect(RAILGUN_DB)
    shields = {r[0].lower(): r[1] for r in con.execute(
        "SELECT sender, MIN(block_number) FROM senders GROUP BY sender")}
    low, high = con.execute(
        "SELECT MIN(block_number), MAX(block_number) FROM senders "
        "WHERE block_number > 0").fetchone()
    con.close()
    return shields, low, high


def load_funding():
    con = sqlite3.connect(HOP_DB)
    table = {}
    for shielder, funder, block in con.execute(
            "SELECT shielder, funder, block FROM funding"):
        table.setdefault(shielder.lower(), []).append((funder.lower(), block))
    low, high = con.execute(
        "SELECT MIN(block), MAX(block) FROM funding WHERE block > 0").fetchone()
    con.close()
    return table, low, high


# ----------------------------------------------------------------------


def block_times(blocks):
    con = sqlite3.connect(CACHE_DB)
    con.execute("CREATE TABLE IF NOT EXISTS times "
                "(block INTEGER PRIMARY KEY, ts INTEGER)")
    con.commit()
    known = {r[0]: r[1] for r in con.execute("SELECT block, ts FROM times")}
    missing = sorted({b for b in blocks if b and b not in known})

    if missing:
        print("  fetching {:,} block timestamps ({:,} already cached)".format(
            len(missing), len(known)))
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        for start in range(0, len(missing), BATCH):
            group = missing[start:start + BATCH]
            payload = [{"jsonrpc": "2.0", "id": i,
                        "method": "eth_getBlockByNumber",
                        "params": [hex(b), False]}
                       for i, b in enumerate(group)]
            try:
                answers = session.post(NODE, json=payload, timeout=180).json()
            except Exception as problem:
                print("\n  fetch failed at {}: {}".format(
                    start, str(problem)[:60]))
                continue
            if isinstance(answers, dict):
                answers = [answers]
            batch = []
            for answer in answers:
                block = group[answer.get("id", 0)]
                result = answer.get("result")
                if result and result.get("timestamp"):
                    batch.append((block, int(result["timestamp"], 16)))
            if batch:
                con.executemany(
                    "INSERT OR REPLACE INTO times VALUES (?,?)", batch)
                con.commit()
                known.update(dict(batch))
            print("    {:,}/{:,}    ".format(
                min(start + BATCH, len(missing)), len(missing)), end="\r")
        print()
    con.close()
    return known


def months_between(first, last):
    out = []
    year, mon = int(first[:4]), int(first[5:])
    while "{:04d}-{:02d}".format(year, mon) <= last:
        out.append("{:04d}-{:02d}".format(year, mon))
        mon += 1
        if mon > 12:
            year, mon = year + 1, 1
    return out


def lag_table(title, days):
    days = sorted(d for d in days if d is not None)
    if not days:
        return
    print("\n  {}".format(title))
    buckets = [(None, 0, "negative, out of order"), (0, 1, "same day"),
               (1, 7, "1 to 7 days"), (7, 30, "7 to 30 days"),
               (30, 90, "30 to 90 days"), (90, 365, "90 days to 1 year"),
               (365, None, "over a year")]
    for low, high, label in buckets:
        count = sum(1 for d in days
                    if (low is None or d > low) and (high is None or d <= high))
        print("    {:<26} {:>6,}  {:>5.1f}%  {}".format(
            label, count, count / len(days) * 100,
            "#" * int(count / len(days) * 34)))
    print("    median {:,.1f} days   longest {:,.0f} days".format(
        days[len(days) // 2], days[-1]))


# ----------------------------------------------------------------------


def main():
    exits, relayers, failed, pay_low, pay_high = load_exits()
    shields, sh_low, sh_high = load_shielders()
    funding, fund_low, fund_high = load_funding()

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

    print("=" * 74)
    print("ONE HOP  ( depth 1 )")
    print("=" * 74)
    print("  Tornado pool -> B -> C -> Railgun shield, B and C different\n")
    print("  withdrawal addresses     {:>10,}   ({:,} relayers removed)".format(
        len(exits), relayers))
    print("  railgun shielders        {:>10,}".format(len(shields)))
    print("  exit to shielder pairs   {:>10,}".format(len(pairs)))
    print("  distinct shielders       {:>10,}".format(len(depth1)))
    print("  distinct exits           {:>10,}".format(
        len({e for e, _ in pairs})))
    print("  excluded as depth 0      {:>10,}".format(len(depth0)))

    print("\n" + "=" * 74)
    print("HOW FAR BACK THIS MEASURES")
    print("=" * 74)
    for name, low, high, note in (
            ("overlap.db  payouts", pay_low, pay_high, ""),
            ("railgun.db  shields", sh_low, sh_high, ""),
            ("onehop.db   funding", fund_low, fund_high, "")):
        print("  {:<22} {} to {}   blocks {:,} to {:,}".format(
            name, approx(low or 0), approx(high or 0), low or 0, high or 0))
    binding = max(v for v in (pay_low, sh_low, fund_low) if v)
    print("\n  Depth 1 needs all three, so it measures from {}.".format(
        approx(binding)))
    if binding > LAUNCH_BLOCK:
        print("  That is later than {}, so the first months of Railgun".format(
            LAUNCH_LABEL))
        print("  are not covered. Widen the shielder extraction first,")
        print("  then rerun the funding sweep against the wider set.")
    else:
        print("  That reaches {}, so the series is complete.".format(
            LAUNCH_LABEL))

    covered = len({s for s in shields if s in funding})
    print("\n  shielders with any funding row  {:,} of {:,}  {:.1f}%".format(
        covered, len(shields),
        covered / len(shields) * 100 if shields else 0))
    print("  A shielder with no funding row cannot be reached at depth 1,")
    print("  whether or not a withdrawal address actually paid it.")

    if not pairs:
        print("\n  No depth 1 pairs. Nothing to plot.")
        return

    # timestamps -----------------------------------------------------
    needed = set(shields.values()) | set(pairs.values())
    needed |= {exits[e] for e, _ in pairs}
    print()
    times = block_times(needed)
    if not times:
        raise SystemExit("  No timestamps available. Is the node reachable?")

    baseline = {}
    for block in shields.values():
        ts = times.get(block)
        if ts:
            baseline[month_of(ts)] = baseline.get(month_of(ts), 0) + 1

    by_shield = {}
    for shielder in depth1:
        ts = times.get(shields.get(shielder))
        if ts:
            by_shield[month_of(ts)] = by_shield.get(month_of(ts), 0) + 1

    by_funding = {}
    for _, block in pairs.items():
        ts = times.get(block)
        if ts:
            by_funding[month_of(ts)] = by_funding.get(month_of(ts), 0) + 1

    if not by_shield:
        print("  Nothing could be dated.")
        return

    first = min(by_shield)
    last = max(max(by_shield), max(baseline) if baseline else first)
    months = months_between(first, last)
    peak = max(by_shield.values())

    print("\n" + "=" * 74)
    print("ONE HOP SHIELDERS BY MONTH, FROM THE FIRST")
    print("=" * 74)
    print("  {:<9} {:>8} {:>8} {:>11} {:>8}  {}".format(
        "month", "one hop", "cumul", "shielders", "share", ""))
    print("  " + "-" * 70)
    running = 0
    for key in months:
        count = by_shield.get(key, 0)
        running += count
        total = baseline.get(key, 0)
        pct = "{:.2f}%".format(count / total * 100) if total else "-"
        mark = " <- designation" if key == DESIGNATION else ""
        print("  {:<9} {:>8,} {:>8,} {:>11,} {:>8}  {}{}".format(
            key, count, running, total, pct,
            "#" * int(count / peak * 20) if peak else "", mark))

    print("\n  first one hop shielder   {}".format(first))
    print("  busiest month            {} with {:,}".format(
        max(by_shield, key=by_shield.get), peak))

    print("\n" + "=" * 74)
    print("LAGS")
    print("=" * 74)
    lag_table("withdrawal to funding, how long B held it", [
        (times[block] - times[exits[funder]]) / 86400.0
        for (funder, _), block in pairs.items()
        if times.get(block) and times.get(exits.get(funder))])
    lag_table("funding to shield, how long C waited", [
        (times[shields[shielder]] - times[block]) / 86400.0
        for (_, shielder), block in pairs.items()
        if times.get(block) and shielder in shields
        and times.get(shields[shielder])])
    lag_table("withdrawal to shield, end to end", [
        (times[shields[shielder]] - times[exits[funder]]) / 86400.0
        for (funder, shielder), _ in pairs.items()
        if shielder in shields and times.get(shields[shielder])
        and times.get(exits.get(funder))])

    # files ----------------------------------------------------------
    with open("timeline_onehop.csv", "w") as handle:
        handle.write("month,onehop_shielders,cumulative,pairs_by_funding,"
                     "all_new_shielders,share_percent\n")
        running = 0
        for key in months:
            count = by_shield.get(key, 0)
            running += count
            total = baseline.get(key, 0)
            handle.write("{},{},{},{},{},{}\n".format(
                key, count, running, by_funding.get(key, 0), total,
                "{:.4f}".format(count / total * 100) if total else ""))

    with open("TIMELINE_ONEHOP.md", "w") as handle:
        handle.write("# One hop shielders by month\n\n")
        handle.write("A Tornado ETH pool paid address B, B paid address C, "
                     "and C shielded into Railgun. B and C are different "
                     "addresses, so the overlap cases are excluded and "
                     "counted separately.\n\n")
        handle.write("Dated by the month C first shielded, using block "
                     "timestamps from an archive node. Measured from {}, "
                     "which is where the narrowest of the three source "
                     "datasets begins.\n\n".format(approx(binding)))
        handle.write("Read the share column. Absolute counts track "
                     "Railgun's overall growth.\n\n")
        handle.write("| Month | One hop | Cumulative | All new shielders "
                     "| Share |\n|---|---:|---:|---:|---:|\n")
        running = 0
        for key in months:
            count = by_shield.get(key, 0)
            running += count
            total = baseline.get(key, 0)
            label = "**{}**".format(key) if key == DESIGNATION else key
            handle.write("| {} | {:,} | {:,} | {:,} | {} |\n".format(
                label, count, running, total,
                "{:.2f}%".format(count / total * 100) if total else "-"))
        handle.write("\nAugust 2022, the designation month, in bold.\n")

    if failed:
        print("\n  {} uncollected range(s) in overlap.db. Early months may"
              " be understated.".format(failed))
    print("\n  wrote timeline_onehop.csv and TIMELINE_ONEHOP.md")


if __name__ == "__main__":
    main()
