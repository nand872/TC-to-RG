# Following money out of a sanctioned mixer

**An empirical study of connectivity between Tornado Cash and Railgun on
Ethereum mainnet.**

---

## 1. Introduction

On 8 August 2022 the US Treasury's Office of Foreign Assets Control designated
Tornado Cash, naming 38 specific Ethereum addresses. It was the first time a
sanctions authority had listed autonomous software rather than a person or an
organisation, and it raised a question nobody could answer at the time: what
would the people using it do next?

The obvious hypothesis was migration. Railgun offers comparable privacy, was not
designated, and was operating. If Tornado's users wanted to keep doing what they
had been doing, Railgun was the place to do it.

This study measures whether that happened, how large the connection is, what the
people involved actually did, and — more usefully than any of those — where the
measurement stops working.

```mermaid
%%{init: {'theme':'neutral'}}%%
mindmap
  root((What was<br/>found))
    Size
      387 direct
      1132 through one payment
      5.19 percent of Railgun
    Behaviour
      Heavier Tornado users
      No more careful
      46 broke own anonymity
    Timing
      Direct cluster after sanction
      Chains cluster during it
      Shield takes 4 minutes
    Method limits
      Misses 57 percent of people
      Misses 18 percent of money
      Gas fingerprinting found nothing
```

The short answer is that the connection is small, specific, and not what the
migration hypothesis predicts. About one Railgun user in twenty is reachable
from a sanctioned Tornado withdrawal within a single payment. Those users
handled Tornado more heavily than comparable people who never touched Railgun,
but no more carefully. And the timing runs the wrong way for a migration story:
direct connections cluster *after* the designation was lifted, not during it.

One further result cuts against the argument this work was expected to support.
Published tracing techniques fail on a clear majority of these addresses, but
the addresses they fail on hold almost none of the money.

---

## 2. Background

### 2.1 What the two protocols do

Everything on Ethereum is public. Amounts, timings, counterparties. Privacy
tools cannot conceal a transaction, so instead they sever the link between
transactions.

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart LR
    subgraph T["Tornado Cash hides the origin"]
        D[deposit address] --> P[fixed-size pool]
        P -. link broken .-> W[withdrawal address]
    end
    subgraph R["Railgun hides the destination"]
        S[public address] --> Z[shielded balance]
        Z -. link broken .-> X[anything after]
    end
```

**Tornado Cash** takes a fixed amount from one address and later returns the
same amount to a fresh one. Both events are public; nothing on the chain
connects them. Amounts are fixed at 0.1, 1, 10 or 100 ETH precisely so the
amount itself reveals nothing.

**Railgun** takes funds from a public address into a private balance, a step
called *shielding*. That transaction is necessarily public. Everything
afterwards is not.

### 2.2 The relayer problem

A newly created withdrawal address holds nothing, and every Ethereum transaction
costs a fee. Funding it beforehand would create a payment pointing directly at
it, undoing the entire exercise.

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart TD
    A[fresh address<br/>holds nothing] --> Q{how is the<br/>fee paid?}
    Q -->|relayer pays it| G[no link created<br/>90.9 percent of cases]
    Q -->|you fund it first| L[funding payment<br/>points at you<br/>9.1 percent]
```

That 9.1% who paid their own fee made a mistake, and the rate is a usable
measure of operational care throughout this study.

### 2.3 The question

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart LR
    P[sanctioned<br/>Tornado pool] -->|withdrawal| B[address B]
    B -->|shields directly<br/>DEPTH 0| R0[Railgun]
    B -->|pays| C[address C]
    C -->|shields<br/>DEPTH 1| R1[Railgun]
