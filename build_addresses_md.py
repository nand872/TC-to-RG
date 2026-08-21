#!/usr/bin/env python3
"""
BUILD ADDRESSES MD

Turns address_profiles.csv into ADDRESSES.md, one table row per address,
so the profiles are browsable on GitHub without downloading anything.

Two things it handles that a naive conversion does not.

The denominations column uses a pipe to separate values, and a pipe is
also the markdown column separator, so those rows would break the table.
They are rewritten as commas.

Addresses are wrapped in backticks, which stops GitHub reformatting long
hex strings and keeps them monospaced and easy to compare by eye.

Every row is checked for the right cell count before writing, and the
script refuses to produce a file that would render broken.

    python3 build_addresses_md.py
    python3 build_addresses_md.py --sort eth_withdrawn
    python3 build_addresses_md.py --per-address     one section each
"""

import argparse
import csv
import os

IN_CSV = "address_profiles.csv"
OUT_MD = "ADDRESSES.md"

# Column key, and the heading it gets in the table. Order is the display
# order. Anything not listed is dropped from the markdown but stays in
# the CSV.
COLUMNS = [
    ("n", "#"),
    ("address", "address"),
    ("kind", "kind"),
    ("ens", "ENS"),
    ("withdrawals", "wdls"),
    ("pools_used", "pools"),
    ("denominations", "denominations"),
    ("eth_withdrawn", "ETH"),
    ("relayed", "relayed"),
    ("direct", "direct"),
    ("relayers_used", "relayers"),
    ("first_withdrawal_date", "first wdl"),
    ("last_withdrawal_date", "last wdl"),
    ("shields", "shields"),
    ("first_shield_date", "first shield"),
    ("nonce", "nonce"),
    ("shield_only", "shield only"),
    ("was_prefunded", "prefunded"),
    ("balance_eth", "balance"),
    ("balance_before_eth", "bal before"),
    ("days_withdraw_to_shield", "days to shield"),
    ("order_correct", "order ok"),
    ("active_days", "active days"),
    ("post_designation", "post desig"),
    ("timing_cluster", "cluster"),
    ("h_direct", "h direct"),
    ("h_multipool", "h multipool"),
    ("h_repeat", "h repeat"),
    ("h_cluster", "h cluster"),
    ("h_any", "h any"),
]

HEADER = ("{count} addresses that both withdrew from a Tornado Cash contract "
          "named in the OFAC designation of 8 August 2022 and shielded into "
          "Railgun. Full data in [{csv}]({csv}).")

# Column key, and one plain sentence saying what it holds. Printed as a
# key above the table so the headings do not need guessing at.
MEANINGS = [
    ("address", "The wallet."),
    ("kind", "`account` if a person holds the key, `contract` if it is code."),
    ("ENS", "A registered name, if the wallet has one."),
    ("wdls", "How many times Tornado paid this wallet."),
    ("pools", "How many different pool sizes it used."),
    ("denominations", "Which sizes, for example `1 ETH, 10 ETH`."),
    ("ETH", "Total withdrawn, adding up the fixed pool sizes."),
    ("relayed", "Withdrawals where somebody else paid the gas."),
    ("direct", "Withdrawals where the wallet paid its own gas, which "
               "means it already held ETH."),
    ("relayers", "How many different relayers it used."),
    ("first wdl", "Date of its first Tornado withdrawal."),
    ("last wdl", "Date of its last one."),
    ("shields", "How many times it shielded into Railgun."),
    ("first shield", "Date of the first shield."),
    ("nonce", "Total transactions this wallet has ever sent."),
    ("shield only", "`1` if the shield is the only transaction it ever sent."),
    ("prefunded", "`1` if it already held ETH before its first withdrawal, "
                  "so it was not a fresh wallet."),
    ("balance", "What it holds now."),
    ("bal before", "What it held just before its first withdrawal."),
    ("days to shield", "Days from first withdrawal to first shield. "
                       "Negative means it shielded first."),
    ("order ok", "`1` if the withdrawal came before the shield."),
    ("active days", "Days between its first and last withdrawal."),
    ("post desig", "`1` if it shielded on or after 8 August 2022."),
    ("cluster", "`1` if two or more withdrawals landed within two hours, "
                "which is one session rather than separate decisions."),
    ("h direct", "Traceable because it paid its own gas."),
    ("h multipool", "Traceable because it used more than one pool size."),
    ("h repeat", "Traceable because it was paid three or more times."),
    ("h cluster", "Traceable because withdrawals came in a burst."),
    ("h any", "`1` if any of the four above apply."),
]


