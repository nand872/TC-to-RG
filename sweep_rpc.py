#!/usr/bin/env python3
"""
Shared JSON-RPC sweep utilities.

This module is the infrastructure layer for the project. It is responsible for:

- talking to the Ethereum JSON-RPC endpoint
- probing whether gzip is accepted
- discovering the block-range limit the node will tolerate
- sweeping block ranges in parallel
- writing sweep results to SQLite safely and resumably

Other modules should import from here rather than reimplementing sweep logic.
"""

import gzip
import io
import json
import os
import queue
import re
import sqlite3
import threading
import time

import requests

NODE = os.environ.get("TC_RPC_URL", "http://88.218.224.19:8546")

WORKERS = 6
TIMEOUT = 900
UNIT = 1_000
WINDOW_START = 100_000
WINDOW_MIN = 1_000
WINDOW_MAX = 1_000_000
GROW_AFTER = 3
PIECE = 200_000
COMMIT_ROWS = 50_000
QUEUE_DEPTH = 200

LIMIT_PATTERN = re.compile(r"(?:limit|filter)[^0-9]{0,30}(\d{2,})")
OVERFLOW_HINTS = (
    "too many",
    "limit",
    "exceed",
    "too large",
    "out of memory",
    "deadline",
    "timeout",
    "canceled",
    "cancelled",
    "response size",
)

_server_limit = None
_limit_lock = threading.Lock()
_use_gzip = False


class Busy(Exception):
    pass


class Overflow(Exception):
    pass


def classify(error):
    text = str(error).lower()
    if any(hint in text for hint in OVERFLOW_HINTS):
        return Overflow(str(error)[:140])
    return Busy(str(error)[:140])


def parse_limit(text):
    match = LIMIT_PATTERN.search(str(text))
    if not match:
        return None
    value = int(match.group(1))
    return value if 100 <= value <= 10_000_000 else None


def note_limit(value):
    global _server_limit
    if not value:
        return
    with _limit_lock:
        if _server_limit is None or value < _server_limit:
            _server_limit = value


def cap():
    return _server_limit or WINDOW_MAX


def set_node_url(url):
    global NODE
    NODE = url


class Node:
    def __init__(self, url=None):
        self.url = url or NODE
        self.session = None
        self._reset()

    def _reset(self):
        if self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _send(self, payload, timeout):
        if _use_gzip:
            buffer = io.BytesIO()
            with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=1) as f:
                f.write(json.dumps(payload).encode())
            return self.session.post(
                self.url,
                data=buffer.getvalue(),
                timeout=timeout,
                headers={
                    "Content-Encoding": "gzip",
                    "Content-Type": "application/json",
                },
            )
        return self.session.post(self.url, json=payload, timeout=timeout)

    def _post(self, payload, timeout=None, stop=None):
        wait, total = 1, 0
        while stop is None or not stop.is_set():
            try:
                return self._send(payload, timeout or TIMEOUT).json()
            except requests.exceptions.ReadTimeout:
                raise Overflow("read timeout after {}s".format(timeout or TIMEOUT))
            except Exception:
                # Most RPC failures here are transient node/gateway problems, so
                # we back off and retry with a fresh session before giving up.
                total += wait
                if total > 3600:
                    raise RuntimeError("node unreachable for an hour")
                time.sleep(wait)
                wait = min(wait * 2, 60)
                self._reset()
        raise RuntimeError("stopped")

    def call(self, method, params, timeout=None, stop=None):
        answer = self._post(
            {"jsonrpc": "2.0", "id": 0, "method": method, "params": params},
            timeout,
            stop,
        )
        if "error" in answer:
            raise classify(answer["error"])
        return answer["result"]

    def batch(self, calls, timeout=None, stop=None):
        if not calls:
            return []
        payload = [
            {"jsonrpc": "2.0", "id": index, "method": method, "params": params}
            for index, (method, params) in enumerate(calls)
        ]
        answers = self._post(payload, timeout, stop)
        if isinstance(answers, dict):
            raise classify(answers.get("error", answers))
        out = [None] * len(calls)
        for answer in answers:
            if "error" in answer:
                raise classify(answer["error"])
            out[answer.get("id", 0)] = answer.get("result")
        return out


def probe_gzip(node, probe_params):
    # Address-heavy RPC requests compress extremely well. Probe once and let
    # the rest of the session benefit automatically.
    global _use_gzip
    _use_gzip = True
    try:
        node.call(probe_params[0], probe_params[1], timeout=60)
        return True
    except Exception:
        _use_gzip = False
        return False


