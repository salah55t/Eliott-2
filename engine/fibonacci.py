"""
engine/fibonacci.py
-------------------
Fibonacci Math Utility for the Elliott Wave Validation Engine.

Provides two complementary tools:

  FibonacciLevels  — a single-instance calculator that computes retracement
                     and extension price levels given a swing's start/end.

  FibonacciChecker — a stateless validator that answers whether a given
                     price is NEAR one of the canonical Fib levels, within
                     a configurable percentage tolerance (default ±0.5%).

Canonical levels sourced directly from course notes (pages 9-12):
  Retracement : 0.236, 0.382, 0.500, 0.618, 0.786, 0.886
  Extension   : 1.000, 1.272, 1.414, 1.618, 2.000, 2.272, 2.618, 3.272, 3.414

  * = "preferred" / high-probability zones marked in the notes:
        Wave 2 key zone  → 0.382, 0.500, 0.618  (starred on p.11)
        Wave 3 key zone  → 1.618, 2.618          (starred on p.11)
        Wave 4 key zone  → 0.236, 0.382          (starred on p.10)
        Wave 5 targets   → 0.382, 0.500, 0.618 of W1 length (p.12-13)

Usage
-----
    from engine.fibonacci import FibonacciLevels, FibonacciChecker

    # --- Retracement (e.g. Wave 2 pullback off Wave 1) ---
    fib = FibonacciLevels(swing_start=10_000, swing_end=15_000)
    levels = fib.retracement_levels()
    # {'0.236': 13820.0, '0.382': 13090.0, ...}

    # --- Extension (e.g. Wave 3 projection off Wave 2 low) ---
    ext = fib.extension_levels()
    # {'1.618': 23090.0, '2.618': 31090.0, ...}

    # --- Is a price "at" a fib level? ---
    checker = FibonacciChecker(fib)
    result  = checker.is_at_retracement(13_100, tolerance_pct=0.5)
    # FibHitResult(hit=True, nearest_ratio=0.382, price=13090.0, deviation_pct=0.076)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

log = get_logger(__name__)


# ── Canonical Fibonacci Ratios ─────────────────────────────────────────────────

#: Retracement ratios — used for Wave 2 and Wave 4 entry zones.
#: Source: course notes pages 9-11.
RETRACEMENT_RATIOS: Tuple[float, ...] = (
    0.236, 0.382, 0.500, 0.618, 0.786, 0.886
)

#: Extension ratios — used for Wave 3 and Wave 5 targets.
#: Source: course notes pages 11-13.
EXTENSION_RATIOS: Tuple[float, ...] = (
    1.000, 1.272, 1.414, 1.618, 2.000, 2.272, 2.618, 3.272, 3.414
)

#: High-probability Wave 2 retracement zone (starred in notes p.11).
WAVE2_KEY_RATIOS: Tuple[float, ...] = (0.382, 0.500, 0.618)

#: High-probability Wave 3 extension zone (starred in notes p.11).
WAVE3_KEY_RATIOS: Tuple[float, ...] = (1.618, 2.618)

#: High-probability Wave 4 retracement zone (starred in notes p.10).
WAVE4_KEY_RATIOS: Tuple[float, ...] = (0.236, 0.382)

#: Wave 5 projection ratios measured against Wave 1 length (notes p.12-13).
WAVE5_TARGET_RATIOS: Tuple[float, ...] = (0.382, 0.500, 0.618)


# ── Data containers ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FibLevel:
    """A single computed Fibonacci price level."""
    ratio:  float   #: The Fib ratio, e.g. 0.618
    price:  float   #: The actual price at that ratio
    label:  str     #: Human-readable label, e.g. "0.618"
    is_key: bool    #: True when this ratio is in the "starred" / key set


@dataclass(frozen=True)
class FibHitResult:
    """Result returned by FibonacciChecker proximity tests."""
    hit:             bool           #: True when price is within tolerance
    nearest_ratio:   float          #: Closest Fib ratio found
    nearest_price:   float          #: Price at that nearest ratio
    deviation_pct:   float          #: Percentage distance from nearest level
    tolerance_pct:   float          #: Tolerance threshold that was applied


# ── FibonacciLevels ────────────────────────────────────────────────────────────

class FibonacciLevels:
    """
    Computes retracement and extension price levels for a given price swing.

    A "swing" is defined by two endpoints:
      * swing_start : origin of the measured move  (e.g. Wave 1 low / P0)
      * swing_end   : terminus of the measured move (e.g. Wave 1 high / P1)

    The direction (bullish / bearish) is inferred automatically from the sign
    of (swing_end - swing_start).

    Parameters
    ----------
    swing_start : float
        Price at the beginning of the reference swing.
    swing_end : float
        Price at the end of the reference swing.

    Raises
    ------
    ValueError
        If swing_start == swing_end (zero-length swing — undefined ratios).
    """

    def __init__(self, swing_start: float, swing_end: float) -> None:
        if math.isclose(swing_start, swing_end, rel_tol=1e-9):
            raise ValueError(
                f"swing_start ({swing_start}) and swing_end ({swing_end}) "
                "must not be equal — cannot compute ratios for a zero-length swing."
            )
        self.swing_start: float = float(swing_start)
        self.swing_end:   float = float(swing_end)
        self._range:      float = swing_end - swing_start   # signed
        self.is_bullish:  bool  = self._range > 0

        log.debug(
            "FibonacciLevels created: start=%.4f  end=%.4f  range=%.4f  "
            "direction=%s",
            self.swing_start, self.swing_end, self._range,
            "BULL" if self.is_bullish else "BEAR",
        )

    # ── Retracement ───────────────────────────────────────────────────────────

    def retracement_levels(
        self,
        ratios: Optional[Tuple[float, ...]] = None,
        key_ratios: Optional[Tuple[float, ...]] = WAVE2_KEY_RATIOS,
    ) -> List[FibLevel]:
        """
        Return retracement price levels for each ratio in *ratios*.

        Retracement prices are measured *back against* the swing direction:
          price = swing_end - ratio × range         (bullish swing)
          price = swing_end + ratio × |range|       (bearish swing — same formula
                                                     because range is negative)

        In practice, the formula is simply:
          price = swing_end - ratio × (swing_end - swing_start)

        Parameters
        ----------
        ratios    : Ratios to compute. Defaults to RETRACEMENT_RATIOS.
        key_ratios: Subset of ratios considered "key" (for is_key flag).

        Returns
        -------
        List[FibLevel] sorted by ratio ascending.
        """
        ratios     = ratios or RETRACEMENT_RATIOS
        key_ratios = key_ratios or ()

        levels = [
            FibLevel(
                ratio=r,
                price=round(self.swing_end - r * self._range, 8),
                label=str(r),
                is_key=(r in key_ratios),
            )
            for r in ratios
        ]
        log.debug(
            "Retracement levels for swing [%.4f → %.4f]: %s",
            self.swing_start, self.swing_end,
            {lv.label: lv.price for lv in levels},
        )
        return sorted(levels, key=lambda lv: lv.ratio)

    def retracement_dict(
        self,
        ratios: Optional[Tuple[float, ...]] = None,
    ) -> Dict[str, float]:
        """
        Convenience wrapper — returns ``{ratio_label: price}`` dict.

        Example
        -------
        >>> fib.retracement_dict()
        {'0.236': 13820.0, '0.382': 13090.0, '0.5': 12500.0, ...}
        """
        return {lv.label: lv.price for lv in self.retracement_levels(ratios)}

    # ── Extension ─────────────────────────────────────────────────────────────

    def extension_levels(
        self,
        ratios: Optional[Tuple[float, ...]] = None,
        key_ratios: Optional[Tuple[float, ...]] = WAVE3_KEY_RATIOS,
        base_price: Optional[float] = None,
    ) -> List[FibLevel]:
        """
        Return extension price levels for each ratio in *ratios*.

        Extension prices project *beyond* the swing end from a base price:
          price = base_price + ratio × |range|

        For Elliott Wave usage:
          * Wave 3 target : base = Wave 2 low  (P2),   range = Wave 1 length
          * Wave 5 target : base = Wave 4 low  (P4),   range = Wave 1 length
          * Zigzag Wave C : base = Wave B high (P_b),  range = Wave A length

        Parameters
        ----------
        ratios     : Ratios to compute. Defaults to EXTENSION_RATIOS.
        key_ratios : Subset of ratios considered "key" (for is_key flag).
        base_price : Starting price for the extension projection. Defaults
                     to swing_start (which equals the corrective low / P2
                     when called after a retracement).

        Returns
        -------
        List[FibLevel] sorted by ratio ascending.
        """
        ratios     = ratios or EXTENSION_RATIOS
        key_ratios = key_ratios or ()
        base       = base_price if base_price is not None else self.swing_start
        move_len   = abs(self._range)   # always positive for extension math

        # Direction: extensions project in the same direction as the swing
        sign = 1.0 if self.is_bullish else -1.0

        levels = [
            FibLevel(
                ratio=r,
                price=round(base + sign * r * move_len, 8),
                label=str(r),
                is_key=(r in key_ratios),
            )
            for r in ratios
        ]
        log.debug(
            "Extension levels for swing [%.4f → %.4f] from base=%.4f: %s",
            self.swing_start, self.swing_end, base,
            {lv.label: lv.price for lv in levels},
        )
        return sorted(levels, key=lambda lv: lv.ratio)

    def extension_dict(
        self,
        ratios: Optional[Tuple[float, ...]] = None,
        base_price: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        Convenience wrapper — returns ``{ratio_label: price}`` dict.

        Example
        -------
        >>> fib.extension_dict()
        {'1.618': 23090.0, '2.0': 25000.0, '2.618': 28090.0, ...}
        """
        return {
            lv.label: lv.price
            for lv in self.extension_levels(ratios, base_price=base_price)
        }

    # ── Wave-specific convenience methods ─────────────────────────────────────

    def wave3_targets(self, wave2_low: float) -> List[FibLevel]:
        """
        Return Wave 3 price targets projected from *wave2_low*.

        Uses WAVE3_KEY_RATIOS (1.618, 2.618) as the starred / key levels.
        Full set: 1.000, 1.272, 1.414, 1.618, 2.000, 2.272, 2.618, 3.272, 3.414

        Parameters
        ----------
        wave2_low : float
            The corrective low of Wave 2 (= P2, the base of the Wave 3 launch).
        """
        return self.extension_levels(
            ratios=EXTENSION_RATIOS,
            key_ratios=WAVE3_KEY_RATIOS,
            base_price=wave2_low,
        )

    def wave4_retracement_zone(self) -> Tuple[float, float]:
        """
        Return the Wave 4 high-probability retracement zone as a (low, high) tuple.

        Zone: 23.6%–38.2% of the Wave 3 move (starred in course notes p.10).
        The caller should pass the Wave 3 swing (P2 → P3) as swing_start/end.

        Returns
        -------
        Tuple[float, float]  — (price_at_0.382, price_at_0.236)
                               i.e. (deeper end, shallower end) for a bull swing.
        """
        d = self.retracement_dict(ratios=WAVE4_KEY_RATIOS)
        prices = sorted(d.values())
        return (prices[0], prices[-1])   # (lower price, higher price)

    def wave5_targets(self, wave4_low: float) -> List[FibLevel]:
        """
        Return Wave 5 price targets projected from *wave4_low*.

        Uses WAVE5_TARGET_RATIOS (0.382, 0.500, 0.618 of W1 length).
        Source: course notes page 12-13.

        Parameters
        ----------
        wave4_low : float
            The corrective low of Wave 4 (= P4, the base of the Wave 5 launch).
        """
        return self.extension_levels(
            ratios=WAVE5_TARGET_RATIOS,
            key_ratios=WAVE5_TARGET_RATIOS,
            base_price=wave4_low,
        )

    # ── Utility ───────────────────────────────────────────────────────────────

    @property
    def swing_length(self) -> float:
        """Absolute price length of the measured swing."""
        return abs(self._range)

    def __repr__(self) -> str:  # pragma: no cover
        direction = "↑" if self.is_bullish else "↓"
        return (
            f"FibonacciLevels({direction} "
            f"start={self.swing_start:.4f} "
            f"end={self.swing_end:.4f} "
            f"range={self._range:.4f})"
        )