```

Two patterns. **Depth 0** is one address doing both jobs. **Depth 1** is a chain
with one address in between. Their disagreement turns out to be the most
informative result in the study.

---

## 3. Data and methodology

### 3.1 The collection pipeline

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart TD
    A[sweep the chain for the<br/>Withdrawal event<br/>no address filter] --> B[170 contracts found]
    B --> C{which are<br/>sanctioned?}
    C -->|38 OFAC addresses| D[23 ever paid anyone]
    C -->|147 forks and lookalikes| E[excluded<br/>1,778 recipients]
    D --> F[292,098 events]
    F --> G[125,359 distinct recipients]
    G --> H[sweep every payment<br/>they ever made]
    H --> I[17,204,941 payments<br/>100 percent coverage]
```

All data came from an Ethereum archive node. No third-party service, no
commercial dataset, no purchased address labels.

| Dataset | Volume |
|---|---:|
| Tornado withdrawals | 292,098 events |
| Restricted to designated contracts | 125,359 recipients |
| Tornado deposits | 311,199 events |
| Deposit senders resolved | 310,087, 99.6% |
| Railgun shielders | 29,256 addresses |
| Outward payments collected | 17,204,941 |

### 3.2 Three decisions that shaped everything

**The event rather than value transfers.** A pool paying out DAI moves no ETH.
Searching for ETH movements would have silently omitted every stablecoin
withdrawal. The `Withdrawal` event is emitted by inherited code before the
asset-specific payment, so it fires identically for every denomination.

**No address filter during collection.** The sweep found 170 contracts emitting
that event against about twenty Tornado ever deployed. Had it been restricted to
known addresses, the forks would have been invisible. Six of them are ETH mixers
whose first payout came within seven weeks of the designation.

**Restriction to the designated list afterwards.** A withdrawal from an
unsanctioned clone is not a withdrawal from the sanctioned entity.

### 3.3 One documented exclusion

779 events decoded a zero recipient. 775 originate from a handful of
transactions within sixteen blocks of the 0.1 ETH pool's deployment in December
2019, each emitting the event exactly 100 times. That is contract
initialisation, and a zero recipient cannot be a controlled address.

### 3.4 The comparison design

Descriptive statistics about a selected group mean little without a comparison.
Saying 26% of these addresses used multiple pool sizes invites the question:
compared to what?

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart TD
    A[each address that<br/>reached Railgun] --> B[find a Tornado user<br/>who never shielded]
    B --> C[match on year started<br/>and main pool size]
    C --> D[compare behaviour]
    D --> E[repeat three times<br/>with different draws]
    E --> F{same sign<br/>every time?}
    F -->|yes| G[real difference]
    F -->|no| H[sampling noise]
```

For **depth 1** the unit is a pair, so the control had to be a pair: B′ pays C′
where C′ never shielded. That required drawing from the 27-million-payment
forward graph rather than the withdrawal list.

---

## 4. Results

### 4.1 The headline

| | Shielders reached | Share of 29,256 | 95% interval |
|---|---:|---:|---:|
| **Depth 0** | 387 | 1.32% | 1.20 – 1.46% |
| **Depth 1** | 1,132 | 3.87% | 3.66 – 4.09% |
| **Combined** | **1,519** | **5.19%** | |

Depth 0 is the most reliable figure here. It requires no payment tracing, no
graph, no judgement calls. Two independent collection methods, one working
backward from Railgun and one forward from Tornado across 17.2 million payments,
produced the same 387.

### 4.2 Four kinds of user

```mermaid
%%{init: {'theme':'neutral'}}%%
mindmap
  root((withdrawal<br/>addresses))
    Used once
      one withdrawal ever
      41 percent at depth 0
      56 percent at depth 1
    Collected an amount
      several withdrawals
      or several pool sizes
      the classic signature
    Came back
      exactly two withdrawals
      same pool size
    Operator
      fifty or more withdrawals
      or ten or more shields
      seven addresses
```

Because Tornado only pays fixed sizes, somebody wanting 43 ETH must take 10 four
times and 1 three times. That behaviour is both a practical necessity and a
signature, since those withdrawals plainly belong together.

### 4.3 Value is extraordinarily concentrated, differently at each depth

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart LR
    subgraph D0["Depth 0, 30,274 ETH"]
        A1[7 operators<br/>51.9 percent]
        A2[135 collectors<br/>27.0 percent]
        A3[86 came back<br/>11.7 percent]
        A4[159 used once<br/>9.5 percent]
    end
    subgraph D1["Depth 1, 105,927 ETH"]
        B1[356 collectors<br/>79.2 percent]
        B2[547 used once<br/>13.1 percent]
        B3[7 operators<br/>5.1 percent]
    end
```