def discover_cap(node, method, build):
    # Different gateways tolerate different block ranges. We probe the widest
    # safe range once so later sweeps can avoid lots of failed calls.
    width = WINDOW_MAX
    while width > WINDOW_MIN:
        try:
            node.call(
                method,
                build(1_000_000, 1_000_000 + width - 1),
                timeout=180,
            )
            note_limit(width)
            return width
        except Overflow as problem:
            stated = parse_limit(problem)
            if stated:
                note_limit(stated)
                return stated
            width //= 2
        except (Busy, RuntimeError):
            break
    note_limit(WINDOW_MIN)
    return WINDOW_MIN


def hex_block(value):
    if isinstance(value, str):
        return int(value, 16)
    return value or 0


def format_duration(seconds):
    if seconds < 60:
        return "{:.0f}s".format(seconds)
    if seconds < 3600:
        return "{:.0f}m".format(seconds / 60)
    return "{:.1f}h".format(seconds / 3600)


def open_db(path, schema):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA cache_size=-262144")
    con.execute("PRAGMA temp_store=MEMORY")
    for statement in schema:
        con.execute(statement)
    con.execute("CREATE TABLE IF NOT EXISTS done_units (start_block INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE IF NOT EXISTS failed_ranges (low INTEGER, high INTEGER, reason TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS hot_keys (address TEXT PRIMARY KEY, seen INTEGER)")
    con.commit()
    return con


