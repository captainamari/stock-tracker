"""
Momentum V3 — Signal Engine
=============================
V3 signal generation rules based on 3-year backtest validation.

Rules:
    Entry:
        Level 1: Score≥70 first time → immediate 50% position
        Level 2: Score≥65 for 3 consecutive days + 5d climb>10pt → 100% position
        False breakout filter: 5d climb <5pt = only 30% probe

    Exit (graduated):
        Yellow warning: 2 consecutive days drop>3/day → reduce 30%
        Red exit: Score breaks below 60 → reduce to 30% total
        Full sell: Score breaks 50 or 5 consecutive days <60

    Monitoring:
        Single day drop>5 = 88% probability of continuation within 3 days
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from lib.strategy.momentum_v3.core import get_regime


@dataclass
class V3Signal:
    """Detailed V3 signal output."""
    current_score: Optional[float]
    regime: str
    signals: List[str]
    position_advice: Optional[int]    # 0-100%
    urgency: str                       # CRITICAL, HIGH, MEDIUM, LOW, NONE
    delta_1d: float
    score_5d_change: Optional[float]
    consecutive_above_65: int
    consecutive_above_70: int
    consecutive_below_60: int
    consecutive_decline: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_score": self.current_score,
            "regime": self.regime,
            "signals": self.signals,
            "position_advice": self.position_advice,
            "urgency": self.urgency,
            "delta_1d": self.delta_1d,
            "score_5d_change": self.score_5d_change,
            "consecutive_above_65": self.consecutive_above_65,
            "consecutive_above_70": self.consecutive_above_70,
            "consecutive_below_60": self.consecutive_below_60,
            "consecutive_decline": self.consecutive_decline,
        }


class V3SignalEngine:
    """
    V3 Signal Engine — Entry/Exit/Hold decision maker.

    Operates on the final_scores array produced by compute_composite_momentum_v2.
    """

    def __init__(
        self,
        scores: List[Optional[float]],
        dates: List[str],
        closes: List[float],
    ):
        self.scores = scores
        self.dates = dates
        self.closes = closes
        self.n = len(scores)

    def analyze(self) -> V3Signal:
        """Run full V3 signal analysis."""
        if self.n < 10:
            return self._empty()

        # Get recent valid scores
        recent = [
            (i, self.scores[i])
            for i in range(max(0, self.n - 10), self.n)
            if self.scores[i] is not None
        ]

        if len(recent) < 3:
            return self._empty()

        current_idx, current_score = recent[-1]
        current_regime, _ = get_regime(current_score)

        # Daily deltas
        deltas = [recent[j][1] - recent[j - 1][1] for j in range(1, len(recent))]
        delta_1d = deltas[-1] if deltas else 0

        # 5-day score change
        if len(recent) >= 5:
            score_5d_change = recent[-1][1] - recent[-5][1]
        elif len(recent) >= 2:
            score_5d_change = recent[-1][1] - recent[0][1]
        else:
            score_5d_change = 0

        # Consecutive counters
        c65, c70, c60_below = 0, 0, 0
        for _, s in reversed(recent):
            if s >= 65:
                c65 += 1
            else:
                break
        for _, s in reversed(recent):
            if s >= 70:
                c70 += 1
            else:
                break
        for _, s in reversed(recent):
            if s < 60:
                c60_below += 1
            else:
                break

        # Consecutive decline days (drop > 3 per day)
        c_decline = 0
        for d in reversed(deltas):
            if d < -3:
                c_decline += 1
            else:
                break

        signals: List[str] = []
        position_advice: Optional[int] = None
        urgency = "NONE"

        # === ENTRY SIGNALS ===
        if current_score >= 70 and c70 <= 2:
            if score_5d_change > 10:
                signals.append(
                    f"🚀 Level 1 Entry (Score={current_score:.1f}, 5d climb{score_5d_change:+.1f}pt)"
                )
            else:
                signals.append(f"📈 Level 1 Entry (Score={current_score:.1f})")
            position_advice = 50
            urgency = "HIGH"

        elif current_score >= 65 and c65 >= 3 and c70 == 0:
            if score_5d_change > 10:
                signals.append(
                    f"📈 Level 2 Confirmed ({c65} days≥65, climb{score_5d_change:+.1f}pt)"
                )
                position_advice = 100
                urgency = "MEDIUM"
            elif score_5d_change < 5:
                signals.append(
                    f"⚠️ False breakout suspected (5d climb only{score_5d_change:+.1f}pt)"
                )
                position_advice = 30
                urgency = "LOW"
            else:
                signals.append(f"📈 Level 2 Confirming ({c65} days≥65)")
                position_advice = 70
                urgency = "MEDIUM"

        # === HOLD SIGNALS ===
        elif current_score >= 70 and c70 > 2:
            signals.append(f"🟢 STRONG_TREND continues ({c70} days≥70)")
            position_advice = 100
            urgency = "NONE"

        elif 60 <= current_score < 70:
            if c_decline >= 2:
                signals.append(
                    f"⚡ Yellow Warning! {c_decline} consecutive drops (today{delta_1d:+.1f})"
                )
                position_advice = 70
                urgency = "HIGH"
            elif delta_1d < -5:
                signals.append(f"⚡ Single-day crash warning! ({delta_1d:+.1f}pts)")
                position_advice = 70
                urgency = "HIGH"
            else:
                signals.append(f"🟡 STRONG hold (Score={current_score:.1f})")
                position_advice = 100
                urgency = "NONE"

        # === EXIT SIGNALS ===
        elif 40 <= current_score < 60:
            if len(recent) >= 3 and recent[-3][1] >= 65:
                signals.append(
                    f"🔴 Red Exit! Score dropped from STRONG to {current_score:.1f}"
                )
                position_advice = 30
                urgency = "CRITICAL"
            elif score_5d_change < -20:
                signals.append(f"🔴 5d crash{score_5d_change:+.1f}pt → reduce to 30%")
                position_advice = 30
                urgency = "HIGH"
            else:
                signals.append(f"⚪ NEUTRAL (Score={current_score:.1f})")
                position_advice = 50
                urgency = "LOW"

            if c60_below >= 5:
                signals.append(f"🛑 {c60_below} consecutive days<60 → FULL SELL")
                position_advice = 0
                urgency = "CRITICAL"

        elif current_score < 40:
            if score_5d_change > 5:
                signals.append(f"🔴 WEAK but recovering (5d{score_5d_change:+.1f}pt)")
                position_advice = 20
                urgency = "HIGH"
            else:
                signals.append(f"🛑 Score={current_score:.1f} WEAK → FULL SELL")
                position_advice = 0
                urgency = "CRITICAL"

        # Additional warning
        if delta_1d < -5 and current_score >= 55 and urgency != "CRITICAL":
            signals.append(f"⚠️ Single-day drop{delta_1d:+.1f}pts, 88% probability continues")

        # Fallback
        if not signals:
            signals.append(f"Score={current_score:.1f}, no new signals")
            if current_score >= 65:
                position_advice = 100
            elif current_score >= 40:
                position_advice = 50
            else:
                position_advice = 0

        return V3Signal(
            current_score=current_score,
            regime=current_regime,
            signals=signals,
            position_advice=position_advice,
            urgency=urgency,
            delta_1d=delta_1d,
            score_5d_change=score_5d_change,
            consecutive_above_65=c65,
            consecutive_above_70=c70,
            consecutive_below_60=c60_below,
            consecutive_decline=c_decline,
        )

    def _empty(self) -> V3Signal:
        return V3Signal(
            current_score=None,
            regime="N/A",
            signals=["❌ Insufficient data"],
            position_advice=None,
            urgency="NONE",
            delta_1d=0,
            score_5d_change=None,
            consecutive_above_65=0,
            consecutive_above_70=0,
            consecutive_below_60=0,
            consecutive_decline=0,
        )
