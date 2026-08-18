# Tornado Cash to Railgun

```mermaid
graph LR
    P[Tornado pool] -->|withdrawal| B[Address B]
    B -->|shields| R0[Railgun 0zk]
    B -->|funds| C[Address C]
    C -->|shields| R1[Railgun 0zk]

    style B fill:#1f3a5f,color:#fff
    style C fill:#1f3a5f,color:#fff
```

## Headline

| | Shielders | Share of all shielders |
|---|---:|---:|
| Reached at depth 0 or 1 | 1,883 | 6.44% |
| Depth 0, same address on both sides | 387 | 1.32% |
| Depth 1, funded by a withdrawal address | 1,496 | 5.11% |
| All Railgun shielders | 29,256 | 100% |

Depth 1 comes from 1,698 withdrawal address to shielder pairs, involving 1,002
distinct withdrawal addresses. There are more pairs than shielders because some
shielders received money from more than one withdrawal address. The two depths
are disjoint, so no shielder is counted twice.

The withdrawal set is restricted to contracts named in the OFAC designation of
8 August 2022.

## Month by month

| Month | New shielders | Depth 1 | Share |
|---|---:|---:|---:|
| 2022-05 | 15 | 2 | 13.33% |
| 2022-06 | 23 | 5 | 21.74% |
| 2022-07 | 19 | 4 | 21.05% |
| **2022-08** | 66 | 20 | 30.30% |
| 2022-09 | 88 | 13 | 14.77% |
| 2022-10 | 61 | 10 | 16.39% |
| 2022-11 | 86 | 6 | 6.98% |
| 2022-12 | 96 | 11 | 11.46% |
| 2023-01 | 200 | 79 | 39.50% |
| 2023-02 | 155 | 9 | 5.81% |
| 2023-03 | 186 | 16 | 8.60% |
| 2023-04 | 253 | 25 | 9.88% |
| 2023-05 | 223 | 18 | 8.07% |
| 2023-06 | 259 | 43 | 16.60% |
| 2023-07 | 218 | 26 | 11.93% |
| 2023-08 | 253 | 24 | 9.49% |
| 2023-09 | 243 | 20 | 8.23% |
| 2023-10 | 282 | 27 | 9.57% |
| 2023-11 | 299 | 32 | 10.70% |
| 2023-12 | 292 | 30 | 10.27% |
| 2024-01 | 330 | 30 | 9.09% |
| 2024-02 | 252 | 23 | 9.13% |
| 2024-03 | 370 | 21 | 5.68% |
| 2024-04 | 408 | 21 | 5.15% |
| 2024-05 | 668 | 35 | 5.24% |
| 2024-06 | 626 | 46 | 7.35% |
| 2024-07 | 479 | 29 | 6.05% |
| 2024-08 | 706 | 33 | 4.67% |
| 2024-09 | 705 | 34 | 4.82% |
| 2024-10 | 606 | 22 | 3.63% |
| 2024-11 | 556 | 32 | 5.76% |
| 2024-12 | 534 | 30 | 5.62% |
| 2025-01 | 648 | 36 | 5.56% |
| 2025-02 | 604 | 21 | 3.48% |
| 2025-03 | 822 | 26 | 3.16% |
| 2025-04 | 867 | 28 | 3.23% |
| 2025-05 | 834 | 30 | 3.60% |
| 2025-06 | 787 | 36 | 4.57% |
| 2025-07 | 728 | 35 | 4.81% |
| 2025-08 | 1,166 | 37 | 3.17% |
| 2025-09 | 1,095 | 79 | 7.21% |
| 2025-10 | 1,118 | 51 | 4.56% |
| 2025-11 | 966 | 45 | 4.66% |
| 2025-12 | 1,443 | 64 | 4.44% |
| 2026-01 | 1,666 | 47 | 2.82% |
| 2026-02 | 978 | 27 | 2.76% |
| 2026-03 | 1,123 | 39 | 3.47% |
| 2026-04 | 943 | 26 | 2.76% |
| 2026-05 | 997 | 29 | 2.91% |
| 2026-06 | 1,075 | 34 | 3.16% |
| 2026-07 | 1,336 | 21 | 1.57% |
| 2026-08 | 503 | 9 | 1.79% |

August 2022, the designation month, is in bold. The first one hop shielder
appears in May 2022 and the busiest month by count is September 2025 with 79.

Aggregated by year, the share is the column that carries meaning. Counts track
Railgun's own growth.

| Year | New shielders | Depth 1 | Share |
|---|---:|---:|---:|
| 2022 | 454 | 71 | 15.64% |
| 2023 | 2,863 | 349 | 12.19% |
| 2024 | 6,240 | 356 | 5.71% |
| 2025 | 11,078 | 488 | 4.41% |
| 2026 | 8,621 | 232 | 2.69% |

## Lag structure

Depth 1 has three events, so it has three intervals.