class RangeSweeper:
    """
    Resumable parallel sweep of a block range.

    `build(low, high)` returns the RPC method and params for a window.
    `rows(result)` converts one RPC result into DB rows matching `insert_sql`.
    """

    def __init__(
        self,
        db_path,
        schema,
        insert_sql,
        build,
        rows,
        hub_index=None,
        hub_limit=0,
        workers=WORKERS,
        label="rows",
    ):
        self.db_path = db_path
        self.schema = schema
        self.insert_sql = insert_sql
        self.build = build
        self.rows = rows
        self.hub_index = hub_index
        self.hub_limit = hub_limit
        self.workers = workers
        self.label = label

        self.work = queue.Queue()
        self.results = queue.Queue(maxsize=QUEUE_DEPTH)
        self.stop = threading.Event()
        self.warned = threading.Event()
        self.counters = {"rows": 0, "blocks": 0, "failed": 0}
        self.lock = threading.Lock()
        self.hot = set()
        self.hot_counts = {}
        self.hot_lock = threading.Lock()

    def _guard(self, rows):
        if self.hub_index is None or not self.hub_limit:
            return rows
        tally = {}
        for row in rows:
            key = row[self.hub_index]
            tally[key] = tally.get(key, 0) + 1
        newly = []
        with self.hot_lock:
            for key, count in tally.items():
                total = self.hot_counts.get(key, 0) + count
                self.hot_counts[key] = total
                if total > self.hub_limit and key not in self.hot:
                    self.hot.add(key)
                    newly.append((key, total))
        for entry in newly:
            self.results.put(("hot", entry))
        if not self.hot:
            return rows
        return [row for row in rows if row[self.hub_index] not in self.hot]

    def _writer(self):
        con = open_db(self.db_path, self.schema)
        pending = 0
        while True:
            try:
                item = self.results.get(timeout=2)
            except queue.Empty:
                if self.stop.is_set() and self.results.empty():
                    break
                continue
            if item is None:
                break
            kind, payload = item
            try:
                if kind == "span":
                    low, high, rows = payload
                    units = [(u,) for u in range(low, high + 1, UNIT)]
                    try:
                        # We only mark a block unit complete in the same DB
                        # transaction as the row insert, so partial writes never
                        # silently corrupt sweep coverage.
                        if rows:
                            con.executemany(self.insert_sql, rows)
                        con.executemany(
                            "INSERT OR IGNORE INTO done_units VALUES (?)",
                            units,
                        )
                        pending += len(rows) + len(units)
                    except Exception as problem:
                        con.rollback()
                        pending = 0
                        con.execute(
                            "INSERT INTO failed_ranges VALUES (?,?,?)",
                            (low, high, "write failed: " + str(problem)[:80]),
                        )
                        con.commit()
                        with self.lock:
                            self.counters["failed"] += 1
                        print(
                            "\n  write failed {:,} to {:,}: {}".format(
                                low, high, str(problem)[:70]
                            )
                        )
                elif kind == "failed":
                    con.execute("INSERT INTO failed_ranges VALUES (?,?,?)", payload)
                    con.commit()
                    pending = 0
                elif kind == "hot":
                    con.execute("INSERT OR REPLACE INTO hot_keys VALUES (?,?)", payload)
                    con.commit()
                    pending = 0
                if pending >= COMMIT_ROWS:
                    con.commit()
                    pending = 0
            except Exception as problem:
                print("\n  writer problem: {}".format(str(problem)[:90]))
            self.results.task_done()
        con.commit()
        con.close()

    def _worker(self, done):
        node = Node()
        window = min(WINDOW_START, cap())
        clean = 0
        while not self.stop.is_set():
            try:
                low, high = self.work.get(timeout=3)
            except queue.Empty:
                return
            current = low
            while current <= high and not self.stop.is_set():
                stop_at = min(current + window - 1, high)
                if all(unit in done for unit in range(current, stop_at + 1, UNIT)):
                    with self.lock:
                        self.counters["blocks"] += stop_at - current + 1
                    current = stop_at + 1
                    continue

                method, params = self.build(current, stop_at)
                try:
                    result = node.call(method, params, stop=self.stop)
                except Overflow as problem:
                    stated = parse_limit(problem)
                    note_limit(stated)
                    if window > WINDOW_MIN:
                        # If the node refuses a window, shrink quickly and keep
                        # going instead of failing the entire sweep.
                        if not self.warned.is_set():
                            self.warned.set()
                            print("\n  node refused {:,} blocks: {}".format(window, problem))
                            print(
                                "  cap {:,}, using it\n".format(stated)
                                if stated
                                else "  narrowing\n"
                            )
                        window = (
                            max(WINDOW_MIN, min(stated, window))
                            if stated
                            else max(WINDOW_MIN, window // 2)
                        )
                        clean = 0
                        continue
                    self.results.put(("failed", (current, stop_at, str(problem))))
                    with self.lock:
                        self.counters["failed"] += 1
                    current = stop_at + 1
                    continue
                except Busy as problem:
                    self.results.put(("failed", (current, stop_at, str(problem))))
                    with self.lock:
                        self.counters["failed"] += 1
                    current = stop_at + 1
                    continue
                except RuntimeError:
                    return

                rows = self._guard(self.rows(result))
                self.results.put(("span", (current, stop_at, rows)))
                with self.lock:
                    self.counters["rows"] += len(rows)
                    self.counters["blocks"] += stop_at - current + 1

                current = stop_at + 1
                clean += 1
                if clean >= GROW_AFTER and window < cap():
                    window = min(cap(), window * 2)
                    clean = 0
            self.work.task_done()

    def run(self, start, end):
        con = open_db(self.db_path, self.schema)
        done = {row[0] for row in con.execute("SELECT start_block FROM done_units")}
        for row in con.execute("SELECT address FROM hot_keys"):
            self.hot.add(row[0])

        start = (start // UNIT) * UNIT
        pieces, cursor = 0, start
        while cursor <= end:
            stop_at = min(cursor + PIECE - 1, end)
            if not all(unit in done for unit in range(cursor, stop_at + 1, UNIT)):
                self.work.put((cursor, stop_at))
                pieces += 1
            cursor = stop_at + 1
        con.close()

        span = end - start + 1
        print("  blocks              {:,} to {:,}".format(start, end))
        print("  range cap           {:,} blocks".format(cap()))
        print("  calls for one pass  {:,.0f}".format(span / float(cap())))
        print("  pieces outstanding  {:,}".format(pieces))
        if pieces == 0:
            print("\n  Already complete.")
            return
        print("\n  Ctrl-C is safe. Progress saved continuously.\n")

        writer = threading.Thread(target=self._writer, daemon=True)
        writer.start()
        threads = []
        for _ in range(self.workers):
            thread = threading.Thread(target=self._worker, args=(done,), daemon=True)
            thread.start()
            threads.append(thread)

        started = time.time()
        try:
            while any(thread.is_alive() for thread in threads):
                time.sleep(5)
                with self.lock:
                    blocks = self.counters["blocks"]
                    rows = self.counters["rows"]
                    failed = self.counters["failed"]
                elapsed = time.time() - started
                rate = blocks / elapsed if elapsed else 0
                print(
                    "  {:,}/{:,} blocks  {:.2f}%  {} {:,}  failed {}  {:,.0f} blk/s  eta {}    ".format(
                        blocks,
                        span,
                        blocks / span * 100 if span else 100,
                        self.label,
                        rows,
                        failed,
                        rate,
                        format_duration((span - blocks) / rate if rate else 0),
                    ),
                    end="\r",
                )
        except KeyboardInterrupt:
            print("\n\n  stopping, please wait...")
            self.stop.set()
            for thread in threads:
                thread.join(timeout=30)

        self.stop.set()
        self.results.put(None)
        writer.join(timeout=120)
        print()


def coverage(db_path):
    con = sqlite3.connect(db_path)
    units = con.execute("SELECT COUNT(*) FROM done_units").fetchone()[0]
    failed = con.execute("SELECT COUNT(*) FROM failed_ranges").fetchone()[0]
    hot = con.execute("SELECT COUNT(*) FROM hot_keys").fetchone()[0]
    con.close()
    return units * UNIT, failed, hot