At depth 0, seven addresses hold 51.9% of the value, averaging 2,245 ETH each
against 18 for the single-use group — a ratio of 125 to 1. At depth 1 those same
operators hold 5.1% and the collectors dominate at 79.2%.

These are not one population behaving differently. They are different kinds of
user, and any statement about either must say whether it counts addresses or
money, because the two give opposite pictures.

### 4.4 The shape of a chain

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart LR
    subgraph one["One to one, 60.5 percent"]
        B1[B] --> C1[C] --> R1[Railgun]
    end
    subgraph split["One B, many C, 18.9 percent"]
        B2[B] --> C2[C]
        B2 --> C3[C]
        B2 --> C4[C]
    end
    subgraph merge["Many B, one C, 11.7 percent"]
        B3[B] --> C5[C]
        B4[B] --> C5
        B5[B] --> C5
    end
```

Six chains in ten are a simple line. The remaining four sit inside a wider
structure, and describing them as one person routing money through one
intermediate would be wrong.

The "many B, one C" group deserves particular scepticism. **91% of those
recipients already had a transaction history**, against 55% for the simple
chains, which fits a collection point rather than a purpose-made conduit.

### 4.5 What the recipients looked like

An address's transaction count rises only when it *sends*. Money arriving does
not change it. So an address with a count of one has done exactly one thing in
its existence.

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart TD
    A[1,244 recipients] --> B{had it ever<br/>sent anything?}
    B -->|no, 443 chains<br/>35.6 percent| C[purpose-built conduit<br/>the shield was its<br/>first and only act]
    B -->|yes, 801 chains<br/>64.4 percent| D[an existing wallet<br/>the payment means<br/>something different]
```

About a third of recipients were purpose-built conduits. Two thirds were not,
which sits awkwardly with the standard description of this pattern as money
passing through a disposable address.

### 4.6 Timing: two gaps that behave nothing alike

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart LR
    T[Tornado pays B] -->|gap 1<br/>median 6.5 months<br/>quarter under 5 days<br/>quarter over 2 years| PAY[B pays C]
    PAY -->|gap 2<br/>median 4 minutes<br/>quarter under 2 min<br/>quarter over 39 min| S[C shields]
```

**Gap 2 is bimodal, not simply fast.**

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart TD
    A[gap 2, payment to shield] --> B[shielded before being paid<br/>150 chains, 12.1 percent]
    A --> C[within the hour<br/>800 chains, 64.3 percent]
    A --> D[same day<br/>87 chains, 7.0 percent]
    A --> E[over a year<br/>126 chains, 10.1 percent]
    C --> F[fast enough to be<br/>scripted or one sitting]
    E --> G[payment and shield are<br/>unrelated events]
```

Among the 1,094 chains that run in the right order, **73.1% shielded within the
hour**.

**And the two gaps are independent:**

| | Chains | Shielded same day |
|---|---:|---:|
| B paid onward within a week | 326 | 78.8% |
| B waited over a year | 511 | 78.3% |

Identical. How long the withdrawal address held the money says nothing about how
fast the recipient acted. That suggests two separate decisions by two different
parties, or one automated step following one human one.

End-to-end timing tracks gap 1 almost exactly, so reporting it adds nothing over
reporting gap 1.

### 4.7 The comparison: heavier, not more careful

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart TD
    A[compared against<br/>matched controls] --> B[HOW MUCH they used Tornado]
    A --> C[HOW CAREFULLY they used it]
    B --> B1[used 2+ pool sizes<br/>+11 to +17 points]
    B --> B2[made 3+ withdrawals<br/>+10 to +13 points]
    B --> B3[withdrawals each<br/>1.6 times more]
    C --> C1[paid own fee<br/>+0.0 to -1.1 points]
    C --> C2[used a relayer<br/>+2.3 to -4.0 points]
    B1 --> D[REAL, held across<br/>all three draws]
    B2 --> D
    B3 --> D
    C1 --> E[NULL, changed sign<br/>between draws]
    C2 --> E