| | Withdrawal to funding | Funding to shield | End to end |
|---|---:|---:|---:|
| Negative, out of order | 151, 8.9% | 200, 11.8% | 55, 3.2% |
| Same day | 254, 15.0% | 1,018, 60.0% | 210, 12.4% |
| 1 to 7 days | 51, 3.0% | 48, 2.8% | 51, 3.0% |
| 7 to 30 days | 69, 4.1% | 24, 1.4% | 61, 3.6% |
| 30 to 90 days | 82, 4.8% | 28, 1.6% | 66, 3.9% |
| 90 days to 1 year | 244, 14.4% | 55, 3.2% | 192, 11.3% |
| Over a year | 847, 49.9% | 325, 19.1% | 1,063, 62.6% |
| **Median** | **362.1 days** | **0.0 days** | **698.0 days** |

The shape is consistent and specific. The withdrawal address holds funds for a
long time, a median of nearly a year and almost half for more than one, and
then the recipient shields the same day it is paid in 60% of cases. The hop
itself is immediate. All of the delay sits upstream of it.

That is a recognisable operational signature. An address funded and used within
a single day, for the single purpose of shielding, is behaving as a purpose
created intermediate rather than as an ordinary wallet that happened to receive
a payment. It supports reading these chains as deliberate, while the long
upstream delay argues against any of it being a reaction to a specific event.

Ordering is reported and never applied. The negative rows are pairs where the
events run the wrong way round, and they are counted rather than removed.

## Coverage

| | |
|---|---:|
| Designated addresses | 38 |
| Of those, emitting withdrawal events | 23 |
| Withdrawal events collected | 281,121 |
| Distinct recipients | 125,092 |
| Railgun shielders | 29,256 |
| Shielders with at least one funding row | 29,237, 99.9% |
| Funding edges examined | 1,872,205 |
| Blocks swept | 16,660,000 |

1,872,205 is the search space, every incoming payment to any shielder from any
source. 1,698 of them had a designated Tornado contract's withdrawal recipient
as sender, roughly nine in every ten thousand.

The 15 designated addresses that emitted no withdrawal events are routers and
proxies, which do not emit the event.

The withdrawal set is built from the `Withdrawal` event rather than from ETH
value transfers, so it covers every denomination. Pools paying out in DAI,
USDC, USDT or WBTC move no ETH and produce no value bearing trace, and are
invisible to a trace based method. The event is emitted by the pool contract
regardless of what it pays out.

Relayers are named separately by the event, in an indexed topic distinct from
the recipient field, so no frequency heuristic is used to separate them. They
are excluded by construction, and the relayer count at every cutoff level is
zero.

## Robustness

The withdrawal set was collected three times, using methods that share almost
nothing, and the result is stable across all of them.

| | Traces, ETH pools | Logs, every emitter | Logs, designated |
|---|---:|---:|---:|
| Distinct recipients | 124,181 | 126,870 | **125,092** |
| Depth 0 | 384 | 391 | **387** |
| Depth 1 | 1,502 | 1,508 | **1,496** |
| Reached at depth 0 or 1 | 1,886 | 1,899 | **1,883** |

Depth 1 varies by 0.8% across the three. The finding does not depend on the
collection method.

Restricting from every contract emitting the event to the designated list
removed 147 contracts and 1.4% of recipients, and changed the result by 0.84%.
The contract list is not carrying the finding.

Depth 1 is also insensitive to the relayer cutoff. Between a cutoff of 25 and
none at all it moves from 1,465 to 1,496, and depth 0 from 384 to 387.

Payout counts across methods are not comparable. Traces recorded 498,710
payments because a relayed withdrawal pays twice out of the pool, once to the
recipient and once to the relayer. Logs record one event per withdrawal.
Payments fell while recipients rose, which confirms the two count different
things.

## Limits

**Observation window.** The shielder set begins at block 14,751,290, May 2022.
Railgun deployed in December 2021, so the first months are absent, likely
because Railgun sits behind an upgradeable proxy and a V1 shield event under a
different signature would be invisible to a filter written for the V2 event.
Only 57 shielders fall before the designation, 0.195% of the observation
window, so any before and after comparison rests on a narrow base.

**Funding layer covers ETH only.** The withdrawal set covers all denominations,
but incoming payments to shielders were collected from ETH value transfers.
Someone funded in USDC before shielding is invisible. Both depth figures are
floors.

**A funding edge is not an identity claim.** Two addresses joined by a payment
may or may not be controlled by the same person, and nothing on chain
distinguishes those cases.

**Neither an upper nor a lower bound on migration.** Not an upper bound,
because anyone who inserted a further hop, used an exchange, or bridged is
absent. Not a lower bound, because some counted connections are incidental.

**Depth 2 does not discriminate.** Asking who funded the addresses that funded
shielders is backwards expansion, measured at 745 edges per block and
projecting to roughly eleven billion rows. Ethereum's transfer graph has a
diameter of about four, so two hops back from any non trivial set reaches a
large share of all active addresses. That is a property of the graph rather
than of the node or the sweep.

---

Withdrawal set from contracts named in the OFAC designation of 8 August 2022,
collected from the `Withdrawal` event, all denominations, no relayer cutoff and
no time window applied at any stage.
