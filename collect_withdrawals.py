#!/usr/bin/env python3
"""
Collect Tornado Cash withdrawal recipients from Ethereum logs.

This is the main entrypoint for the current codebase.

What it does:
- sweeps the Withdrawal event across blocks
- stores one row per withdrawal in SQLite
- can summarize discovered pools and recipients
- can export a simple `paid` table for downstream tracing
"""

import argparse
import os
import sqlite3

from eth_utils import keccak

import sweep_rpc as sweep

DEFAULT_OUTPUT_DB = "tornado_withdrawals.db"
DEFAULT_EXPORT_DB = "tornado_recipient_edges.db"
START_BLOCK = 9_116_000
MIN_EVENTS = 20

KNOWN_POOLS = {
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
    "CREATE INDEX IF NOT EXISTS i_w_recipient ON withdrawals(recipient)",
    """CREATE TABLE IF NOT EXISTS pool_info (
           pool TEXT PRIMARY KEY, token TEXT, denomination TEXT,
           symbol TEXT)""",
]


def signature(text):
    return "0x" + keccak(text=text).hex()


WITHDRAWAL_TOPIC = signature("Withdrawal(address,bytes32,address,uint256)")
TOKEN_SELECTOR = signature("token()")[:10]
DENOMINATION_SELECTOR = signature("denomination()")[:10]
SYMBOL_SELECTOR = signature("symbol()")[:10]


def build_log_request(low, high):
    # We intentionally avoid an address filter here. The point of this sweep is
    # to discover every contract that emits the Withdrawal event, then inspect
    # the resulting emitter set afterward.
    return "eth_getLogs", [
        {"fromBlock": hex(low), "toBlock": hex(high), "topics": [WITHDRAWAL_TOPIC]}
    ]


def parse_withdrawal_rows(logs):
    rows = []
    for entry in logs or []:
        if entry.get("removed"):
            continue
        # The event has one indexed field (relayer) and the other fields in the
        # data payload, so we decode recipient and fee from the ABI-encoded
        # data instead of looking for normal ETH transfers.
        data = (entry.get("data") or "0x")[2:]
        if len(data) < 192:
            continue
        topics = entry.get("topics") or []
        relayer = ("0x" + topics[1][-40:]).lower() if len(topics) > 1 else None
        rows.append(
            (
                (entry.get("transactionHash") or "").lower(),
                sweep.hex_block(entry.get("logIndex")),
                sweep.hex_block(entry.get("blockNumber")),
                (entry.get("address") or "").lower(),
                ("0x" + data[24:64]).lower(),
                relayer,
                str(int(data[128:192], 16)),
            )
        )
    return rows


def decode_symbol(raw):
    if not raw or raw == "0x":
        return None
    body = raw[2:]
    try:
        if len(body) >= 128:
            length = int(body[64:128], 16)
            if 0 < length <= 64:
                return bytes.fromhex(body[128 : 128 + length * 2]).decode(
                    "utf-8", "ignore"
                ).strip()
        return bytes.fromhex(body[:64]).rstrip(b"\x00").decode("utf-8", "ignore").strip() or None
    except Exception:
        return None


def label_pool_contracts(db_path):
    # This step is optional metadata enrichment. The raw withdrawal collection
    # works without it, but these calls make the emitter list much easier to
    # inspect by asking each contract what token and denomination it represents.
    con = sweep.open_db(db_path, SCHEMA)
    pools = [
        row[0]
        for row in con.execute(
            "SELECT pool, COUNT(*) FROM withdrawals GROUP BY pool HAVING COUNT(*) >= ?",
            (MIN_EVENTS,),
        )
    ]
    labeled = {row[0] for row in con.execute("SELECT pool FROM pool_info")}
    pending = [pool for pool in pools if pool not in labeled]
    if not pending:
        con.close()
        return

    node = sweep.Node()
    print("  labelling {:,} contracts".format(len(pending)))
    for pool in pending:
        token = denomination = symbol = None
        try:
            raw = node.call("eth_call", [{"to": pool, "data": TOKEN_SELECTOR}, "latest"], timeout=60)
            if raw and len(raw) >= 66:
                token = ("0x" + raw[-40:]).lower()
        except Exception:
            pass
        try:
            raw = node.call(
                "eth_call", [{"to": pool, "data": DENOMINATION_SELECTOR}, "latest"], timeout=60
            )
            if raw and len(raw) > 2:
                denomination = str(int(raw, 16))
        except Exception:
            pass
        if token and int(token, 16):
            try:
                raw = node.call("eth_call", [{"to": token, "data": SYMBOL_SELECTOR}, "latest"], timeout=60)
                symbol = decode_symbol(raw)
            except Exception:
                pass
        else:
            token, symbol = None, "ETH"
        con.execute(
            "INSERT OR REPLACE INTO pool_info VALUES (?,?,?,?)",
            (pool, token, denomination, symbol),
        )
        con.commit()
    con.close()


