#!/usr/bin/env python3
"""
WITHDRAWALS 112

Every Tornado Cash withdrawal, in every denomination, with the recipient
and the relayer named separately.

WHY THIS REPLACES THE TRACE SWEEP

overlap.db was built with trace_filter, which finds payments by looking
at the ETH value field. A pool paying out DAI moves no ETH, so its
payout has a value of zero and is discarded, and the real record is a log
emitted by the DAI contract that a trace sweep never reads. That is why
28 of 48 pool contracts looked silent.

Every pool emits the same event regardless of what it pays out:

    Withdrawal(address to, bytes32 nullifierHash,
               address indexed relayer, uint256 fee)

The event comes from the pool, not from the token, so one log sweep
filtered on that signature catches all of them.

TWO THINGS THIS GETS FOR FREE

No address list. Filtering on the event alone, with no address filter,
finds every contract that ever emitted it. The pools discover themselves,
including any you did not know about. The payload is one topic hash, so
the block range cap costs almost nothing.

No relayer guesswork. The recipient sits in the data and the relayer in
an indexed topic, as separate fields. The frequency cutoff that removed
200 addresses from the trace based set is not needed here, because the
two roles are stated rather than inferred.

    python3 extract_withdrawals.py              sweep
    python3 extract_withdrawals.py --pools      what emitted the event, with labels
    python3 extract_withdrawals.py --summary
    python3 extract_withdrawals.py --export     write overlap112.db for the analysis

After --export, set OVERLAP_DB = "overlap112.db" and RELAYER_CUTOFF to a
large number at the top of analyse_depths.py, then rerun. The cutoff is
harmless but no longer does anything, since relayers are already out.
"""

import argparse
import sqlite3

from Crypto.Hash import keccak

import rpc as c

OUT_DB = "withdrawals112.db"
EXPORT_DB = "overlap112.db"

# Tornado Cash first deployment. Nothing earlier can be a withdrawal.
START_BLOCK = 9_116_000

# Contracts emitting fewer than this are almost certainly not Tornado.
MIN_EVENTS = 20