```

Every activity measure is higher, at both depths. Every discipline measure is
indistinguishable, and at depth 0 they *change sign* between draws, making them
nulls rather than small effects.

The most plausible reading: finding Railgun, understanding shielding and
trusting a second protocol all require engagement that casual users lack. But
knowing Railgun exists tells you nothing about whether you remember to use a
relayer. **Sophistication and carefulness are different things, and the data
separates them cleanly.**

### 4.8 Users who destroyed their own anonymity

Tornado's guarantee holds against the protocol. It does not hold against a user
who deposits and withdraws with the same address.

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart TD
    subgraph correct["Correct use"]
        A1[address A] -->|deposits 100| P1[100 ETH pool]
        P1 -->|withdraws 100| B1[address B]
        B1 --> N1[no link visible]
    end
    subgraph broken["Self-defeating use"]
        A2[address A] -->|deposits 100| P2[100 ETH pool]
        P2 -->|withdraws 100| A2
        A2 --> N2[anyone can see A<br/>on both sides<br/>proof is now pointless]
    end
```

| | Count | Share |
|---|---:|---:|
| Distinct depositors, whole protocol | 65,226 | |
| Also appear as a withdrawal recipient | 11,976 | 18.4% |
| **Same address, same pool** | **8,533** | **13.1%** |
| Depth 0 addresses that also deposited | 63 | 16.3% |
| **Of those, same address same pool** | **46** | **11.9%** |

**One depositor in eight, across the entire history of the protocol, did this.**

Those 46 addresses account for **41.5% of the ETH** in the depth 0 set, or 22.1%
once a single large contract is set aside. The mistake was made
disproportionately by people moving large sums.

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart LR
    A[2020 to 2021<br/>25.9 percent] --> B[2022 to 2024<br/>13.0 percent] --> C[2025 to 2026<br/>7.3 percent]
    C --> D[users got<br/>markedly more careful<br/>z equals 3.94]
```

Because cohort composition did not change, this is a genuine improvement in
behaviour rather than a shift in who was using the protocol.

Self-matching also concentrates in heavy users: 42.9% of operators against 3.8%
of single-use addresses.

The clearest single case made **nine deposits and nine withdrawals from the 100
ETH pool with one address** — 900 ETH in, 900 ETH out, no anonymity gained at
any point — and then shielded.

### 4.9 A published method that failed

Gas price fingerprinting holds that people set idiosyncratic gas prices which
recur, so an unusual price shared by two transactions suggests one sender.

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart TD
    A[310,087 deposits<br/>with gas prices] --> B[exclude round values<br/>wallet defaults]
    B --> C[6 candidate pairs<br/>touching depth 0]
    C --> D{how far apart<br/>in blocks?}
    D -->|5 pairs: same block| E[worthless]
    D -->|1 pair: 4 blocks| F[worthless]
    D -->|1 pair: 37 days<br/>but 13.01 gwei| G[round number, weak]
    E --> H[usable matches: ZERO]
    F --> H
    G --> H
```

**Why same-block is fatal rather than unlucky:** block builders order
transactions by gas price. Two transactions bidding the same price land in the
same block *by construction*. A shared price predicts a shared block and says
nothing about a shared sender.

The threshold was also barely selective. With 311,199 transactions across
182,539 distinct prices, an average price appears 1.7 times, so 98% qualify as
"rare" by construction.

This is reported because a method run and failed is a stronger claim than a
method never attempted.

### 4.10 Traceability, and a result that cuts the wrong way