def show_pools(db_path):
    label_pool_contracts(db_path)
    con = sqlite3.connect(db_path)
    info = {
        row[0]: row[1:]
        for row in con.execute("SELECT pool, token, denomination, symbol FROM pool_info")
    }
    print("=" * 78)
    print("CONTRACTS THAT EMITTED THE WITHDRAWAL EVENT")
    print("=" * 78)
    print("  Low-count emitters may be non-Tornado contracts. Inspect them before trusting them.\n")
    total = 0
    for pool, count, recipients, low, high in con.execute(
        "SELECT pool, COUNT(*), COUNT(DISTINCT recipient), MIN(block), MAX(block) "
        "FROM withdrawals GROUP BY pool ORDER BY 2 DESC"
    ):
        token, denomination, symbol = info.get(pool, (None, None, None))
        label = KNOWN_POOLS.get(pool)
        if not label:
            if symbol and denomination:
                try:
                    label = "{} {}".format(
                        int(denomination) / 1e18 if symbol in ("ETH", "WETH", "DAI") else denomination,
                        symbol,
                    )
                except Exception:
                    label = symbol
            else:
                label = symbol or "unlabelled"
        marker = "" if count >= MIN_EVENTS else "   <- low count, inspect"
        print("  {}  {}".format(pool, label))
        print(
            "    {:,} withdrawals, {:,} recipients, blocks {:,} to {:,}{}".format(
                count, recipients, low, high, marker
            )
        )
        total += count
    print("\n  {:,} withdrawal events in total".format(total))
    con.close()


def show_summary(db_path):
    con = sqlite3.connect(db_path)
    total = con.execute("SELECT COUNT(*) FROM withdrawals").fetchone()[0]
    print("=" * 70)
    print("TORNADO WITHDRAWALS")
    print("=" * 70)
    print("  withdrawal events    {:>12,}".format(total))
    if not total:
        con.close()
        return
    print(
        "  pool contracts       {:>12,}".format(
            con.execute("SELECT COUNT(DISTINCT pool) FROM withdrawals").fetchone()[0]
        )
    )
    print(
        "  distinct recipients  {:>12,}".format(
            con.execute("SELECT COUNT(DISTINCT recipient) FROM withdrawals").fetchone()[0]
        )
    )
    print(
        "  distinct relayers    {:>12,}".format(
            con.execute(
                "SELECT COUNT(DISTINCT relayer) FROM withdrawals "
                "WHERE relayer IS NOT NULL AND relayer != "
                "'0x0000000000000000000000000000000000000000'"
            ).fetchone()[0]
        )
    )
    low, high = con.execute("SELECT MIN(block), MAX(block) FROM withdrawals").fetchone()
    print("  blocks               {:,} to {:,}".format(low, high))
    blocks, failed, _ = sweep.coverage(db_path)
    print("\n  blocks swept         {:>12,}".format(blocks))
    print("  failed ranges        {:>12,}".format(failed))
    if failed:
        print("\n  Coverage incomplete. Rerun before quoting counts.")
    con.close()