KNOWN = {
    "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc": "0.1 ETH",
    "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936": "1 ETH",
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf": "10 ETH",
    "0xa160cdab225685da1d56aa342ad8841c3b53f291": "100 ETH",
}

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS withdrawals (
           tx_hash TEXT, log_index INTEGER, block INTEGER,
           pool TEXT, recipient TEXT, relayer TEXT, fee TEXT,
           PRIMARY KEY (tx_hash, log_index))""",
    "CREATE INDEX IF NOT EXISTS i_w_pool ON withdrawals(pool)",
    "CREATE INDEX IF NOT EXISTS i_w_recip ON withdrawals(recipient)",
    """CREATE TABLE IF NOT EXISTS pool_info (
           pool TEXT PRIMARY KEY, token TEXT, denomination TEXT,
           symbol TEXT)""",
]


def sig(text):
    digest = keccak.new(digest_bits=256)
    digest.update(text.encode())
    return "0x" + digest.hexdigest()


WITHDRAWAL = sig("Withdrawal(address,bytes32,address,uint256)")
SEL_TOKEN = sig("token()")[:10]
SEL_DENOM = sig("denomination()")[:10]
SEL_SYMBOL = sig("symbol()")[:10]


def build(low, high):
    # No address filter. That is the point.
    return "eth_getLogs", [{"fromBlock": hex(low), "toBlock": hex(high),
                            "topics": [WITHDRAWAL]}]


def rows(logs):
    out = []
    for entry in logs or []:
        if entry.get("removed"):
            continue
        data = (entry.get("data") or "0x")[2:]
        if len(data) < 192:
            continue
        topics = entry.get("topics") or []
        relayer = ("0x" + topics[1][-40:]).lower() if len(topics) > 1 else None
        out.append((
            (entry.get("transactionHash") or "").lower(),
            c.hex_block(entry.get("logIndex")),
            c.hex_block(entry.get("blockNumber")),
            (entry.get("address") or "").lower(),
            ("0x" + data[24:64]).lower(),
            relayer,
            str(int(data[128:192], 16)),
        ))
    return out


def decode_string(raw):
    """ABI encoded string, or a bytes32 for older tokens."""
    if not raw or raw == "0x":
        return None
    body = raw[2:]
    try:
        if len(body) >= 128:
            length = int(body[64:128], 16)
            if 0 < length <= 64:
                text = bytes.fromhex(body[128:128 + length * 2])
                return text.decode("utf-8", "ignore").strip()
        chunk = bytes.fromhex(body[:64])
        text = chunk.rstrip(b"\x00").decode("utf-8", "ignore").strip()
        return text or None
    except Exception:
        return None


def label_pools():
    """Ask each contract what it holds and in what size."""
    con = c.open_db(OUT_DB, SCHEMA)
    pools = [r[0] for r in con.execute(
        "SELECT pool, COUNT(*) FROM withdrawals GROUP BY pool "
        "HAVING COUNT(*) >= ?", (MIN_EVENTS,))]
    done = {r[0] for r in con.execute("SELECT pool FROM pool_info")}
    pending = [p for p in pools if p not in done]
    if not pending:
        con.close()
        return

    node = c.Node()
    print("  labelling {:,} contracts".format(len(pending)))
    for pool in pending:
        token = denom = symbol = None
        try:
            raw = node.call("eth_call", [{"to": pool, "data": SEL_TOKEN},
                                         "latest"], timeout=60)
            if raw and len(raw) >= 66:
                token = ("0x" + raw[-40:]).lower()
        except Exception:
            pass
        try:
            raw = node.call("eth_call", [{"to": pool, "data": SEL_DENOM},
                                         "latest"], timeout=60)
            if raw and len(raw) > 2:
                denom = str(int(raw, 16))
        except Exception:
            pass
        if token and int(token, 16):
            try:
                raw = node.call("eth_call", [{"to": token, "data": SEL_SYMBOL},
                                             "latest"], timeout=60)
                symbol = decode_string(raw)
            except Exception:
                pass
        else:
            token, symbol = None, "ETH"
        con.execute("INSERT OR REPLACE INTO pool_info VALUES (?,?,?,?)",
                    (pool, token, denom, symbol))
        con.commit()
    con.close()


def show_pools():
    label_pools()
    con = sqlite3.connect(OUT_DB)
    info = {r[0]: r[1:] for r in con.execute(
        "SELECT pool, token, denomination, symbol FROM pool_info")}
    print("=" * 78)
    print("CONTRACTS THAT EMITTED THE WITHDRAWAL EVENT")
    print("=" * 78)
    print("  Anything with very few events is probably not Tornado. Check")
    print("  the odd ones on Etherscan before trusting them.\n")
    total = 0
    for pool, count, recips, low, high in con.execute(
            "SELECT pool, COUNT(*), COUNT(DISTINCT recipient), "
            "MIN(block), MAX(block) FROM withdrawals GROUP BY pool "
            "ORDER BY 2 DESC"):
        token, denom, symbol = info.get(pool, (None, None, None))
        label = KNOWN.get(pool)
        if not label:
            if symbol and denom:
                try:
                    label = "{} {}".format(int(denom) / 1e18
                                           if symbol in ("ETH", "WETH", "DAI")
                                           else denom, symbol)
                except Exception:
                    label = symbol
            else:
                label = symbol or "unlabelled"
        mark = "" if count >= MIN_EVENTS else "   <- too few, check this"
        print("  {}  {}".format(pool, label))
        print("    {:,} withdrawals, {:,} recipients, blocks {:,} to {:,}{}"
              .format(count, recips, low, high, mark))
        total += count
    print("\n  {:,} withdrawal events in total".format(total))
    con.close()


def summary():
    con = sqlite3.connect(OUT_DB)
    total = con.execute("SELECT COUNT(*) FROM withdrawals").fetchone()[0]
    print("=" * 70)
    print("TORNADO WITHDRAWALS, ALL DENOMINATIONS")
    print("=" * 70)
    print("  withdrawal events    {:>12,}".format(total))
    if not total:
        con.close()
        return
    print("  pool contracts       {:>12,}".format(con.execute(
        "SELECT COUNT(DISTINCT pool) FROM withdrawals").fetchone()[0]))
    print("  distinct recipients  {:>12,}".format(con.execute(
        "SELECT COUNT(DISTINCT recipient) FROM withdrawals").fetchone()[0]))
    print("  distinct relayers    {:>12,}".format(con.execute(
        "SELECT COUNT(DISTINCT relayer) FROM withdrawals "
        "WHERE relayer IS NOT NULL AND relayer != "
        "'0x0000000000000000000000000000000000000000'").fetchone()[0]))
    direct = con.execute(
        "SELECT COUNT(*) FROM withdrawals WHERE relayer IS NULL OR relayer = "
        "'0x0000000000000000000000000000000000000000'").fetchone()[0]
    print("  without a relayer    {:>12,}   {:.1f}%".format(
        direct, direct / total * 100))
    low, high = con.execute(
        "SELECT MIN(block), MAX(block) FROM withdrawals").fetchone()
    print("  blocks               {:,} to {:,}".format(low, high))
    both = con.execute(
        "SELECT COUNT(*) FROM (SELECT recipient FROM withdrawals INTERSECT "
        "SELECT relayer FROM withdrawals)").fetchone()[0]
    print("\n  addresses that were both recipient and relayer  {:,}".format(
        both))
    print("  The trace based method could not separate these. Here the")
    print("  event states which role each address played each time.")
    blocks, failed, _ = c.coverage(OUT_DB)
    print("\n  blocks swept         {:>12,}".format(blocks))
    print("  failed ranges        {:>12,}".format(failed))
    if failed:
        print("\n  Coverage incomplete. Rerun before quoting counts.")
    con.close()


def export():
    """Write the recipient set in the schema analyse_depths.py already reads."""
    con = sqlite3.connect(EXPORT_DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=OFF")
    for statement in (
            "DROP TABLE IF EXISTS paid",
            "CREATE TABLE paid (payer TEXT, target TEXT, block INTEGER)",
            "CREATE TABLE IF NOT EXISTS done_units "
            "(start_block INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS failed_ranges "
            "(low INTEGER, high INTEGER, reason TEXT)",
            "CREATE TABLE IF NOT EXISTS hot_payers "
            "(address TEXT PRIMARY KEY, seen INTEGER)"):
        con.execute(statement)

    con.execute("ATTACH DATABASE ? AS src", (OUT_DB,))
    con.execute("INSERT INTO paid SELECT pool, recipient, block "
                "FROM src.withdrawals")
    con.execute("INSERT OR IGNORE INTO done_units "
                "SELECT DISTINCT start_block FROM src.done_units")
    con.execute("INSERT INTO failed_ranges "
                "SELECT low, high, reason FROM src.failed_ranges")
    con.commit()
    con.execute("DETACH DATABASE src")
    con.commit()

    rows_out = con.execute("SELECT COUNT(*) FROM paid").fetchone()[0]
    targets = con.execute(
        "SELECT COUNT(DISTINCT target) FROM paid").fetchone()[0]
    con.execute("CREATE INDEX IF NOT EXISTS i_p_target ON paid(target)")
    con.commit()
    con.close()

    print("=" * 70)
    print("EXPORTED")
    print("=" * 70)
    print("  rows                 {:>12,}".format(rows_out))
    print("  distinct recipients  {:>12,}".format(targets))
    print("\n  wrote {}".format(EXPORT_DB))
    print("\n  Relayers are excluded already, because the event names them")
    print("  separately. Only recipients are in here.")
    print("\n  In analyse_depths.py set")
    print('    OVERLAP_DB     = "{}"'.format(EXPORT_DB))
    print("    RELAYER_CUTOFF = 10_000_000")
    print("  then rerun. A frequency cutoff would now only remove genuine")
    print("  repeat users, so switch it off rather than leaving it at 100.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pools", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--from-block", type=int, default=START_BLOCK)
    parser.add_argument("--to-block", type=int, default=None)
    parser.add_argument("--workers", type=int, default=c.WORKERS)
    args = parser.parse_args()

    if args.pools:
        show_pools()
        return
    if args.summary:
        summary()
        return
    if args.export:
        export()
        return

    print("=" * 70)
    print("ALL TORNADO WITHDRAWALS")
    print("=" * 70)
    print("  event       Withdrawal(address,bytes32,address,uint256)")
    print("  topic0      {}".format(WITHDRAWAL))
    print("  address     no filter, so every pool is found")
    print("  payload     one topic hash, a few hundred bytes per call\n")

    node = c.Node()
    head = int(node.call("eth_blockNumber", []), 16)
    end = args.to_block or head

    c.probe_gzip(node, build(1_000_000, 1_000_009))
    c.discover_cap(node, "eth_getLogs",
                   lambda a, b: [{"fromBlock": hex(a), "toBlock": hex(b),
                                  "topics": [WITHDRAWAL]}])

    sweeper = c.RangeSweeper(
        OUT_DB, SCHEMA,
        "INSERT OR IGNORE INTO withdrawals VALUES (?,?,?,?,?,?,?)",
        build, rows, workers=args.workers, label="withdrawals")
    sweeper.run(args.from_block, end)
    summary()
    print("\n  Run --pools next to see what was found.")


if __name__ == "__main__":
    main()
