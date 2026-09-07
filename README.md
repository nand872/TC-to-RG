# Tornado Cash to Railgun

Empirical measurement of connectivity between Tornado Cash withdrawal addresses
and Railgun shielding addresses, on Ethereum mainnet.

The withdrawal set is restricted to the contracts named in the OFAC designation
of 8 August 2022. All data was collected from an archive node rather than from
any third party service, and every figure can be reproduced from the scripts
here.

| | Shielders reached | Share of 29,256 |
|---|---:|---:|
| **Depth 0**, one address withdrew and shielded | 387 | 1.32% |
| **Depth 1**, B withdrew, paid C, C shielded | 1,132 | 3.87% |
| Depth 2, two intermediates | 11,858 | 40.53% |

Depth 2 is where the method stops working. 91.7% of it runs through 149 shared
utility contracts including WETH, 1inch and Railgun's own helper contract.

## Three findings

**Heavier users, not more careful ones.** Against matched controls, at both
depths, the people who reached Railgun used Tornado substantially more than
comparable users who did not. Their operational discipline was
indistinguishable. The activity difference held across three independent control
draws at depth 0; the discipline measures changed sign between draws.

**46 addresses destroyed their own anonymity** by depositing into and
withdrawing from the same pool with one address. They account for 41.5% of the
ETH in the depth 0 set, or 22.1% once a single contract is set aside. Across the
whole protocol the rate is one depositor in eight, and within this population it
fell from 25.9% to 7.3% between the earliest and latest cohorts.

**The two depths disagree about the sanction.** Direct connections cluster after
the designation was lifted, at 53.2%. Chains with an intermediate cluster during
it, at 46.5%. Chains also became simpler over time and exchange involvement
vanished after 2025. The reading is that people inserted a step while the
sanction was active and stopped once it was not, which neither depth could show
alone.

Full results in **[RESULTS.md](RESULTS.md)**. Narrative reports in
**[DEPTH0.pdf](DEPTH0.pdf)** and **[DEPTH1.pdf](DEPTH1.pdf)**, both written for
readers without a background in this.

## What was collected

| | Count |
|---|---:|
| Tornado withdrawal events | 292,098 |
| Distinct withdrawal recipients | 127,137 |
| Of those, paid by designated contracts | 125,359 |
| Tornado deposit events | 311,199 |
| Deposit transactions resolved to a sender | 310,087, 99.6% |
| Railgun shielders | 29,256 |
| Outward payments from every recipient | 17,204,941 |
| Forward sweep coverage | 100% |

## Collection

| File | What it does | Why it is here |
|---|---|---|
| `sweep_rpc.py` | Shared RPC plumbing: range sweeping, cap detection, resumable progress | Every collector depends on it |
| `collect_withdrawals.py` | Sweeps the `Withdrawal` event with no address filter | Produces the withdrawal set. No filter means forks are found rather than assumed away |
| `collect_deposits.py` | Sweeps the `Deposit` event, then resolves each transaction's sender | The deposit side, which the address reuse finding depends on |
| `railgun11.py` | Collects Railgun logs, then resolves shield senders | The `Shield` event does not name the shielder, so it takes two phases |
| `trace_outflows.py` | Sweeps every payment made by all 127,137 recipients | The forward graph at 100% coverage |
| `repair_ranges.py` | Re-sweeps block ranges that timed out, in smaller pieces | Seven ranges in the busy early 2021 period failed repeatedly |
| `split_seeds.py` | Splits a sweep into chunks writing to separate databases | A single SQLite file past a few gigabytes slows to a halt |

## Filtering

| File | What it does | Why it is here |
|---|---|---|
| `filter_designated.py` | Restricts to the 38 OFAC addresses | A withdrawal from an unsanctioned clone is not a withdrawal from the sanctioned entity |
| `classify_addresses.py` | Labels addresses as account or contract | A contract in a population statistic is infrastructure, not a person |

## Depth 0 analysis

| File | What it does | Why it is here |
|---|---|---|
| `address_profiles.py` | Builds a 34 column profile per address | The base table everything else reads |
| `hop0_deep.py` | Five layers: population, inflow, behaviour, exposure, exclusions | The main descriptive analysis |
| `control_group.py` | Draws a matched control of recipients who never shielded | Turns description into comparison. Run at three seeds |
| `address_match.py` | Deposit side against withdrawal side | The strongest published heuristic. Produced the 46 self matched addresses |
| `gas_fingerprint.py` | Gas price fingerprinting after Béres et al. | Run at full coverage and produced no usable match. Included because a method run and failed is a different claim from one not attempted |
| `hop0_clusters.py` | Four linking rules, to estimate actors rather than addresses | 387 addresses are not 387 people |
| `hop0_crosstab.py` | Cross tabulations and threshold sensitivity | One dimensional tables hide the interactions |
| `check_top_holders.py` | Classifies the largest holders, recomputes value without contracts | One contract is a quarter of the ETH in the set |
| `final_checks.py` | Value in the self matched addresses, gas price block distance | Two checks that corrected earlier errors |

