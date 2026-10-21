"""
engine/pattern_detector.py
--------------------------
Layer 2 (Bridge) — Pattern Detector

This module is the bridge between the OHLCV DataFrames produced by Layer 1
(``data/ingestion.py``) and the wave validation rules in Layer 2
(``engine/wave_validator.py``).

Responsibilities
----------------
1. Reduce raw OHLCV candle data to a compact list of significant pivot points
   (local highs and lows) using a configurable noise-filtering algorithm.
2. Walk through consecutive 6-point windows of pivots and test each one
   against the Elliott Wave impulse rules via ``validate_impulse()``.
3. Return structured results for every window that passes all three hard rules.

Pivot Detection Algorithms
--------------------------
Two complementary algorithms are provided. You can select between them via
the ``method`` parameter of ``PivotDetector``.  For most use cases, start
with ``"zigzag"`` and tune ``deviation_threshold``.

  "zigzag" (default)  ─ Percentage-Reversion ZigZag
  ──────────────────────────────────────────────────
  The classic ZigZag approach used by traders.  A pivot is only confirmed
  once price has reversed by at least ``deviation_threshold`` percent from
  the previous extreme.

  Pros  : Direction-aware; naturally enforces strict peak/trough alternation;
          closely mirrors how traders visually draw swings; handles trends
          and ranges equally well.
  Cons  : One free parameter only (the deviation %); not look-ahead free
          (the last unconfirmed pivot updates until confirmed).
  Tune  : Raise ``deviation_threshold`` on noisy/choppy data.  Lower it on
          smooth trending markets to catch smaller waves.

  "window" ─ Rolling Window Local Extrema (scipy.signal.find_peaks)
  ─────────────────────────────────────────────────────────────────
  Identifies local maxima/minima within a symmetric window of ±``window_size``
  bars using scipy's ``find_peaks`` with configurable ``prominence``.

  Pros  : Symmetric look-ahead; no sequential bias; prominence filter
          removes minor wiggles very cleanly.
  Cons  : Requires two free parameters (window_size + prominence); may miss
          the first/last pivot near the data edges; look-ahead is real — the
          last ``window_size`` bars never produce a confirmed pivot.
  Tune  : Increase ``window_size`` to filter more noise.  Increase
          ``prominence_pct`` to require larger swings.

Parameter Tuning Guide
----------------------
Timeframe    | deviation_threshold | window_size | Notes
-------------|--------------------:|------------:|-------------------------------
1m           | 0.008 – 0.012       | 5 – 7       | Very noisy; start conservative
5m           | 0.006 – 0.010       | 5           | Standard scalp
15m          | 0.004 – 0.008       | 5           | Primary entry TF for this bot
1h           | 0.003 – 0.006       | 3 – 5       | Signal confirmation TF
4h           | 0.002 – 0.005       | 3           | Swing / position TF
1d           | 0.015 – 0.030       | 3           | Position trading

General rule: if you are getting too many false signals → raise the threshold.
If valid wave structures are being missed → lower the threshold.

Output Schema
-------------
Each valid setup is returned as a ``DetectedSetup`` dataclass:

  symbol            : str               — e.g. "BTC/USDT"
  timeframe         : str               — e.g. "1h"
  direction         : str               — "BULLISH" or "BEARISH"
  pivot_indices     : List[int]         — DataFrame row indices of P0–P5
  pivot_timestamps  : List[pd.Timestamp]— UTC timestamps of P0–P5
  pivot_prices      : List[float]       — Closing prices of P0–P5 [P0…P5]
  validation_result : ValidationResult  — Full result from WaveValidator
  detected_at       : pd.Timestamp      — Timestamp of the last candle (P5)

Usage
-----
    from data.ingestion import build_ingestion
    from engine.pattern_detector import PivotDetector, DetectorConfig

    di  = build_ingestion()
    df  = di.fetch_ohlcv("BTC/USDT", "1h", limit=500)

    cfg = DetectorConfig(deviation_threshold=0.04, method="zigzag")
    det = PivotDetector(cfg)

    setups = det.scan(df)
    for s in setups:
        print(s.summary())
        print()

    # Or use the one-liner:
    from engine.pattern_detector import scan_for_impulses
    setups = scan_for_impulses(df, deviation_threshold=0.04)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from engine.wave_validator import ValidationResult, validate_impulse
from utils.logger import get_logger

log = get_logger(__name__)

# ── Type aliases ───────────────────────────────────────────────────────────────
PivotType   = Literal["peak", "trough"]
MethodType  = Literal["zigzag", "window"]

# ── Internal pivot representation ─────────────────────────────────────────────

@dataclass(frozen=True)
class Pivot:
    """
    A single confirmed pivot point extracted from an OHLCV DataFrame.

    Attributes
    ----------
    bar_index   : Integer position in the source DataFrame (iloc index).
    timestamp   : UTC open-time of the candle at this pivot.
    price       : Pivot price — high for peaks, low for troughs.
    pivot_type  : "peak" (local high) or "trough" (local low).
    """
    bar_index  : int
    timestamp  : pd.Timestamp
    price      : float
    pivot_type : PivotType

    @property
    def is_peak(self) -> bool:
        return self.pivot_type == "peak"

    @property
    def is_trough(self) -> bool:
        return self.pivot_type == "trough"

    def __repr__(self) -> str:  # pragma: no cover
        symbol = "^" if self.is_peak else "v"
        return (
            f"Pivot({symbol} idx={self.bar_index} "
            f"ts={self.timestamp.isoformat()[:16]} "
            f"price={self.price:.4f})"
        )


# ── Configuration dataclass ────────────────────────────────────────────────────

@dataclass
class DetectorConfig:
    """
    Configuration for ``PivotDetector``.

    Parameters
    ----------
    method : "zigzag" | "window"
        Which detection algorithm to use (see module docstring).
        Default: "zigzag".

    deviation_threshold : float
        [ZigZag only] Minimum percentage reversion required to confirm a
        new pivot.  Expressed as a decimal: 0.03 = 3%.
        Default: 0.03 (3%).

    window_size : int
        [Window only] Number of bars on *each side* of a candidate bar that
        must be lower (for peaks) or higher (for troughs) to confirm the pivot.
        E.g. window_size=3 means the bar must be the highest in a 7-bar window.
        Default: 5.

    prominence_pct : float
        [Window only] Minimum prominence as a fraction of the *median* price
        in the series.  Prevents micro-fluctuations from registering as pivots.
        E.g. 0.005 = 0.5% of the median price.
        Default: 0.005 (0.5%).

    price_source : "close" | "hl" | "hlc3"
        Which price series to use for pivot detection.

        "close"  — Uses the Close price only.  Cleanest signal; ignores wicks.
                   Best for most EW analysis.
        "hl"     — Uses High for peak detection and Low for trough detection.
                   Captures intra-bar extremes; more pivots, more noise.
        "hlc3"   — Uses (H+L+C)/3 (typical price).  A compromise.

        Default: "close".

    min_wave_bars : int
        Minimum number of candles that must separate two consecutive pivots.
        Prevents detecting waves that are unrealistically short in time.
        Default: 2.

    require_fib_confluence : bool
        If True, only return setups where Wave 2 AND Wave 4 also land near
        a Fibonacci retracement level (within ``fib_tolerance_pct``).
        This is an additional filter on top of the three hard rules.
        Default: False (return all valid impulses regardless of fib zones).

    fib_tolerance_pct : float
        Percentage tolerance for Fibonacci confluence check.
        Only used when ``require_fib_confluence=True``.
        Default: 1.0 (±1.0%).
    """

    method               : MethodType = "zigzag"
    deviation_threshold  : float      = 0.03
    window_size          : int        = 5
    prominence_pct       : float      = 0.005
    price_source         : Literal["close", "hl", "hlc3"] = "close"
    min_wave_bars        : int        = 2
    require_fib_confluence: bool      = False
    fib_tolerance_pct    : float      = 1.0
    # [FE1.6.0] أرضية التناسب للأمواج الدافعة (اقتباس ElliottWavesEngine
    # MinMotiveWaveProportion=0.15): كل موجة دافعة ≥ 15% من الحركة الأمومية
    # لوغاريتميًا. 0 يعطل القاعدة الرابعة.
    min_wave_proportion  : float      = 0.15

    def __post_init__(self) -> None:
        if self.deviation_threshold <= 0:
            raise ValueError(
                f"deviation_threshold must be > 0, got {self.deviation_threshold}"
            )
        if self.window_size < 1:
            raise ValueError(
                f"window_size must be >= 1, got {self.window_size}"
            )
        if self.prominence_pct < 0:
            raise ValueError(
                f"prominence_pct must be >= 0, got {self.prominence_pct}"
            )
        if self.min_wave_bars < 1:
            raise ValueError(
                f"min_wave_bars must be >= 1, got {self.min_wave_bars}"
            )
        if self.method not in ("zigzag", "window"):
            raise ValueError(
                f"method must be 'zigzag' or 'window', got '{self.method}'"
            )
        if self.price_source not in ("close", "hl", "hlc3"):
            raise ValueError(
                f"price_source must be 'close', 'hl', or 'hlc3', "
                f"got '{self.price_source}'"
            )
        if not (0.0 <= self.min_wave_proportion <= 1.0):
            raise ValueError(
                f"min_wave_proportion must be within [0, 1], "
                f"got {self.min_wave_proportion}"
            )


# ── Output dataclass ───────────────────────────────────────────────────────────

@dataclass
class DetectedSetup:
    """
    A validated Elliott Wave impulse setup identified in an OHLCV DataFrame.

    Attributes
    ----------
    symbol             : Trading pair (from the DataFrame metadata column).
    timeframe          : Candle period (from the DataFrame metadata column).
    direction          : "BULLISH" or "BEARISH".
    pivot_indices      : DataFrame integer positions (iloc) for P0–P5.
    pivot_timestamps   : UTC open-time for each pivot candle.
    pivot_prices       : Detected pivot prices [P0, P1, P2, P3, P4, P5].
    validation_result  : Full ``ValidationResult`` from ``WaveValidator``.
    detected_at        : Timestamp of the final confirmed candle (P5).
    pivot_objects      : The raw ``Pivot`` dataclasses for advanced use.
    """

    symbol            : str
    timeframe         : str
    direction         : str                   # "BULLISH" | "BEARISH"
    pivot_indices     : List[int]             # [bar_idx_P0, …, bar_idx_P5]
    pivot_timestamps  : List[pd.Timestamp]    # [ts_P0, …, ts_P5]
    pivot_prices      : List[float]           # [P0, P1, P2, P3, P4, P5]
    validation_result : ValidationResult
    detected_at       : pd.Timestamp
    pivot_objects     : List[Pivot] = field(default_factory=list)

    # ── Convenience accessors ──────────────────────────────────────────────

    @property
    def entry_zone_low(self) -> float:
        """
        Lower bound of the Wave 4/5 entry zone.
        The Fibonacci conformance on Wave 4 gives us the retracement zone.
        If fib data is available, returns the 38.2% level of Wave 3.
        Falls back to P4 price as a conservative entry reference.
        """
        if self.validation_result.fib:
            p2, p3 = self.pivot_prices[2], self.pivot_prices[3]
            w3_len = abs(p3 - p2)
            if self.direction == "BULLISH":
                return p3 - 0.382 * w3_len
            else:
                return p3 + 0.382 * w3_len
        return self.pivot_prices[4]

    @property
    def entry_zone_high(self) -> float:
        """Upper bound of the Wave 4/5 entry zone (23.6% retrace of Wave 3)."""
        if self.validation_result.fib:
            p2, p3 = self.pivot_prices[2], self.pivot_prices[3]
            w3_len = abs(p3 - p2)
            if self.direction == "BULLISH":
                return p3 - 0.236 * w3_len
            else:
                return p3 + 0.236 * w3_len
        return self.pivot_prices[3]

    @property
    def stop_loss_price(self) -> float:
        """
        Structural stop loss: just beyond P0 (Wave 1 origin).
        A close beyond this level invalidates the entire impulse count.
        """
        if self.direction == "BULLISH":
            return self.pivot_prices[0] * 0.999   # 0.1% buffer below P0
        else:
            return self.pivot_prices[0] * 1.001   # 0.1% buffer above P0

    @property
    def fib_w2_retrace_pct(self) -> Optional[float]:
        """Wave 2 retracement percentage, if Fibonacci data is available."""
        if self.validation_result.fib:
            return self.validation_result.fib.wave2_retrace_pct
        return None

    @property
    def fib_w4_retrace_pct(self) -> Optional[float]:
        """Wave 4 retracement percentage, if Fibonacci data is available."""
        if self.validation_result.fib:
            return self.validation_result.fib.wave4_retrace_pct
        return None

    # ── Reporting ──────────────────────────────────────────────────────────

    def summary(self) -> str:
        """
        Human-readable one-page summary of the detected setup.
        Intended for logging and console display.
        """
        w2_pct = (
            f"{self.fib_w2_retrace_pct * 100:.1f}%"
            if self.fib_w2_retrace_pct is not None else "N/A"
        )
        w4_pct = (
            f"{self.fib_w4_retrace_pct * 100:.1f}%"
            if self.fib_w4_retrace_pct is not None else "N/A"
        )
        pv = self.pivot_prices

        lines = [
            "╔" + "═" * 58 + "╗",
            f"║  DETECTED IMPULSE  [{self.direction}]  {self.symbol} {self.timeframe}",
            f"║  Detected at : {self.detected_at.isoformat()[:19]} UTC",
            "╠" + "═" * 58 + "╣",
            f"║  P0={pv[0]:<10.4f}  P1={pv[1]:<10.4f}  P2={pv[2]:<10.4f}",
            f"║  P3={pv[3]:<10.4f}  P4={pv[4]:<10.4f}  P5={pv[5]:<10.4f}",
            "╠" + "═" * 58 + "╣",
            f"║  W1={abs(pv[1]-pv[0]):.4f}  "
            f"W3={abs(pv[3]-pv[2]):.4f}  "
            f"W5={abs(pv[5]-pv[4]):.4f}",
            f"║  W2 retrace={w2_pct}   W4 retrace={w4_pct}",
            "╠" + "═" * 58 + "╣",
            f"║  Entry zone : {self.entry_zone_low:.4f} – {self.entry_zone_high:.4f}",
            f"║  Stop loss  : {self.stop_loss_price:.4f}",
            "╠" + "═" * 58 + "╣",
        ]
        # Append the compact rule summary
        for rule in self.validation_result.rules.values():
            status = "PASS" if rule.passed else "FAIL"
            lines.append(f"║  [{status}] {rule.rule_name}")
        lines.append("╚" + "═" * 58 + "╝")
        return "\n".join(lines)


# ── PivotDetector ──────────────────────────────────────────────────────────────

class PivotDetector:
    """
    Detects Elliott Wave impulse setups in a pandas OHLCV DataFrame.

    This class orchestrates:
      1. Price series extraction from the DataFrame.
      2. Pivot detection via the configured algorithm.
      3. Pivot alternation enforcement.
      4. Minimum wave-bar filtering.
      5. 6-point window enumeration.
      6. Directional signature filtering.
      7. Validation via ``WaveValidator.is_valid_impulse()``.
      8. Optional Fibonacci confluence filtering.

    Parameters
    ----------
    config : DetectorConfig
        Configuration dataclass (see ``DetectorConfig`` docstring for all options).
        If ``None``, uses default settings (ZigZag 3%, close price).

    Examples
    --------
    Basic scan with defaults:

        from engine.pattern_detector import PivotDetector
        detector = PivotDetector()
        setups = detector.scan(df_1h)

    Aggressive noise filtering for choppy 15m data:

        from engine.pattern_detector import PivotDetector, DetectorConfig
        cfg  = DetectorConfig(
            method="zigzag",
            deviation_threshold=0.06,   # 6% swing required
            price_source="close",
            require_fib_confluence=True,
            fib_tolerance_pct=1.5,
        )
        det = PivotDetector(cfg)
        setups = det.scan(df_15m)

    Window method for cleaner swing identification on 4h:

        cfg = DetectorConfig(
            method="window",
            window_size=5,
            prominence_pct=0.008,
        )
    """

    # Required columns from the Layer 1 DataFrame
    _REQUIRED_COLS: Tuple[str, ...] = (
        "timestamp", "open", "high", "low", "close", "volume"
    )

    def __init__(self, config: Optional[DetectorConfig] = None) -> None:
        self.cfg = config or DetectorConfig()
        log.debug("PivotDetector initialised: %s", self.cfg)

    # ═══════════════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════════════

    def scan(self, df: pd.DataFrame) -> List[DetectedSetup]:
        """
        Scan an OHLCV DataFrame for valid Elliott Wave impulse setups.

        Steps
        -----
        1. Validate the input DataFrame.
        2. Extract the price series (based on ``price_source``).
        3. Detect pivot points via the configured algorithm.
        4. Enforce strict peak/trough alternation.
        5. Filter pivots by minimum inter-pivot bar distance.
        6. Enumerate all 6-point windows and test each directional signature.
        7. Pass candidates to ``WaveValidator`` and collect valid setups.

        Parameters
        ----------
        df : pd.DataFrame
            A DataFrame produced by ``DataIngestion.fetch_ohlcv()``.
            Must contain columns: timestamp, open, high, low, close, volume.

        Returns
        -------
        List[DetectedSetup]
            One entry per valid 5-wave impulse found, ordered by detection time
            (i.e. by the timestamp of P5).  Empty list if none found.
        """
        self._validate_dataframe(df)

        symbol    = str(df["symbol"].iloc[0])   if "symbol"    in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "UNKNOWN"

        log.info(
            "Scanning %d candles of %s %s (method=%s threshold=%.2f%%)",
            len(df), symbol, timeframe,
            self.cfg.method, self.cfg.deviation_threshold * 100,
        )

        # ── Step 1: Extract price series ────────────────────────────────────
        prices_close, prices_high, prices_low = self._extract_price_series(df)

        # ── Step 2: Detect raw pivots ────────────────────────────────────────
        if self.cfg.method == "zigzag":
            raw_pivots = self._detect_pivots_zigzag(
                prices_close, prices_high, prices_low
            )
        else:
            raw_pivots = self._detect_pivots_window(
                prices_close, prices_high, prices_low
            )

        log.debug("Raw pivots detected: %d", len(raw_pivots))

        # ── Step 3: Enforce strict alternation ──────────────────────────────
        pivots = self._enforce_alternation(raw_pivots, prices_high, prices_low)

        # ── Step 4: Filter by minimum wave bars ─────────────────────────────
        pivots = self._filter_min_wave_bars(pivots)

        log.info(
            "Pivots after alternation + min-bar filter: %d  "
            "(need ≥ 6 for a complete impulse)",
            len(pivots),
        )

        if len(pivots) < 6:
            log.info(
                "Not enough pivots (%d) to form a 6-point window. "
                "Try lowering deviation_threshold or fetching more data.",
                len(pivots),
            )
            return []

        # ── Step 5: Enumerate 6-point windows and validate ───────────────────
        setups = self._enumerate_windows(pivots, df, symbol, timeframe)

        log.info(
            "Scan complete: %d valid impulse setup(s) found in %s %s.",
            len(setups), symbol, timeframe,
        )
        return setups

    def get_pivots(self, df: pd.DataFrame) -> List[Pivot]:
        """
        Return only the detected + filtered pivot list without running validation.

        Useful for visualisation or debugging the detection parameters
        before committing to a full scan.

        Parameters
        ----------
        df : pd.DataFrame  — OHLCV DataFrame from Layer 1.

        Returns
        -------
        List[Pivot]  — Alternating peak/trough sequence, chronologically ordered.
        """
        self._validate_dataframe(df)
        prices_close, prices_high, prices_low = self._extract_price_series(df)

        if self.cfg.method == "zigzag":
            raw = self._detect_pivots_zigzag(prices_close, prices_high, prices_low)
        else:
            raw = self._detect_pivots_window(prices_close, prices_high, prices_low)

        pivots = self._enforce_alternation(raw, prices_high, prices_low)
        pivots = self._filter_min_wave_bars(pivots)
        return pivots

    # ═══════════════════════════════════════════════════════════════════════
    # Step 1 — DataFrame validation
    # ═══════════════════════════════════════════════════════════════════════

    def _validate_dataframe(self, df: pd.DataFrame) -> None:
        """Raise ValueError if the DataFrame does not meet Layer 1 contract."""
        if not isinstance(df, pd.DataFrame):
            raise TypeError(f"Expected pd.DataFrame, got {type(df).__name__}")

        missing = [c for c in self._REQUIRED_COLS if c not in df.columns]
        if missing:
            raise ValueError(
                f"DataFrame is missing required columns: {missing}. "
                f"Ensure it was produced by DataIngestion.fetch_ohlcv()."
            )

        if len(df) < 6:
            raise ValueError(
                f"DataFrame has only {len(df)} rows; at least 6 are needed "
                "to form a single 5-wave impulse candidate."
            )

        if df[["open", "high", "low", "close"]].isnull().any().any():
            raise ValueError(
                "DataFrame contains NaN values in price columns. "
                "Run DataIngestion._clean() before passing to PivotDetector."
            )

    # ═══════════════════════════════════════════════════════════════════════
    # Step 2a — Price series extraction
    # ═══════════════════════════════════════════════════════════════════════

    def _extract_price_series(
        self, df: pd.DataFrame
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Return (prices_for_detection, highs, lows) as numpy float arrays.

        The detection series is selected by ``price_source``:
          "close" → raw close
          "hl"    → (H+L)/2  for detection; pure H and L for pivot prices
          "hlc3"  → (H+L+C)/3
        """
        high_arr  = df["high"].to_numpy(dtype=np.float64)
        low_arr   = df["low"].to_numpy(dtype=np.float64)
        close_arr = df["close"].to_numpy(dtype=np.float64)

        if self.cfg.price_source == "close":
            detect_arr = close_arr
        elif self.cfg.price_source == "hl":
            detect_arr = (high_arr + low_arr) / 2.0
        else:  # "hlc3"
            detect_arr = (high_arr + low_arr + close_arr) / 3.0

        return detect_arr, high_arr, low_arr

    # ═══════════════════════════════════════════════════════════════════════
    # Step 2b — ZigZag pivot detection
    # ═══════════════════════════════════════════════════════════════════════

    def _detect_pivots_zigzag(
        self,
        prices: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> List[Pivot]:
        """
        Percentage-reversion ZigZag algorithm.

        A new pivot is confirmed only when price reverses at least
        ``deviation_threshold`` percent from the most recent extreme.

        The pivot *price* uses the actual High (for peaks) or Low (for troughs)
        of the confirmation bar, regardless of the detection series, ensuring
        the output prices represent true market extremes.

        Algorithm
        ---------
        State machine with three phases:
          direction=0 (undecided) → find the first meaningful move
          direction=1 (up)        → track new highs; pivot when reversal >= threshold
          direction=-1 (down)     → track new lows; pivot when reversal >= threshold
        """
        n         = len(prices)
        threshold = self.cfg.deviation_threshold
        pivots: List[Tuple[int, float, int]] = []   # (bar_idx, price, direction)

        high_idx = low_idx = 0
        direction = 0   # 0=undecided, 1=uptrend, -1=downtrend
        last_bar = -1   # [FE1.6.0] شريط آخر محور مؤكد — حدود شرائح تحسين الويك

        def _peak_at(k: int) -> None:
            """[FE1.6.0] قمة عند القيمة القصوى المطلقة الحقيقية (ويك) في الشريحة
            (last_bar, k] — كانت القمة تُثبّت على شريط الإغلاق الأقصى رغم أن ذيلًا
            أعلى على شريط آخر داخل الترند هو القمة البصرية التي يراها المتداول
            ويحترمها السعر الحي (اقتباس PivotScanner المرجعي: القيم القصوى
            المطلقة على High/Low)."""
            nonlocal last_bar
            j = self._wick_extreme_index(highs, last_bar + 1, k, want_max=True)
            pivots.append((j, float(highs[j]), 1))
            last_bar = j

        def _trough_at(k: int) -> None:
            """[FE1.6.0] قاع عند القيمة القصوى المطلقة الحقيقية (ويك) في الشريحة."""
            nonlocal last_bar
            j = self._wick_extreme_index(lows, last_bar + 1, k, want_max=False)
            pivots.append((j, float(lows[j]), -1))
            last_bar = j

        for i in range(1, n):
            if direction == 0:
                # Phase 1: looking for the first significant move
                if prices[i] > prices[high_idx]:
                    high_idx = i
                if prices[i] < prices[low_idx]:
                    low_idx = i

                move_up   = (prices[i]         - prices[low_idx]) / prices[low_idx]
                move_down = (prices[high_idx]  - prices[i])       / prices[high_idx]

                if move_up >= threshold:
                    # Uptrend established from low_idx
                    _trough_at(i)
                    direction = 1
                    high_idx  = i
                elif move_down >= threshold:
                    # Downtrend established from high_idx
                    _peak_at(i)
                    direction = -1
                    low_idx   = i

            elif direction == 1:
                # Phase 2: tracking uptrend — looking for the next trough
                if prices[i] >= prices[high_idx]:
                    high_idx = i   # extend current peak (not yet confirmed)
                else:
                    reversal = (prices[high_idx] - prices[i]) / prices[high_idx]
                    if reversal >= threshold:
                        # Confirm the peak and start a new downtrend
                        _peak_at(i)
                        direction = -1
                        low_idx   = i

            else:  # direction == -1
                # Phase 3: tracking downtrend — looking for the next peak
                if prices[i] <= prices[low_idx]:
                    low_idx = i   # extend current trough (not yet confirmed)
                else:
                    reversal = (prices[i] - prices[low_idx]) / prices[low_idx]
                    if reversal >= threshold:
                        # Confirm the trough and start a new uptrend
                        _trough_at(i)
                        direction = 1
                        high_idx  = i

        # ── Close out the final open (unconfirmed) pivot ─────────────────────
        # The last pivot in a ZigZag is always tentative — it updates until
        # the next confirmation.  We include it because the scanner needs to
        # assess the most recent potential Wave 5 completion.
        if direction == 1:
            _peak_at(n - 1)
        elif direction == -1:
            _trough_at(n - 1)

        return self._raw_tuples_to_pivots(pivots)

    # ═══════════════════════════════════════════════════════════════════════
    # [FE1.6.0] مساعد الويك — القيمة القصوى المطلقة داخل شريحة
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _wick_extreme_index(arr: np.ndarray, lo: int, hi: int, want_max: bool) -> int:
        """فهرس القيمة القصوى (أعلى High أو أدنى Low) في الشريحة [lo..hi].
        عند التساوي يُفضّل الشريط الأحدث ليظل كل محور بعد سابقه تمامًا،
        ولا يُنتج أبدًا محورين على الشريط نفسه (الشريحة تبدأ بعد آخر محور).
        [FE1.9.2] شريحة فارغة (انعكاس تأكد على الشريط الأخير نفسه ثم طُلب
        المحور المبدئي الختامي بعده — مثل STRK/BAT/RNDR حيًا): كانت
        argmin/argmax على تسلسل فارغ تُسقط الكاشف كله ف يتخطى المسح الرمز
        بصمت كل دورة — الآن المحور الختامي يقع على الشريط الأخير ذاته
        (دلالة الإغلاق نفسها قبل تحسين الويك FE1.6.0) بلا أي انكسار."""
        lo = max(lo, 0)
        hi = min(max(hi, lo), len(arr) - 1)
        if lo > hi:
            # lo تجاوز آخر شريط — hi هنا = len(arr)-1: المحور الختامي على الشريط الأخير
            return max(hi, 0)
        seg  = arr[lo : hi + 1]
        seg_rev = seg[::-1]
        pos = int(np.argmax(seg_rev)) if want_max else int(np.argmin(seg_rev))
        return lo + (len(seg) - 1 - pos)

    # ═══════════════════════════════════════════════════════════════════════
    # Step 2c — Window-based pivot detection (scipy)
    # ═══════════════════════════════════════════════════════════════════════

    def _detect_pivots_window(
        self,
        prices: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> List[Pivot]:
        """
        Rolling-window local extrema using scipy.signal.find_peaks.

        Peaks are identified on the raw detection series; troughs are
        identified by inverting it.  A minimum prominence filter removes
        noise relative to the local price level.

        The ``distance`` parameter enforces a minimum spacing of
        ``window_size`` bars between successive peaks (or troughs).

        Pivot prices use the actual High/Low of the identified bar.
        """
        median_price = float(np.median(prices))
        prominence   = max(
            median_price * self.cfg.prominence_pct,
            1e-8,   # absolute floor to avoid zero prominence on flat data
        )
        distance = max(self.cfg.window_size, 1)

        peak_indices, _   = find_peaks(
            prices, distance=distance, prominence=prominence
        )
        trough_indices, _ = find_peaks(
            -prices, distance=distance, prominence=prominence
        )

        raw: List[Tuple[int, float, int]] = (
            [(int(i), float(highs[i]), 1)  for i in peak_indices] +
            [(int(i), float(lows[i]), -1)  for i in trough_indices]
        )
        raw.sort(key=lambda t: t[0])

        log.debug(
            "Window method: %d peaks + %d troughs = %d raw pivots "
            "(prominence=%.4f, distance=%d)",
            len(peak_indices), len(trough_indices), len(raw),
            prominence, distance,
        )
        return self._raw_tuples_to_pivots(raw)

    # ═══════════════════════════════════════════════════════════════════════
    # Step 3 — Enforce strict alternation
    # ═══════════════════════════════════════════════════════════════════════

    def _enforce_alternation(
        self,
        pivots: List[Pivot],
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> List[Pivot]:
        """
        Ensure the pivot sequence strictly alternates peak/trough/peak/...

        When two consecutive pivots of the same type are adjacent (e.g. two
        peaks back-to-back), only the more extreme one is retained:
          - Two peaks   → keep the higher peak (true local maximum).
          - Two troughs → keep the lower trough (true local minimum).

        This is necessary after the window method (which detects peaks and
        troughs independently) and can also occur at the start/end of a
        ZigZag series.
        """
        if not pivots:
            return []

        result: List[Pivot] = [pivots[0]]

        for pv in pivots[1:]:
            last = result[-1]

            if pv.pivot_type != last.pivot_type:
                # Different types → strict alternation satisfied, append
                result.append(pv)
            else:
                # Same type → keep the more extreme pivot
                if pv.is_peak and pv.price > last.price:
                    result[-1] = pv   # new pivot is a higher peak
                elif pv.is_trough and pv.price < last.price:
                    result[-1] = pv   # new pivot is a lower trough
                # else: existing pivot is already more extreme → discard new one

        log.debug(
            "Alternation: %d → %d pivots (removed %d duplicates)",
            len(pivots), len(result), len(pivots) - len(result),
        )
        return result

    # ═══════════════════════════════════════════════════════════════════════
    # Step 4 — Minimum wave bars filter
    # ═══════════════════════════════════════════════════════════════════════

    def _filter_min_wave_bars(self, pivots: List[Pivot]) -> List[Pivot]:
        """
        Remove pivots that are fewer than ``min_wave_bars`` candles apart.

        Waves that span only 1–2 candles are almost always noise on any
        timeframe above 1m.  This filter collapses unrealistically fast
        swings into their more extreme neighbour.

        Uses a greedy forward pass: the first pivot in each pair is kept,
        and subsequent pivots are accepted only if they are far enough away.
        """
        if len(pivots) < 2:
            return pivots

        min_bars = self.cfg.min_wave_bars
        result   = [pivots[0]]

        for pv in pivots[1:]:
            gap = pv.bar_index - result[-1].bar_index
            if gap >= min_bars:
                result.append(pv)
            else:
                # Too close — keep the more extreme of the two
                last = result[-1]
                if pv.is_peak and pv.price > last.price:
                    result[-1] = pv
                elif pv.is_trough and pv.price < last.price:
                    result[-1] = pv

        log.debug(
            "Min-bar filter (%d bars): %d → %d pivots",
            min_bars, len(pivots), len(result),
        )
        return result

    # ═══════════════════════════════════════════════════════════════════════
    # Step 5 — Enumerate 6-point windows and validate
    # ═══════════════════════════════════════════════════════════════════════

    # Expected directional signatures for impulse waves:
    #   Bullish impulse: trough→peak→trough→peak→trough→peak  (-1,+1,-1,+1,-1,+1)
    #   Bearish impulse: peak→trough→peak→trough→peak→trough  (+1,-1,+1,-1,+1,-1)
    _BULL_SIGNATURE = (-1, 1, -1, 1, -1, 1)
    _BEAR_SIGNATURE = (1, -1, 1, -1, 1, -1)

    def _enumerate_windows(
        self,
        pivots: List[Pivot],
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> List[DetectedSetup]:
        """
        Slide a 6-pivot window over the alternated pivot list and validate each.

        For every window of 6 consecutive pivots:
        1. Check directional signature (bull or bear).
        2. Map pivot prices to WavePivots(P0…P5).
        3. Call validate_impulse() from the WaveValidator.
        4. If valid (and optional fib confluence passes), create a DetectedSetup.

        Returns all valid setups sorted by the timestamp of P5 (detected_at).
        """
        setups: List[DetectedSetup] = []
        n = len(pivots)

        # Pre-cache timestamps from the DataFrame
        timestamps = df["timestamp"].tolist()
        # [FE1.6.0] مصفوفتا High/Low الحقيقيتان — لفحص R1/R3 واعيًا بالذيل
        highs_arr = df["high"].to_numpy(dtype=np.float64)
        lows_arr  = df["low"].to_numpy(dtype=np.float64)

        for start in range(n - 5):
            window = pivots[start : start + 6]

            # ── Directional signature check ──────────────────────────────────
            sig = tuple(
                1 if pv.is_peak else -1 for pv in window
            )
            if sig == self._BULL_SIGNATURE:
                direction = "BULLISH"
            elif sig == self._BEAR_SIGNATURE:
                direction = "BEARISH"
            else:
                continue   # Not an impulse signature — skip

            # ── Extract P0–P5 prices ─────────────────────────────────────────
            p0, p1, p2, p3, p4, p5 = (pv.price for pv in window)

            # ── [FE1.6.0] قيم قصوى مطلقة (ويكات) للشرائح بين المحاور ─────────
            # (P0, P2] لفحص R1 و (P3, P5] لفحص R3 — الويك الذي يخترق أصل W1
            # أو أرض W1 يعني أن الوقف البنيوي سيُلمس حيًا حتى لو محافطة الإغلاقات
            i0, i2 = window[0].bar_index, window[2].bar_index
            i3, i5 = window[3].bar_index, window[5].bar_index
            if i2 > i0:
                wick_min_low_p0p2  = float(np.min(lows_arr[i0 + 1 : i2 + 1]))
                wick_max_high_p0p2 = float(np.max(highs_arr[i0 + 1 : i2 + 1]))
            else:
                wick_min_low_p0p2 = wick_max_high_p0p2 = None
            if i5 > i3:
                wick_min_low_p3p5  = float(np.min(lows_arr[i3 + 1 : i5 + 1]))
                wick_max_high_p3p5 = float(np.max(highs_arr[i3 + 1 : i5 + 1]))
            else:
                wick_min_low_p3p5 = wick_max_high_p3p5 = None

            # ── Validate impulse ─────────────────────────────────────────────
            try:
                result = validate_impulse(
                    P0=p0, P1=p1, P2=p2,
                    P3=p3, P4=p4, P5=p5,
                    fib_tolerance_pct=self.cfg.fib_tolerance_pct,
                    min_wave_proportion=self.cfg.min_wave_proportion,
                    wick_min_low_p0p2=wick_min_low_p0p2,
                    wick_max_high_p0p2=wick_max_high_p0p2,
                    wick_min_low_p3p5=wick_min_low_p3p5,
                    wick_max_high_p3p5=wick_max_high_p3p5,
                )
            except ValueError as exc:
                # validate_impulse raises ValueError for invalid pivot inputs
                # (e.g. a near-zero wave caused by duplicate prices)
                log.debug(
                    "Window [%d:%d] skipped — invalid pivots: %s",
                    start, start + 6, exc,
                )
                continue

            if not result.is_valid:
                log.debug(
                    "Window [%d:%d] %s — INVALID: %s",
                    start, start + 6, direction,
                    "; ".join(r.rule_name for r in result.failed_rules()),
                )
                continue

            # ── Optional Fibonacci confluence filter ─────────────────────────
            if self.cfg.require_fib_confluence and result.fib:
                if not (result.fib.wave2_in_zone and result.fib.wave4_in_zone):
                    log.debug(
                        "Window [%d:%d] passed hard rules but FAILED fib confluence "
                        "(W2=%.1f%% W4=%.1f%%).",
                        start, start + 6,
                        result.fib.wave2_retrace_pct * 100,
                        result.fib.wave4_retrace_pct * 100,
                    )
                    continue

            # ── Build DetectedSetup ──────────────────────────────────────────
            bar_indices  = [pv.bar_index for pv in window]
            pivot_ts     = [timestamps[idx] for idx in bar_indices]
            pivot_prices = [p0, p1, p2, p3, p4, p5]
            detected_at  = pivot_ts[-1]   # timestamp of P5

            setup = DetectedSetup(
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                pivot_indices=bar_indices,
                pivot_timestamps=pivot_ts,
                pivot_prices=pivot_prices,
                validation_result=result,
                detected_at=detected_at,
                pivot_objects=list(window),
            )
            setups.append(setup)
            log.info(
                "Valid %s impulse found: P0=%.4f P1=%.4f P2=%.4f "
                "P3=%.4f P4=%.4f P5=%.4f  [bars %d→%d]",
                direction, p0, p1, p2, p3, p4, p5,
                bar_indices[0], bar_indices[-1],
            )

        return sorted(setups, key=lambda s: s.detected_at)

    # ═══════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _raw_tuples_to_pivots(
        raw: List[Tuple[int, float, int]],
    ) -> List[Pivot]:
        """
        Convert internal ``(bar_idx, price, direction)`` tuples to ``Pivot``
        dataclasses.

        The ``timestamp`` field on each Pivot is set to ``pd.NaT`` here;
        it is resolved against the actual DataFrame in ``_enumerate_windows()``
        using the confirmed ``bar_index``.
        """
        return [
            Pivot(
                bar_index  = idx,
                timestamp  = pd.NaT,          # resolved later in _enumerate_windows
                price      = price,
                pivot_type = "peak" if direction == 1 else "trough",
            )
            for idx, price, direction in raw
        ]


# ── Convenience factory ────────────────────────────────────────────────────────

def scan_for_impulses(
    df: pd.DataFrame,
    method: MethodType = "zigzag",
    deviation_threshold: float = 0.03,
    window_size: int = 5,
    prominence_pct: float = 0.005,
    price_source: Literal["close", "hl", "hlc3"] = "close",
    min_wave_bars: int = 2,
    require_fib_confluence: bool = False,
    fib_tolerance_pct: float = 1.0,
    min_wave_proportion: float = 0.15,
) -> List[DetectedSetup]:
    """
    One-liner convenience function: detect Elliott Wave impulse setups.

    Wraps ``PivotDetector.scan()`` with all parameters exposed directly.

    Parameters
    ----------
    df                     : OHLCV DataFrame from ``DataIngestion.fetch_ohlcv()``.
    method                 : "zigzag" (default) or "window".
    deviation_threshold    : ZigZag minimum reversal % (default 3%).
    window_size            : Window method: bars on each side (default 5).
    prominence_pct         : Window method: prominence as % of median (default 0.5%).
    price_source           : "close", "hl", or "hlc3" (default "close").
    min_wave_bars          : Minimum bars between pivots (default 2).
    require_fib_confluence : If True, apply Fibonacci zone filter (default False).
    fib_tolerance_pct      : Fib hit tolerance in % (default ±1.0%).

    Returns
    -------
    List[DetectedSetup]  — Valid impulse setups, chronologically ordered.

    Example
    -------
        from engine.pattern_detector import scan_for_impulses
        setups = scan_for_impulses(df_1h, deviation_threshold=0.04)
        for setup in setups:
            print(setup.summary())
    """
    cfg = DetectorConfig(
        method=method,
        deviation_threshold=deviation_threshold,
        window_size=window_size,
        prominence_pct=prominence_pct,
        price_source=price_source,
        min_wave_bars=min_wave_bars,
        require_fib_confluence=require_fib_confluence,
        fib_tolerance_pct=fib_tolerance_pct,
        min_wave_proportion=min_wave_proportion,
    )
    return PivotDetector(cfg).scan(df)
