# Kraken equities and futures — TradeBot support

## What Kraken offers (2026-06)

| Product | Venue | API | TradeBot v1 |
|---------|-------|-----|-------------|
| **xStocks (tokenized stocks/ETFs)** | Kraken **Spot** | REST with `asset_class=tokenized_asset` | **Supported** (paper + optional live) |
| **Crypto spot** | Kraken Spot | ccxt `kraken` | Supported (existing) |
| **xStocks perpetual futures** | Kraken **Futures** | `ccxt.krakenfutures` / Futures REST | **Phase 2b** (not in v1) |
| **Crypto futures / margin** | Kraken Futures | Separate API keys & wallet | Phase 2b |
| **Kraken Trade Prop** | Evaluation accounts | N/A | Not implemented (`PROP_ENABLED=0`) |

### xStocks on spot (v1)

- 300+ USD-quoted tokenized equities and ETFs (e.g. `AAPLx/USD`, `TSLAx/USD`, `SPYx/USD`).
- Kraken exposes these under asset class `tokenized_asset`, **not** in ccxt's default `load_markets()` (which only loads `currency`).
- Public endpoints require `asset_class=tokenized_asset` on Ticker and OHLC.
- Private `AddOrder` requires `asset_class=tokenized_asset` and pair id like `AAPLxUSD`.
- Geo-restricted (not available in USA). User must confirm eligibility on Kraken.

### xStocks perpetual futures (Phase 2b)

- Symbols on `krakenfutures` include `AAPLX/USD:USD`, `TSLAX/USD:USD`, `SPYX/USD:USD` (uppercase X, swap type).
- Up to 20× leverage, 24/7, separate collateral wallet.
- Requires new module (`bot/futures/`), different risk model, and explicit user opt-in.

## TradeBot v1 behavior

**Default: OFF** — crypto-only behavior unchanged.

```env
ENABLE_EQUITIES=0
# EQUITY_WATCHLIST=AAPLx,TSLAx,SPYx
# MAX_EQUITY_ALLOCATION_PCT=0.15
```

### Enabling paper equities

```env
ENABLE_EQUITIES=1
EQUITY_WATCHLIST=AAPLx,TSLAx,SPYx
```

- Watchlist symbols are validated against Kraken `AssetPairs?aclass_base=tokenized_asset`.
- `cross_momentum` scores equity USD pairs alongside crypto (15m/1h EMA + RVOL).
- Equities trade **USD pairs only** — no crypto cross routes (e.g. no `AAPLx/ETH`).
- Portfolio cap: `MAX_EQUITY_ALLOCATION_PCT` (default 15%), separate from `MAX_ALT_ALLOCATION_PCT`.
- Defensive trims sell overweight equities back to **USD** (not ETH).

### Live equities (explicit allowlist required)

Live crypto defaults stay `LIVE_ALLOWED_ASSETS=ETH,ADA`. To mirror or execute equity trades:

```env
LIVE_ENABLED=1
LIVE_TRADING_CONFIRM=I_ACCEPT_REAL_MONEY
# Add only symbols you approve — comma-separated tickers (not pair names):
LIVE_ALLOWED_ASSETS=ETH,ADA,AAPLx
```

- Each equity ticker in `LIVE_ALLOWED_ASSETS` must also appear in `EQUITY_WATCHLIST`.
- `LiveBroker` passes `asset_class=tokenized_asset` on equity orders.
- Same per-trade caps: `LIVE_MAX_TRADE_USD`, drawdown halt, ETH reserve.

**Do not** add equities to `LIVE_ALLOWED_ASSETS` until paper behavior is verified.

## ccxt limitations

| Operation | Crypto spot | xStocks spot |
|-----------|-------------|--------------|
| `load_markets()` | Yes | No — use `bot/equities.fetch_tokenized_pairs()` |
| `fetch_ticker` | Yes | No — use Kraken REST + `asset_class` |
| `fetch_ohlcv` | Yes | No — use Kraken REST + `asset_class` |
| `create_order` | Yes | Yes with `params={"asset_class": "tokenized_asset"}` |

## Roadmap

### Phase 2a (near-term)

- Equity-specific fee tier from pair metadata (xStocks often ~0.40% at low volume).
- Whale watch on large xStock prints.
- Dashboard chart series for equity holdings.

### Phase 2b — Futures

- `ENABLE_FUTURES=0` gate, `ccxt.krakenfutures` instance.
- `bot/futures/` package: positions, leverage limits, funding rates.
- xStocks perps watchlist separate from spot `EQUITY_WATCHLIST`.
- No shared live mirror until spot equities are stable.

### Phase 3 — Prop / funded accounts

- See [kraken-prop.md](kraken-prop.md). Remains stubbed.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_equities.py -q
```

Probe live Kraken catalog (no keys):

```powershell
.\.venv\Scripts\python.exe -c "from bot.equities import fetch_tokenized_pairs; print(len(fetch_tokenized_pairs()))"
```
