# Fast Pass Lab

Research into MNQ strategies that could pass a prop-firm eval quickly. The test account is a 50K eval: $3K target, $2K end-of-day trailing drawdown, and a 50% consistency rule. Every result here comes from honest fills, and each one is checked on two separate halves of the data. Paper research only.

## Layout

```
data/       NQ 5m bars from Jan 2024 to Oct 2026, and 15m bars from 2020 to 2026
lab/        data.py (loading, ATR, VWAP, daily levels), pivot_retest.py, breakout.py
```

## Findings so far (Nov 5, 2026)

### 1. Pivot Retest has no edge

The October backtest of Pivot Retest showed +0.25 to +0.38R per trade. That number came from a bug. On the bar where the limit order filled, the test counted the bar's whole range, including prices that traded before the fill. With that fixed, the strategy averages −0.23R per trade at a 2R target, and it loses in both halves of the data.

### 2. What makes a level hold or break

I faded swing pivots after a 3 ATR move and counted a level as "held" when price moved 1R away from it before hitting a 0.5 ATR stop. About 4,900 levels, both halves:

| What predicts whether a level holds | Held |
|---|---|
| All levels | 32% |
| At PDH, PDL, or the overnight high/low | 22% (major levels break more) |
| Retested during NY AM | 23% (the morning breaks levels) |
| Retested during the Asia session | 40% |
| Pivot bar had low volume | 37–39% |
| Fast return to the level | 28–31% |
| Number of prior touches, level age, wick size, round numbers | No consistent effect |

Fading still lost money in every bucket. The pattern matches Osler's (NY Fed) research on order flow: take-profit orders cluster at levels, and stop orders sit just beyond them. That's why big levels tend to break with force.

### 3. Breakouts at major levels: 5m bars can't settle it

I tested a stop-order entry 0.1 ATR beyond PDH, PDL, or the overnight high/low, with a 0.5 ATR stop.

In 91% of trades, the 5m bar that filled the entry also touched the stop. A 5m bar doesn't show which came first, so the result depends entirely on that assumption:

| Assumption on the fill bar | Avg R at a 2R target |
|---|---|
| Stop came first | about −0.8R |
| Stop came after | about +0.2 to +0.3R |

Any strategy with a stop around 10–15 points needs 1-minute (or tick) data to test honestly. With a wider 1.0 ATR stop, the result is about +0.05 to +0.10R, which is small.

### 4. SpacemanBTC Key Levels compared with random prices

`lab/key_levels.py` rebuilds the levels from SpacemanBTC's "Key Levels (IDWM)" indicator:

- Daily, weekly, monthly, quarterly, and yearly opens
- Previous highs, lows, and mids
- 4H levels
- Monday's range

For each level, the test looks at the first touch of each trading day. Starting with the bar after the touch, it asks which comes first: a move of 1 ATR back, or 1 ATR through. Every level is compared with random prices taken from the previous day, the same method Osler used.

Random levels held about 50% of the time. No key-level type beat random in both halves of the data by more than a few percentage points, which is within noise. The daily highs and lows held slightly less often than random. On their own, these levels don't predict a bounce or a break. Any edge has to come from how price reacts at the level.

### 5. Liquidity grabs (sweep and reclaim) with pivot-to-pivot targets

`lab/sweep.py` tests sweeps of PDH, PDL, the overnight high/low, and the previous 4H high/low.

**Entry:** short at the close of the bar that reclaims back below a swept high (long at the reclaim of a swept low). The sweep can be no deeper than 1.5 ATR, and the reclaim has to happen within 3 bars.

**Stop:** 1 tick past the sweep's wick.

**Targets:** 1R, 2R, 3R, or the next opposite swing pivot. In this data, the next pivot sat a median of about 4–5R away.

**Results:**

| Sweep | Avg R at 2R, first half / second half |
|---|---|
| Random prices (control) | −0.14 / −0.05 |
| All key levels combined | close to random |
| PDH | +0.20 / +0.13 (about 40% winners, n = 206) |

PDH was the only level positive in both halves, and with only 206 trades that isn't statistically meaningful. Targeting the next pivot instead of a fixed R didn't help.