def key_block():
    out = ["## What the columns mean", ""]
    out.append("| column | meaning |")
    out.append("|---|---|")
    for label, text in MEANINGS:
        out.append("| {} | {} |".format(label, text))
    out.append("")
    out.append("The four `h` columns are linkage heuristics. Each marks a "
               "way the wallet gave itself away. `h any` is the union, so a "
               "`0` there means none of them caught it.")
    out.append("")
    return out


def clean(value, key):
    """Make a cell safe for a markdown table."""
    text = (value or "").replace("|", ", ").replace("\n", " ").strip()
    if key == "address" and text:
        return "`{}`".format(text)
    return text


def as_table(rows, csv_name):
    out = ["# Address profiles", ""]
    out.append(HEADER.format(count=len(rows), csv=csv_name))
    out.append("")
    out.extend(key_block())
    out.append("## Profiles")
    out.append("")
    out.append("| " + " | ".join(label for _, label in COLUMNS) + " |")
    out.append("|" + "|".join(["---"] * len(COLUMNS)) + "|")
    for row in rows:
        out.append("| " + " | ".join(
            clean(row.get(key), key) for key, _ in COLUMNS) + " |")
    out.append("")
    return out


def as_sections(rows, csv_name):
    out = ["# Address profiles", ""]
    out.append(HEADER.format(count=len(rows), csv=csv_name))
    out.append("")
    out.extend(key_block())
    for row in rows:
        out.append("---")
        out.append("")
        out.append("## {}. `{}`".format(row.get("n", ""), row.get("address", "")))
        out.append("")
        out.append("| | |")
        out.append("|---|---|")
        for key, label in COLUMNS:
            if key in ("n", "address"):
                continue
            value = clean(row.get(key), key)
            out.append("| {} | {} |".format(label, value or "—"))
        out.append("")
    return out


def verify(lines, expected):
    """Refuse to write a table that would render broken.

    Only the profiles table is checked. The column key above it is a
    two column table and would otherwise be flagged.
    """
    try:
        start = lines.index("## Profiles")
    except ValueError:
        start = 0
    data = [l for l in lines[start:]
            if l.startswith("| ") and not l.startswith("| # ")]
    counts = {len(l.strip("|").split("|")) for l in data}
    return data, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=IN_CSV)
    parser.add_argument("--out", default=OUT_MD)
    parser.add_argument("--sort", default="n",
                        help="column to sort by, numeric where possible")
    parser.add_argument("--per-address", action="store_true",
                        help="one section per address instead of one table")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        raise SystemExit(
            "\n  {} not found. Run address_profiles.py first.".format(args.csv))

    rows = list(csv.DictReader(open(args.csv)))
    if not rows:
        raise SystemExit("\n  {} is empty.".format(args.csv))

    missing = [k for k, _ in COLUMNS if k not in rows[0]]
    if missing:
        print("  columns absent from the CSV and skipped: {}".format(
            ", ".join(missing)))

    def key(row):
        value = row.get(args.sort, "")
        try:
            return (0, float(value))
        except (TypeError, ValueError):
            return (1, str(value))

    rows.sort(key=key)

    name = os.path.basename(args.csv)
    lines = (as_sections(rows, name) if args.per_address
             else as_table(rows, name))

    if not args.per_address:
        data, counts = verify(lines, len(COLUMNS))
        if counts != {len(COLUMNS)}:
            raise SystemExit(
                "\n  Refusing to write. {} row(s) have the wrong cell count:"
                "\n  found {}, expected {}. A value probably contains a"
                "\n  character that breaks the table.".format(
                    len(data), sorted(counts), len(COLUMNS)))

    with open(args.out, "w") as handle:
        handle.write("\n".join(lines) + "\n")

    print("=" * 60)
    print("WROTE {}".format(args.out))
    print("=" * 60)
    print("  addresses            {:>8,}".format(len(rows)))
    print("  columns              {:>8,}".format(len(COLUMNS)))
    print("  lines                {:>8,}".format(len(lines)))
    print("  layout               {}".format(
        "one section per address" if args.per_address else "single table"))
    print("  sorted by            {}".format(args.sort))
    if not args.per_address:
        print("\n  Every row checked for {} cells before writing.".format(
            len(COLUMNS)))
    print("\n  Upload alongside {} so the link resolves.".format(name))


if __name__ == "__main__":
    main()
