"""
Cross-Asset Correlation Monitor:
Calculates 30-day rolling correlation across crypto, forex, gold, and indices.
Evaluates portfolio concentration risk and macroeconomic risk regime (RISK_ON, RISK_OFF, MIXED).
"""
from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd


class CrossAssetMonitor:
    def __init__(self):
        pass

    def calculate_correlation_matrix(self, price_dict: Dict[str, pd.Series]) -> pd.DataFrame:
        """Calculate correlation matrix of asset returns."""
        df_prices = pd.DataFrame(price_dict).dropna()
        if len(df_prices) < 5:
            # Fallback identity matrix
            cols = list(price_dict.keys())
            return pd.DataFrame(np.eye(len(cols)), index=cols, columns=cols)
        returns = df_prices.pct_change().dropna()
        return returns.corr()

    def check_correlation_risk(
        self,
        open_positions: List[Dict[str, Any]],
        correlation_matrix: Optional[pd.DataFrame] = None,
    ) -> float:
        """
        If open positions have correlation > 0.8 -> reduce size multiplier to 0.5.
        If > 0.7 -> 0.75.
        Else -> 1.0.
        """
        symbols = [p.get("symbol") for p in open_positions if p.get("symbol")]
        if len(symbols) < 2 or correlation_matrix is None:
            return 1.0

        # Filter available symbols in correlation matrix
        valid_syms = [s for s in symbols if s in correlation_matrix.columns]
        if len(valid_syms) < 2:
            return 1.0

        sub_matrix = correlation_matrix.loc[valid_syms, valid_syms].values.copy()
        # Off-diagonal elements
        np.fill_diagonal(sub_matrix, 0.0)
        max_corr = np.max(np.abs(sub_matrix))

        if max_corr >= 0.8:
            return 0.5
        elif max_corr >= 0.7:
            return 0.75
        return 1.0

    def evaluate_risk_regime(
        self,
        crypto_return: float,
        stock_return: float,
        gold_return: float,
        dxy_return: float,
    ) -> str:
        """
        Determine global macro risk state:
        - RISK_ON: Stocks & Crypto up, DXY / Gold softer
        - RISK_OFF: Stocks & Crypto down, DXY / Gold stronger
        - MIXED: Divergent moves
        """
        risk_asset_score = (1 if crypto_return > 0 else -1) + (1 if stock_return > 0 else -1)
        safe_asset_score = (1 if gold_return > 0 else -1) + (1 if dxy_return > 0 else -1)

        if risk_asset_score > 0 and safe_asset_score <= 0:
            return "RISK_ON"
        elif risk_asset_score < 0 and safe_asset_score >= 0:
            return "RISK_OFF"
        return "MIXED"

    def evaluate_dxy_liquidity_filter(
        self,
        dxy_series: Optional[pd.Series] = None,
        dxy_daily_change_pct: float = 0.0,
    ) -> Dict[str, Any]:
        """
        DXY (US Dollar Index) Beta Inversion Filter:
        Crypto, Gold (XAU/USD), and major FX pairs (EUR/USD, GBP/USD) exhibit severe
        negative beta to explosive US Dollar rallies.
        - If DXY rallies > +0.4% intraday or breaks above 20-period high:
          Trigger DOLLAR_SQUEEZE warning and scale back Long risk by 50%.
        """
        dollar_squeeze = False
        reasons = []

        if dxy_daily_change_pct >= 0.40:
            dollar_squeeze = True
            reasons.append(f"DXY intraday spike (+{dxy_daily_change_pct:.2f}%)")

        if dxy_series is not None and len(dxy_series) >= 20:
            recent_high = dxy_series.iloc[-21:-1].max()
            current_dxy = dxy_series.iloc[-1]
            if current_dxy >= recent_high:
                dollar_squeeze = True
                reasons.append("DXY 20-period breakout high")

        risk_mult = 0.50 if dollar_squeeze else 1.0
        return {
            "dollar_squeeze": dollar_squeeze,
            "risk_multiplier": risk_mult,
            "reason": " + ".join(reasons) if reasons else "DXY normal",
        }
