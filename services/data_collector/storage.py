"""
SQLite Database Storage Manager:
Handles creation, indexing, insertion, and querying of market signals and events.
"""
import sqlite3
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone


class SignalStorage:
    def __init__(self, db_path: str = "data/signals.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
        except Exception:
            pass
        return conn

    def init_db(self) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()

        # Market signals table
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

        # Economic events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time DATETIME NOT NULL,
                currency TEXT NOT NULL,
                impact TEXT NOT NULL,
                event_name TEXT,
                forecast REAL,
                previous REAL,
                actual REAL,
                week_start DATE
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON events(event_time);")

        # Trade log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                source TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL,
                exit_price REAL,
                sl REAL,
                tp REAL,
                lots REAL,
                pnl REAL,
                pnl_pct REAL,
                regime TEXT,
                conviction REAL,
                ml_probability REAL,
                holding_minutes INTEGER,
                exit_reason TEXT
            );
        """)
        conn.commit()

    def insert_signal(self, data: Dict[str, Any]) -> bool:
        """Insert a market signal row with INSERT OR IGNORE."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT OR IGNORE INTO market_signals (
                    timestamp, symbol, funding_rate, open_interest,
                    oi_change_pct, long_short_ratio, taker_buy_volume,
                    taker_sell_volume, taker_ratio
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    data.get("symbol"),
                    data.get("funding_rate", 0.0),
                    data.get("open_interest", 0.0),
                    data.get("oi_change_pct", 0.0),
                    data.get("long_short_ratio", 1.0),
                    data.get("taker_buy_volume", 0.0),
                    data.get("taker_sell_volume", 0.0),
                    data.get("taker_ratio", 1.0),
                ),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def get_latest_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT timestamp, symbol, funding_rate, open_interest, oi_change_pct,
                   long_short_ratio, taker_ratio
            FROM market_signals
            WHERE symbol LIKE ?
            ORDER BY timestamp DESC LIMIT 1
            """,
            (f"%{symbol}%",),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "timestamp": row[0],
            "symbol": row[1],
            "funding_rate": row[2],
            "open_interest": row[3],
            "oi_change_pct": row[4],
            "long_short_ratio": row[5],
            "taker_ratio": row[6],
        }
