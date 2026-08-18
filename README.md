# Tornado Cash Withdrawal Recipients

This repo is a minimal working environment for one job: collect every visible
recipient of a Tornado Cash withdrawal on Ethereum by sweeping the
`Withdrawal(address,bytes32,address,uint256)` event.

It also includes a second-stage tracer for following what those recipient
addresses do afterward, while avoiding graph blowups through shared smart
contracts.

## Module guide

The repo now has a small, single-purpose runtime path:

- `collect_withdrawals.py`
  Main entrypoint. Sweeps the Tornado `Withdrawal` event, stores results in
  SQLite, prints summaries, and can export a simple recipient-edge table.

- `sweep_rpc.py`
  Shared infrastructure for resumable RPC sweeps. Handles the node client,
  adaptive block windows, gzip probing, progress tracking, and SQLite-safe
  writes.

- `trace_outflows.py`
  Second-stage tracer. Starts from Tornado withdrawal recipients, collects
  outbound actions, expands only through EOAs, and marks smart-contract
  interactions instead of expanding through them. It supports separate
  collection, classification, and path-building phases.

- `protocol_labels.py`
  Protocol classification rules. Holds known contract addresses and selector
  mappings for Railgun, wrappers, token contracts, and common DEX patterns.

## Why this method

Tracing ETH value transfers misses ERC-20 withdrawals. Reading the pool's
`Withdrawal` event captures all denominations and also separates the
recipient from the relayer directly from the event payload.

For the second stage, the tracer follows outbound actions from withdrawal
recipients but only expands through EOAs. Smart-contract interactions are
recorded and classified, but they do not cause the graph to fan out through
every downstream contract recipient.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export TC_RPC_URL="https://your-rpc-endpoint"
```

You can also pass `--rpc-url` directly to the script.

## Run

There are two stages:

1. collect Tornado withdrawal recipients
2. trace what those recipients do afterward

### Stage 1: collect withdrawal recipients

Collect withdrawals with the canonical entrypoint:

```bash
python3 collect_withdrawals.py
```

Show a summary:

```bash
python3 collect_withdrawals.py --summary
```

Inspect discovered emitting contracts:

```bash
python3 collect_withdrawals.py --pools
```

Export a simple `paid(payer, target, block)` table for downstream tracing:

```bash
python3 collect_withdrawals.py --export
```

Sweep a custom range:

```bash
python3 collect_withdrawals.py --from-block 9116000 --to-block 18000000
```

### Stage 2: trace post-withdrawal outflows

Trace post-withdrawal outflows one hop deep:

```bash
python3 trace_outflows.py --max-hops 1
```

Trace two hops deep:

```bash
python3 trace_outflows.py --max-hops 2 --processes 4
```

Only collect raw actions:

```bash
python3 trace_outflows.py --max-hops 2 --collect-only --processes 4
```

Only classify cached actions and addresses:

```bash
python3 trace_outflows.py --classify-only
```

Rebuild paths locally from cached actions:

```bash
python3 trace_outflows.py --max-hops 2 --build-only
```

## What the tracer is doing

`trace_outflows.py` is intentionally split into phases:

1. **Collect raw actions**
   It uses `trace_filter` to collect outbound actions from the current frontier
   of tracked EOAs and stores those rows in `tornado_outflows.db`.

2. **Classify recipients**
   It resolves whether recipients are EOAs or contracts, then applies protocol
   labels from `protocol_labels.py` such as `railgun`, `dex`, `wrapper`, or
   `token_contract`.

3. **Build seed-relative paths**
   It rebuilds path membership locally from the cached action table. This is
   what makes changing `--max-hops` relatively cheap once actions are already
   collected.

The key design rule is:

- EOAs expand the frontier
- smart contracts are marked and stored, but not expanded through by default

That keeps the tracing focused on user migration paths instead of exploding
into every shared protocol graph.

## End-to-end example

The most common workflow is:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export TC_RPC_URL="https://your-rpc-endpoint"

# 1. Collect all withdrawal recipients.
python3 collect_withdrawals.py

# 2. Inspect what contracts emitted the event.
python3 collect_withdrawals.py --pools

# 3. Trace recipient outflows two hops deep.
python3 trace_outflows.py --max-hops 2 --processes 4

# 4. If you later want to rebuild paths without recollecting actions:
python3 trace_outflows.py --max-hops 2 --build-only

# 5. Export the traced graph to JSON if needed.
python3 trace_outflows.py --export-json
```

If you want the phased workflow explicitly:

```bash
python3 trace_outflows.py --max-hops 2 --collect-only --processes 4
python3 trace_outflows.py --classify-only --processes 4
python3 trace_outflows.py --max-hops 2 --build-only
```

`--processes` controls how many worker processes are used for the RPC-heavy
phases of raw trace collection and bulk contract classification. A small number
such as `2`, `4`, or `6` is usually the right place to start; going too high
can overwhelm the RPC endpoint and make things slower rather than faster.

## Output

The main output is `tornado_withdrawals.db`, containing one row per withdrawal
event with the pool, recipient, relayer, fee, and block number. The export
step writes `tornado_recipient_edges.db`.

The second-stage tracer writes `tornado_outflows.db`, which stores:

- unique nodes
- globally collected outbound actions
- seed-relative paths
- seed-relative edges

At a high level:

- `nodes` tells you what addresses were seen
- `actions` stores raw outbound behavior collected from the node
- `seed_paths` stores when an address entered a seed-derived path
- `seed_edges` stores the seed-relative graph after timing and hop rules are applied

## Docs

- `PATHWAYS.md`: conceptual explanation of the Tornado -> Railgun pathways
- `RESULTS.md`: latest writeup and measurement summary

## Notes

- The sweep is resumable.
- The collector does not depend on a hardcoded list of pool addresses.
- A signature-only sweep can pick up unrelated contracts with the same event
  shape, so inspect `--pools` before treating every emitter as Tornado.