# ── FibonacciChecker ───────────────────────────────────────────────────────────

class FibonacciChecker:
    """
    Stateless proximity validator: given a FibonacciLevels instance,
    answers "is a price at / near a Fibonacci level?"

    Used by the Wave Validator to confirm that pivot points land inside
    expected retracement or extension zones.

    Parameters
    ----------
    fib : FibonacciLevels
        A pre-configured FibonacciLevels instance for the reference swing.
    default_tolerance_pct : float
        Default percentage tolerance for proximity checks (default 0.5 = ±0.5%).
    """

    def __init__(
        self,
        fib: FibonacciLevels,
        default_tolerance_pct: float = 0.5,
    ) -> None:
        self.fib = fib
        self.default_tolerance_pct = default_tolerance_pct

    # ── Public API ─────────────────────────────────────────────────────────

    def is_at_retracement(
        self,
        price: float,
        ratios: Optional[Tuple[float, ...]] = None,
        tolerance_pct: Optional[float] = None,
    ) -> FibHitResult:
        """
        Return whether *price* is within *tolerance_pct* of any retracement level.

        Parameters
        ----------
        price          : The price to test (e.g. P2 close price).
        ratios         : Subset of retracement ratios to check.
                         Defaults to RETRACEMENT_RATIOS.
        tolerance_pct  : Percentage window. Default = self.default_tolerance_pct.
        """
        levels = self.fib.retracement_levels(ratios)
        return self._nearest_hit(price, levels, tolerance_pct)

    def is_at_extension(
        self,
        price: float,
        ratios: Optional[Tuple[float, ...]] = None,
        tolerance_pct: Optional[float] = None,
        base_price: Optional[float] = None,
    ) -> FibHitResult:
        """
        Return whether *price* is within *tolerance_pct* of any extension level.

        Parameters
        ----------
        price          : The price to test (e.g. P3 high for a Wave 3 target).
        ratios         : Subset of extension ratios to check.
        tolerance_pct  : Percentage window. Default = self.default_tolerance_pct.
        base_price     : Base for extensions (see FibonacciLevels.extension_levels).
        """
        levels = self.fib.extension_levels(ratios, base_price=base_price)
        return self._nearest_hit(price, levels, tolerance_pct)

    def nearest_retracement(self, price: float) -> FibLevel:
        """Return the retracement FibLevel whose price is closest to *price*."""
        levels = self.fib.retracement_levels()
        return min(levels, key=lambda lv: abs(lv.price - price))

    def nearest_extension(
        self,
        price: float,
        base_price: Optional[float] = None,
    ) -> FibLevel:
        """Return the extension FibLevel whose price is closest to *price*."""
        levels = self.fib.extension_levels(base_price=base_price)
        return min(levels, key=lambda lv: abs(lv.price - price))

    def retracement_pct(self, price: float) -> float:
        """
        Return the actual retracement percentage of *price* within the swing.

        0.0 = at swing_end  (no retracement)
        1.0 = at swing_start (full retracement / 100%)

        Example
        -------
        swing 10_000 → 15_000;  price 13_090  → ≈ 38.2% retracement
        """
        if math.isclose(self.fib.swing_length, 0.0, rel_tol=1e-9):
            return 0.0
        retrace = (self.fib.swing_end - price) / self.fib._range
        return round(retrace, 6)

    # ── Internal ──────────────────────────────────────────────────────────

    def _nearest_hit(
        self,
        price: float,
        levels: List[FibLevel],
        tolerance_pct: Optional[float],
    ) -> FibHitResult:
        """Find the closest level and decide whether it qualifies as a 'hit'."""
        tol = tolerance_pct if tolerance_pct is not None else self.default_tolerance_pct

        nearest = min(levels, key=lambda lv: abs(lv.price - price))
        deviation_pct = (
            abs(price - nearest.price) / nearest.price * 100.0
            if not math.isclose(nearest.price, 0.0, abs_tol=1e-9)
            else float("inf")
        )
        hit = deviation_pct <= tol

        log.debug(
            "Fib proximity check: price=%.4f  nearest=%s @ %.4f  "
            "deviation=%.3f%%  tol=%.2f%%  hit=%s",
            price, nearest.label, nearest.price, deviation_pct, tol, hit,
        )
        return FibHitResult(
            hit=hit,
            nearest_ratio=nearest.ratio,
            nearest_price=nearest.price,
            deviation_pct=round(deviation_pct, 4),
            tolerance_pct=tol,
        )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"FibonacciChecker(fib={self.fib!r}, "
            f"tol={self.default_tolerance_pct}%)"
        )