```mermaid
%%{init: {'theme':'neutral'}}%%
mindmap
  root((four ways an<br/>address gives<br/>itself away))
    Paid own fee
      it held money first
      so someone funded it
      that payment is visible
    Used several pool sizes
      only one person holds
      notes for both
    Paid three or more times
      those withdrawals
      belong together
    Withdrew in bursts
      one session
      not separate decisions
```

| | Addresses | Share | ETH | Share of value | Mean |
|---|---:|---:|---:|---:|---:|
| Detected | 165 | 42.6% | 24,782.6 | **81.9%** | 150.2 |
| **Not detected** | **222** | **57.4%** | 5,491.3 | **18.1%** | 24.7 |

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart LR
    A[387 addresses] --> B[165 detected<br/>42.6 percent of people<br/>81.9 percent of money]
    A --> C[222 not detected<br/>57.4 percent of people<br/>18.1 percent of money]
    B --> D[average 150 ETH each]
    C --> E[average 25 ETH each]
```

At depth 1 the same test gives 60.0% of chains detected holding **92.4%** of the
value.

**Standard techniques miss most of the people and almost none of the money.**
The undetected population is not merely a minority of value — it is a poor one.

An honest qualification: three of the four techniques cannot fire on an address
used once, so part of that 57.4% is arithmetic rather than evasion. What these
methods detect is **reuse**, and 41.1% of this population never reused.

### 4.11 The two depths disagree about the sanction

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart TD
    subgraph d0["DEPTH 0, direct"]
        A0[before: 15 percent] --> B0[during: 32 percent] --> C0[after: 53 percent]
    end
    subgraph d1["DEPTH 1, with an intermediate"]
        A1[before: 30 percent] --> B1[during: 47 percent] --> C1[after: 24 percent]
    end
    C0 --> X[peaks AFTER<br/>the sanction ended]
    B1 --> Y[peaks DURING<br/>the sanction]
```

The obvious objection — that this reflects Tornado being busier in one period —
was tested. Tornado's own withdrawal volume in 2025–26 was **30.2%** of all
time. The depth 0 figure of 53.2% has an interval of 48.3–58.2%, which does not
come near it.

The chain shapes corroborate the pattern:

| Period | Simple one-to-one chains | Chains involving a service |
|---|---:|---:|
| 2020–21 | 44% | 8% |
| 2022–24 | 66% | 7% |
| **2025–26** | **70%** | **0%** |

Chains became steadily simpler, and exchange involvement disappeared entirely.
Every service-linked chain in the dataset predates 2025.

**The reading:** while the designation was in force, people inserted an
intermediate address to put distance between themselves and the mixer. Once it
was lifted, they stopped bothering.

### 4.12 Who was removed, and why it barely mattered

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart TD
    A[everyone in the set] --> B{is this a person<br/>or a service?}
    B -->|relayer business| C[removed]
    B -->|exchange hot wallet| C
    B -->|contract with<br/>dozens of withdrawals| C
    B -->|shielded 10+ times| C
    B -->|everything else| D[kept]
    C --> E[depth 0: 387 becomes 380<br/>depth 1: 1,244 becomes 1,162]
    E --> F[headline moves<br/>1.32 to 1.30 percent<br/>3.87 to 3.63 percent]
```

That the correction is so small is itself informative: the result does not
depend on where those lines are drawn.

---

## 5. Discussion

### 5.1 The migration hypothesis does not survive

If the designation had driven Tornado's users toward Railgun, the direct
connection should cluster in 2022 and 2023. It does the opposite.

It is also worth stating plainly that the funds were never frozen. The pools are
immutable contracts with no owner and no pause function — the basis of the *Van
Loon* ruling in November 2024. The designation made transacting with those
addresses a legal offence for US persons; it did not and could not stop
withdrawals, which continued throughout at roughly 1,400 a month.

### 5.2 What did change was chain structure

The depth 1 concentration during the designation, together with the shape trend,
suggests the designation altered *method* rather than *volume*. People kept
using Tornado. While the sanction was live, more of them added a step.

This is the more interesting finding for a proportionality analysis, because it
is evidence that a designation changes conduct without necessarily reducing
activity.

### 5.3 The evidentiary picture is double-edged

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart TD
    A[what can be established?] --> B[counting addresses]
    A --> C[counting money]
    B --> B1[57 percent cannot<br/>be characterised]
    C --> C1[82 percent sits with<br/>addresses that can]
    B1 --> D[supports: most individuals<br/>are beyond reach]
    C1 --> E[undercuts: large flows<br/>are largely attributable]
```

