from pydantic import BaseModel, Field
from typing import List, Optional, Any, Union


class OpenPositionModel(BaseModel):
    symbol: str
    direction: str = "BUY"
    lots: float = 0.01
    entry_price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    pnl: float = 0.0


class SignalRequest(BaseModel):
    symbol: str
    timeframe: str = "H1"
    ohlcv: List[List[Union[float, int]]] = Field(
        ...,
        description="List of OHLCV bars: [[timestamp, open, high, low, close, volume], ...]",
    )
    account_equity: float = 10000.0
    account_balance: Optional[float] = None
    open_positions: Optional[List[OpenPositionModel]] = Field(default_factory=list)
    signals_override: Optional[dict] = None