def export_recipient_edges(source_db_path, export_db_path):
    # Downstream tracing only needs a simple payer->recipient edge table. This
    # export keeps the collector DB intact while producing a smaller DB for
    # follow-up analyses.
    con = sqlite3.connect(export_db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=OFF")
    for statement in (
        "DROP TABLE IF EXISTS paid",
        "CREATE TABLE paid (payer TEXT, target TEXT, block INTEGER)",
        "CREATE TABLE IF NOT EXISTS done_units (start_block INTEGER PRIMARY KEY)",
        "CREATE TABLE IF NOT EXISTS failed_ranges (low INTEGER, high INTEGER, reason TEXT)",
    ):
        con.execute(statement)

    con.execute("ATTACH DATABASE ? AS src", (source_db_path,))
    con.execute("INSERT INTO paid SELECT pool, recipient, block FROM src.withdrawals")
    con.execute("INSERT OR IGNORE INTO done_units SELECT DISTINCT start_block FROM src.done_units")
    con.execute("INSERT INTO failed_ranges SELECT low, high, reason FROM src.failed_ranges")
    con.commit()
    con.execute("DETACH DATABASE src")
    con.commit()

    rows_out = con.execute("SELECT COUNT(*) FROM paid").fetchone()[0]
    recipients = con.execute("SELECT COUNT(DISTINCT target) FROM paid").fetchone()[0]
    con.execute("CREATE INDEX IF NOT EXISTS i_p_target ON paid(target)")
    con.commit()
    con.close()

    print("=" * 70)
    print("EXPORTED")
    print("=" * 70)
    print("  rows                 {:>12,}".format(rows_out))
    print("  distinct recipients  {:>12,}".format(recipients))
    print("\n  wrote {}".format(export_db_path))


def run_collection(args):
    if args.rpc_url:
        sweep.set_node_url(args.rpc_url)

    print("=" * 70)
    print("COLLECT TORNADO WITHDRAWALS")
    print("=" * 70)
    print("  event       Withdrawal(address,bytes32,address,uint256)")
    print("  topic0      {}".format(WITHDRAWAL_TOPIC))
    print("  address     no filter, so every emitting contract is found")
    if args.rpc_url:
        print("  rpc url     {}".format(args.rpc_url))
    print()

    node = sweep.Node()
    head = int(node.call("eth_blockNumber", []), 16)
    end_block = args.to_block or head

    # Probe once up front so the shared sweep code can choose the widest safe
    # block window and whether compressed request bodies help with this node.
    sweep.probe_gzip(node, build_log_request(1_000_000, 1_000_009))
    sweep.discover_cap(node, "eth_getLogs", lambda low, high: build_log_request(low, high)[1])

    sweeper = sweep.RangeSweeper(
        args.db_path,
        SCHEMA,
        "INSERT OR IGNORE INTO withdrawals VALUES (?,?,?,?,?,?,?)",
        build_log_request,
        parse_withdrawal_rows,
        workers=args.workers,
        label="withdrawals",
    )
    sweeper.run(args.from_block, end_block)
    show_summary(args.db_path)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Collect Tornado Cash withdrawal recipients from Ethereum logs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--pools", action="store_true", help="show emitting contracts and labels")
    parser.add_argument("--summary", action="store_true", help="show DB summary without sweeping")
    parser.add_argument("--export", action="store_true", help="export a simple paid table for downstream tracing")
    parser.add_argument("--from-block", type=int, default=START_BLOCK, help="first block to scan")
    parser.add_argument("--to-block", type=int, default=None, help="last block to scan")
    parser.add_argument("--workers", type=int, default=sweep.WORKERS, help="parallel worker count")
    parser.add_argument("--db-path", default=DEFAULT_OUTPUT_DB, help="SQLite file for collected withdrawals")
    parser.add_argument("--export-db", default=DEFAULT_EXPORT_DB, help="SQLite file for exported recipient edges")
    parser.add_argument(
        "--rpc-url",
        default=os.environ.get("TC_RPC_URL"),
        help="Ethereum JSON-RPC URL. Defaults to the TC_RPC_URL environment variable.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    if args.pools:
        show_pools(args.db_path)
        return
    if args.summary:
        show_summary(args.db_path)
        return
    if args.export:
        export_recipient_edges(args.db_path, args.export_db)
        return
    run_collection(args)


if __name__ == "__main__":
    main()