An honest treatment states both. A regulator concerned with large-value flows is
in a considerably better position than the address count suggests. A person
worried about mass surveillance of small users is right that most individuals
are invisible.

### 5.4 Where measurement genuinely stops

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart LR
    A[125,359 seeds] -->|one payment out| B[1,826,874 addresses<br/>14.6 times more]
    B -->|another payment out| C[a substantial share of<br/>everything active<br/>on Ethereum]
    C --> D[at two intermediates<br/>40.5 percent of all<br/>Railgun users qualify]
    D --> E[91.7 percent of that runs<br/>through 149 shared utilities<br/>WETH, 1inch, Railgun's own helper]
```

Extending by one further hop was attempted and abandoned. A path through WETH
means one person wrapped ETH and an unrelated person later unwrapped some. This
is a property of the transfer graph, not of either protocol, and no better node
or longer sweep changes it.

---

## 6. Limitations

```mermaid
%%{init: {'theme':'neutral'}}%%
mindmap
  root((what this<br/>cannot say))
    Railgun withdrawals
      never collected
      cannot tell a waypoint
      from a destination
      THE LARGEST GAP
    Identity
      a payment is not
      an identity claim
      387 addresses are
      at most 371 actors
    Bounds
      not an upper bound
      extra hops are absent
      not a lower bound
      some links are incidental
    Coverage
      Railgun starts May 2022
      only 57 shielders
      predate the sanction
```

**Railgun unshields were never collected.** We know these addresses put money
into Railgun; we do not know whether they took it back out. Rapid unshielding
would indicate a waypoint in a chain; leaving funds shielded would indicate a
destination. Those support very different readings and the data to separate them
was not gathered.

**Threshold choices are judgement calls.** Service, relayer and operator
boundaries were set by the author and tested for sensitivity. The depth 0
segments proved stable across every cutoff from 10 to 200 withdrawals; the depth
1 fan-out threshold did not, and empties entirely at a cap of 50.

---

## 7. Conclusion

```mermaid
%%{init: {'theme':'neutral'}}%%
mindmap
  root((Conclusion))
    Size
      one Railgun user in twenty
      reachable within one payment
    Who
      heavier Tornado users
      no more careful
      46 destroyed own anonymity
    The sanction
      did not drive migration
      direct links peak after it
      chains peak during it
      it changed method not volume
    Measurement
      fails on most people
      succeeds on most money
      stops entirely at two hops
```

Roughly one Railgun user in twenty is reachable from a sanctioned Tornado Cash
withdrawal within a single payment — 387 directly, 1,132 through one
intermediate, 5.19% of the protocol's users combined.

The people involved used Tornado more heavily than matched peers who never
shielded, but handled it no more carefully. Forty-six of them destroyed their
own anonymity through address reuse, and those forty-six account for a
disproportionate share of the value.

The designation does not appear to have driven migration. Direct connections
concentrate *after* it was lifted. What it does appear to have changed is
method: chains with an intermediate address cluster during the sanction and
became simpler once it ended.

And the tracing picture depends entirely on what you count. By address, most of
this population is beyond the reach of published techniques. By value, most of
it is not.

---

## Reproducing this work

Every figure derives from scripts in this repository, run against an Ethereum
archive node. See [README.md](README.md) for the file manifest and
[RESULTS.md](RESULTS.md) for the complete tables, including a list of figures
that did not survive checking and what replaced them.

Narrative reports written for readers without a background in this:
[DEPTH0.pdf](DEPTH0.pdf) and [DEPTH1.pdf](DEPTH1.pdf).
