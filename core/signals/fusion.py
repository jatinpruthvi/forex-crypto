"""
Signal Fusion Engine:
Combines Funding Rate, Open Interest Change, Long/Short Ratio, and Taker Buy/Sell Volume.
Computes conviction score (0-100) and directional bias (LONG, SHORT, NEUTRAL).
"""
import sqlite3
import os
import numpy as np
from typing import Dict, Any, Optional


class SignalFusion:
    def __init__(self, db_path: str = "data/signals.db"):
        self.db_path = db_path

    def _get_connection(self) -> Optional[sqlite3.Connection]:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                symbol TEXT NOT NULL,
                funding_rate REAL,
                open_interest REAL,
                oi_change_pct REAL,
                long_short_ratio REAL,
                taker_buy_volume REAL,
                taker_sell_volume REAL,
                taker_ratio REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(timestamp, symbol)
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_time ON market_signals(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON market_signals(symbol);")
        conn.commit()
        return conn

    def get_latest_signals(self, symbol: str) -> Dict[str, Any]:
        """Fetch latest market signal record from SQLite for given symbol."""
        conn = self._get_connection()
        if not conn:
            return {
                "funding_rate": 0.0,
                "open_interest": 0.0,
                "oi_change_pct": 0.0,
                "long_short_ratio": 1.0,
                "taker_ratio": 1.0,
            }

        cursor = conn.cursor()
        query_sym = symbol.replace(":USDT", "").replace("/", "")
        cursor.execute(
            """
            SELECT funding_rate, open_interest, oi_change_pct, long_short_ratio, taker_ratio, timestamp
            FROM market_signals
            WHERE symbol LIKE ? OR symbol LIKE ?
            ORDER BY timestamp DESC LIMIT 1
            """,
            (f"%{symbol}%", f"%{query_sym}%"),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return {
                "funding_rate": 0.0,
                "open_interest": 0.0,
                "oi_change_pct": 0.0,
                "long_short_ratio": 1.0,
                "taker_ratio": 1.0,
            }

        return {
            "funding_rate": float(row[0] or 0.0),
            "open_interest": float(row[1] or 0.0),
            "oi_change_pct": float(row[2] or 0.0),
            "long_short_ratio": float(row[3] or 1.0),
            "taker_ratio": float(row[4] or 1.0),
            "timestamp": str(row[5]),
        }

    def calculate_conviction(
        self,
        symbol: str,
        price_change_pct: float = 0.0,
        signals_override: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate 4 free signal metrics (25 pts max each):
        - Funding rate: >0.05% (+25 bearish), <-0.03% (+25 bullish)
        - OI change: OI up + Price up (+25 bull), OI up + Price down (+25 bear)
        - Long/Short ratio: <0.5 (+25 bull contrarian), >2.5 (+25 bear contrarian)
        - Taker ratio: >1.1 (+25 bull), <0.9 (+25 bear)
        """
        signals = signals_override or self.get_latest_signals(symbol)

        funding = signals.get("funding_rate", 0.0)
        oi_change = signals.get("oi_change_pct", 0.0)
        ls_ratio = signals.get("long_short_ratio", 1.0)
        taker_ratio = signals.get("taker_ratio", 1.0)

        # 1. Funding score (-25 to +25, positive=bullish, negative=bearish)
        # funding > 0.0005 (0.05%) -> overleveraged longs -> bearish
        # funding < -0.0003 (-0.03%) -> overleveraged shorts -> bullish
        funding_score = 0.0
        if funding >= 0.0005:
            funding_score = -25.0
        elif funding <= -0.0003:
            funding_score = 25.0
        elif funding > 0.0001:
            # Linear scaling between 0.0001 and 0.0005
            funding_score = -25.0 * (funding - 0.0001) / 0.0004
        elif funding < -0.0001:
            # Linear scaling between -0.0001 and -0.0003
            funding_score = 25.0 * (-funding - 0.0001) / 0.0002

        # 2. Open Interest change score (-25 to +25)
        oi_score = 0.0
        if oi_change > 1.0:
            if price_change_pct >= 0:
                oi_score = 25.0  # Bullish expansion
            else:
                oi_score = -25.0  # Bearish expansion
        elif oi_change < -1.0:
            if price_change_pct >= 0:
                oi_score = 10.0  # Short squeeze (weaker)
            else:
                oi_score = -10.0  # Long liquidation (weaker)

        # 3. Long/Short ratio score (-25 to +25, contrarian)
        ls_score = 0.0
        if ls_ratio >= 2.5:
            ls_score = -25.0  # Extreme crowd long -> Bearish contrarian
        elif ls_ratio <= 0.5:
            ls_score = 25.0  # Extreme crowd short -> Bullish contrarian
        elif ls_ratio > 1.2:
            ls_score = -25.0 * (ls_ratio - 1.2) / 1.3
        elif ls_ratio < 0.8:
            ls_score = 25.0 * (0.8 - ls_ratio) / 0.3

        # 4. Taker ratio score (-25 to +25)
        taker_score = 0.0
        if taker_ratio >= 1.10:
            taker_score = 25.0
        elif taker_ratio <= 0.90:
            taker_score = -25.0
        elif taker_ratio > 1.05:
            taker_score = 25.0 * (taker_ratio - 1.05) / 0.05
        elif taker_ratio < 0.95:
            taker_score = -25.0 * (0.95 - taker_ratio) / 0.05

        # 5. Microstructure Pressure Index (MPI):
        # Combines aggressive net taker bias and open-interest institutional delta.
        # MPI > 0.35 confirms strong institutional aggressive accumulation.
        # MPI < -0.35 alerts to aggressive institutional liquidation.
        taker_delta = (taker_ratio - 1.0) / max(0.01, taker_ratio + 1.0)
        oi_direction = 1.0 if (oi_change > 0 and price_change_pct >= 0) else (-1.0 if oi_change > 0 else 0.0)
        mpi_index = round(float(np.clip((taker_delta * 0.7) + (oi_direction * 0.3), -1.0, 1.0)), 3)

        # Funding Climax Penalty: if funding rate is exorbitantly positive (>0.05%), penalize long conviction
        funding_penalty = 0.0
        if funding > 0.0005:
            funding_penalty = -15.0  # Overcrowded long climax risk
        elif funding < -0.0003:
            funding_penalty = 15.0   # Overcrowded short squeeze bonus

        total_net = funding_score + oi_score + ls_score + taker_score + funding_penalty
        conviction = min(100.0, max(0.0, abs(total_net)))

        if total_net >= 25.0:
            direction = "LONG"
        elif total_net <= -25.0:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        return {
            "conviction": round(conviction, 1),
            "direction": direction,
            "net_score": round(total_net, 1),
            "mpi_index": mpi_index,
            "breakdown": {
                "funding": round(funding_score, 1),
                "oi": round(oi_score, 1),
                "ls_ratio": round(ls_score, 1),
                "taker": round(taker_score, 1),
                "mpi_index": mpi_index,
            },
            "signals": {
                "funding_rate": funding,
                "oi_change_pct": oi_change,
                "long_short_ratio": ls_ratio,
                "taker_ratio": taker_ratio,
                "mpi_index": mpi_index,
            },
        }

    def get_position_size_multiplier(self, conviction: float) -> float:
        """Size multiplier based on conviction tier."""
        if conviction >= 80.0:
            return 1.0
        elif conviction >= 60.0:
            return 0.5
        elif conviction >= 40.0:
            return 0.25
        return 0.0