## Depth 1 analysis

| File | What it does | Why it is here |
|---|---|---|
| `chain_profiles.py` | One row per chain, both addresses profiled | The depth 1 base table |
| `hop1_deep.py` | Five layers, plus chain shape | Shape does not exist at depth 0 and changes what a chain means |
| `hop1_control.py` | Matched control drawn from the forward graph | A control for a chain has to be another chain, B′ pays C′ where C′ never shielded |
| `hop1_crosstab.py` | Cross tabulations, sensitivity, and the four denominators | Depth 1 has four different totals and mixing them is the easiest way to misread it |
| `chain_timing.py` | Every chain with all three gaps, in a browsable table | Aggregates hide everything here. The median gap 2 is four minutes; the spread on gap 1 runs from days to years |
| `reconcile_timing.py` | Computes the first gap two ways from one source | Two figures for the same quantity were in the repository. This established that neither reproduces the published 4.0 days |

## Population and depth 2

| File | What it does |
|---|---|
| `withdrawal_frequency.py` | Frequency, pools, relayers, time series across the whole protocol |
| `linkage_heuristics.py` | Four withdrawal side heuristics across all 127,122 participants |
| `depth2_forward.py` | Depth 2 by joining the forward graph against the funding layer |
| `verify_coverage.py` | Confirms every seed was queried, from the collector's own bookkeeping |
| `sweep_status.py` | Coverage across every outflow database |

## Presentation

| File | What it does |
|---|---|
| `build_addresses_md.py` | Renders `address_profiles.csv` as a browsable table |
| `build_chains_md.py` | The same for `chain_profiles.csv` |

## Data

| File | Contents |
|---|---|
| [ADDRESSES.md](ADDRESSES.md) | The 387 depth 0 addresses, one row each, with a column key |
| [address_profiles.csv](address_profiles.csv) | The same, 34 columns |
| [CHAINS.md](CHAINS.md) | The 1,244 depth 1 chains |
| [chain_profiles.csv](chain_profiles.csv) | The same, 31 columns |
| [TIMING.md](TIMING.md) | Every chain with all three gaps |
| [chain_timing.csv](chain_timing.csv) | The same, in days |
| [address_match.csv](address_match.csv) | Deposit and withdrawal counts per address |
| [top_holders.csv](top_holders.csv) | Depth 0 with account or contract labels |
| [hop0_crosstab.csv](hop0_crosstab.csv) | Segment, cohort and matching per address |
| [hop1_crosstab.csv](hop1_crosstab.csv) | Shape, cohort and freshness per chain |

No database files are committed. `tornado_outflows.db` alone is six gigabytes.

## Reproducing

```
pip install -r requirements.txt
export TC_RPC_URL="http://your-archive-node:8545"

python3 collect_withdrawals.py
python3 filter_designated.py
python3 railgun11.py --logs
python3 railgun11.py --senders 0xTOPIC
python3 collect_deposits.py
python3 collect_deposits.py --senders
python3 trace_outflows.py --max-hops 1

python3 address_profiles.py
python3 hop0_deep.py --dump
python3 control_group.py --dump
python3 address_match.py --dump
python3 gas_fingerprint.py --dump
python3 hop0_clusters.py --funder-cap 2 --no-session
python3 hop0_crosstab.py --dump
python3 check_top_holders.py --dump

python3 chain_profiles.py
python3 hop1_deep.py --dump
python3 hop1_control.py --dump
python3 hop1_crosstab.py --dump
python3 chain_timing.py --md
```

An archive node is required. `trace_outflows.py` takes days on a laptop; use
`split_seeds.py` if a database grows past a couple of gigabytes.

## Notes on method

**The event, not value transfers.** A DAI pool moves no ETH and is invisible to
a trace based sweep. The `Withdrawal` event fires for every denomination.

**Relayers are separated by the protocol, not by heuristic.** The event places
the recipient in the data field and the relayer in an indexed topic, so no
frequency cutoff is needed.

**779 events decoded a zero recipient and are excluded.** 775 come from a small
number of transactions at the 0.1 ETH pool's deployment in December 2019, each
firing the event exactly 100 times, which is contract initialisation.

**Assets are never summed.** ETH and DAI are reported separately.

**Denominators are always named at depth 1.** There are four in play: 1,244
chains, 981 withdrawal addresses, 1,132 shielders, 29,256 all shielders.

## Corrections

Figures previously published here that did not survive checking are listed in
[RESULTS.md](RESULTS.md) section 10, with what replaced them and how each was
found. They include a timing figure that could not be reproduced, a value total
that counted addresses more than once, and a depth 1 count contaminated by
exchange hot wallets.

## Known gaps

Railgun unshields were never collected, so whether these addresses took the
money back out is unknown. That is the difference between Railgun as a stop in a
chain and Railgun as a destination, and it is the largest remaining gap.

Railgun records begin May 2022 rather than December 2021, so only 57 shielders
predate the designation.

No clustering has been run at depth 1, so 981 withdrawal addresses have not been
reduced to an actor estimate.

## Licence

MIT.
