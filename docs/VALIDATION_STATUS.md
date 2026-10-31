# VALIDATION STATUS BOARD — one unit per turn, real data + costs

**Champion book (updated as units land): R3.1 — x2 +4.73%/mo SR 1.77 DD 27.4 | x3 +6.80%/mo. All-years-positive: R3 x2 +4.52/minYr +0.31.**

**Winners so far (validated PASS units eligible for END-01 ensemble): I-01 squeeze-family pair slot.**
**Progress: 26/184 units validated · 158 pending.**

Status legend: PENDING · RUNNING · PASS (placebo cleared) · FAIL · BLOCKED (no data).

| unit | status | result | note |
|---|---|---|---|
| **Earlier waves (done in EXP-047/048)** | | | |
| I-01 | PASS | +2.46%/mo SR 1.77 (slot placebo 100pct) | -> Book R3.1 |
| I-02 | FAIL | claims unverified; blend 67pct | |
| I-03 | FAIL | +0.12%/mo; blend 43pct | |
| I-04 | FAIL | inv-vol/vol-scale dominated | |
| I-05 | FAIL | 12h/common/EW squeeze dead | |
| I-06 | FAIL | causal hour-z 0 trades | |
| I-11 | BLOCKED | no basis data | |
| I-18 | FAIL | weekend split no edge | |
| **Volume Profile** | | | |
| VP-01 | FAIL | prescreen -3.0/-6.3%/mo |  |
| VP-02 | PENDING | - | - |
| VP-03 | FAIL | prescreen SR 0.12 placebo 77pct |  |
| VP-04 | FAIL | prescreen -2.2/-2.2%/mo |  |
| VP-05 | PENDING | - | - |
| VP-06 | PENDING | - | - |
| VP-07 | PENDING | - | - |
| VP-08 | PENDING | - | - |
| VP-09 | FAIL | prescreen -2.7/-3.1%/mo |  |
| VP-10 | PENDING | - | - |
| VP-11 | PENDING | - | - |
| VP-12 | PENDING | - | - |
| VP-13 | PENDING | - | - |
| VP-14 | PENDING | - | - |
| VP-15 | PENDING | - | - |
| VP-16 | PENDING | - | - |
| VP-17 | PENDING | - | - |
| VP-18 | FAIL | RVOL gating worsens R3.1 |  |
| VP-19 | PENDING | - | - |
| VP-20 | PENDING | - | - |
| VP-21 | PENDING | - | - |
| VP-22 | PENDING | - | - |
| **VP x SS combos** | | | |
| VPSS-01 | PENDING | - | - |
| VPSS-02 | PENDING | - | - |
| VPSS-03 | PENDING | - | - |
| **Sessions & Calendar** | | | |
| SS-01 | FAIL | prescreen -6.3/-3.5%/mo |  |
| SS-02 | PENDING | - | - |
| SS-03 | PENDING | - | - |
| SS-04 | FAIL | prescreen -5.7/-5.0%/mo |  |
| SS-05 | PENDING | - | - |
| SS-06 | FAIL | prescreen -6.1/-6.6%/mo |  |
| SS-07 | PENDING | - | - |
| SS-08 | PENDING | - | - |
| SS-09 | FAIL | prescreen cost burn 2.95%/day |  |
| SS-10 | FAIL | prescreen cost burn |  |
| SS-11 | PENDING | - | - |
| SS-12 | PENDING | - | - |
| SS-13 | FAIL | prescreen 0 trades |  |
| SS-14 | PENDING | - | - |
| SS-15 | PENDING | - | - |
| SS-16 | PENDING | - | - |
| SS-17 | PENDING | - | - |
| SS-18 | PENDING | - | - |
| SS-19 | PENDING | - | - |
| SS-20 | PENDING | - | - |
| SS-21 | PENDING | - | - |
| SS-22 | PENDING | - | - |
| SS-23 | PENDING | - | - |
| HLD-01 | PENDING | - | - |
| SEAS-01 | PENDING | - | - |
| SEAS-02 | PENDING | - | - |
| SEAS-03 | PENDING | - | - |
| **Patterns & Candles** | | | |
| CH-01 | PENDING | - | - |
| CH-02 | PENDING | - | - |
| CH-03 | PENDING | - | - |
| CH-04 | PENDING | - | - |
| CH-05 | PENDING | - | - |
| CH-06 | PENDING | - | - |
| CH-07 | PENDING | - | - |
| CH-08 | PENDING | - | - |
| CH-09 | PENDING | - | - |
| CH-10 | PENDING | - | - |
| CH-11 | PENDING | - | - |
| CH-12 | PENDING | - | - |
| CH-13 | PENDING | - | - |
| CH-14 | PENDING | - | - |
| CH-15 | PENDING | - | - |
| CH-16 | PENDING | - | - |
| CH-17 | PENDING | - | - |
| CH-18 | PENDING | - | - |
| CH-19 | PENDING | - | - |
| CH-20 | PENDING | - | - |
| CH-21 | PENDING | - | - |
| CH-22 | PENDING | - | - |
| CH-23 | PENDING | - | - |
| CH-24 | PENDING | - | - |
| CH-25 | PENDING | - | - |
| SD-01 | PENDING | - | - |
| SD-02 | PENDING | - | - |
| DAR-01 | PENDING | - | - |
| AMT-01 | PENDING | - | - |
| LV-01 | PENDING | - | - |
| **ICT / SMC** | | | |
| ICT-01 | FAIL | best +0.12%/mo SR 0.22 (BTC hold3) but DD 45.5/minYr -4.0 fail gates; ETH nodes -2.7..-3.9%/mo | placebo 97pct (signal real but too weak net) |
| ICT-02 | FAIL | all 10 nodes negative (-1.1..-6.2%/mo); fade AND momentum both lose = pure cost burn | placebo degenerate (SR 0); verdict clear on sign |
| ICT-03 | FAIL | corrected (entry-lookahead bug fixed): ote_BTC_h8 +34.6%/mo SR 0.90 but minYr -9.6 -> gates FAIL; ETH nodes negative | placebo p0-27 |
| ICT-04 | FAIL | mitigation retest: corrected numbers +3/-0.7/-22.7/-10.2%/mo all gate-fail (first run had entry-day lookahead, +95% phantom) | bug caught by magnitude alarm |
| ICT-05 | FAIL | confirmed turtle soup: all nodes gate-fail (best tsoup2_BTC_h5 +13%/mo but SR 0.38 DD 43 minYr -31) | ICT-01 sibling confirmed dead |
| ICT-06 | FAIL | NWOG/NDOG MR+MOM x BTC/ETH: 8 nodes, all <=0 net (best NWOG_MR_BTC +3.7%/mo SR 0.05 DD 83) | daily gap levels carry no edge |
| ICT-07 | PENDING | - | - |
| ICT-08 | PENDING | - | - |
| ICT-09 | PENDING | - | - |
| ICT-10 | PENDING | - | - |
| **VSA / Wyckoff** | | | |
| VSA-01 | PENDING | - | - |
| VSA-02 | PENDING | - | - |
| VSA-03 | PENDING | - | - |
| WCK-01 | PENDING | - | - |
| WCK-02 | PENDING | - | - |
| **Educator systems** | | | |
| MNV-01 | PENDING | - | - |
| MNV-02 | PENDING | - | - |
| STR-01 | PENDING | - | - |
| WST-01 | PENDING | - | - |
| RSH-01 | PENDING | - | - |
| BRO-01 | PENDING | - | - |
| BRO-02 | PENDING | - | - |
| ELD-01 | PENDING | - | - |
| ELD-02 | PENDING | - | - |
| **Indicator zoo** | | | |
| IND-01 | PENDING | - | - |
| IND-02 | PENDING | - | - |
| IND-03 | PENDING | - | - |
| IND-04 | PENDING | - | - |
| IND-05 | PENDING | - | - |
| IND-06 | PENDING | - | - |
| IND-07 | PENDING | - | - |
| IND-08 | PENDING | - | - |
| IND-09 | PENDING | - | - |
| IND-10 | PENDING | - | - |
| IND-11 | PENDING | - | - |
| IND-12 | PENDING | - | - |
| IND-13 | PENDING | - | - |
| IND-14 | PENDING | - | - |
| IND-15 | PENDING | - | - |
| **Quant methods** | | | |
| QNT-01 | PENDING | - | - |
| QNT-02 | PENDING | - | - |
| QNT-03 | PENDING | - | - |
| QNT-04 | PENDING | - | - |
| QNT-05 | PENDING | - | - |
| QNT-06 | PENDING | - | - |
| **Anomalies** | | | |
| ANM-01 | PENDING | - | - |
| ANM-02 | PENDING | - | - |
| ANM-03 | PENDING | - | - |
| ANM-04 | PENDING | - | - |
| ANM-05 | PENDING | - | - |
| ANM-06 | PENDING | - | - |
| **Sentiment / Macro** | | | |
| SNT-01 | PENDING | - | - |
| SNT-02 | PENDING | - | - |
| SNT-03 | PENDING | - | - |
| SNT-04 | PENDING | - | - |
| SNT-05 | PENDING | - | - |
| FG-01 | PENDING | - | - |
| FG-02 | PENDING | - | - |
| MAC-01 | PENDING | - | - |
| MAC-02 | PENDING | - | - |
| MAC-03 | PENDING | - | - |
| MAC-04 | PENDING | - | - |
| MAC-05 | PENDING | - | - |
| **Carry / Arb** | | | |
| CC-01 | PENDING | - | - |
| CC-02 | PENDING | - | - |
| CAR-03 | PENDING | - | - |
| CAR-04 | PENDING | - | - |
| PRT-01 | PENDING | - | - |
| **Book overlays & Sizing** | | | |
| REG-01 | PENDING | - | - |
| REG-02 | PENDING | - | - |
| REG-03 | PENDING | - | - |
| TM-01 | PENDING | - | - |
| TM-02 | PENDING | - | - |
| TM-03 | PENDING | - | - |
| TM-04 | PENDING | - | - |
| TM-05 | PENDING | - | - |
| TM-06 | PENDING | - | - |
| RBT-01 | PENDING | - | - |
| RBT-02 | PENDING | - | - |
| RSK-01 | PENDING | - | - |
| RSK-02 | PENDING | - | - |
| **Execution & Deployment** | | | |
| EXE-02 | PENDING | - | - |
| EXE-03 | PENDING | - | - |
| GRD-02 | PENDING | - | - |
| **Wave-2 mechanisms** | | | |
| I-07 | PENDING | - | - |
| I-08 | PENDING | - | - |
| I-09 | PENDING | - | - |
| I-10 | PENDING | - | - |
| I-12 | PENDING | - | - |
| I-13 | PENDING | - | - |
| I-14 | PENDING | - | - |
| I-16 | PENDING | - | - |
| I-17 | PENDING | - | - |
| **Options probes** | | | |
| I-19 | PENDING | - | - |
| I-20 | PENDING | - | - |
| IV-01 | PENDING | - | - |
| **Truth & Robustness** | | | |
| I-21 | PENDING | - | - |
| I-22 | PENDING | - | - |
| I-23 | PENDING | - | - |
| I-24 | PENDING | - | - |
| **Meta (endgame)** | | | |
| END-01 | PENDING | - | - |
| END-02 | PENDING | - | - |
