"""
Market Dashboard Backend
FastAPI + SQLite + Yahoo Finance + CoinGecko
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3, httpx, asyncio, time, json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── DB SETUP ────────────────────────────────────────────────────────────────
DB_PATH = "portfolio.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol    TEXT NOT NULL UNIQUE,
                name      TEXT NOT NULL,
                qty       REAL NOT NULL DEFAULT 0,
                avg_price REAL NOT NULL DEFAULT 0,
                icon      TEXT DEFAULT '?',
                color     TEXT DEFAULT '#888',
                bg        TEXT DEFAULT '#88888820',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS price_cache (
                symbol     TEXT PRIMARY KEY,
                price      REAL,
                change     REAL,
                change_pct REAL,
                name       TEXT,
                cached_at  INTEGER
            );
        """)
        conn.commit()

# ─── PRICE CACHE ─────────────────────────────────────────────────────────────
CACHE_TTL = 60  # seconds
price_memory: dict = {}

async def fetch_crypto_prices(symbols: list[str]) -> dict:
    """Fetch from CoinGecko (free, no key needed)"""
    id_map = {
        "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
        "SOL": "solana", "DOGE": "dogecoin", "XRP": "ripple",
        "ADA": "cardano", "AVAX": "avalanche-2", "DOT": "polkadot",
        "MATIC": "matic-network", "LINK": "chainlink", "UNI": "uniswap",
    }
    ids = [id_map[s] for s in symbols if s in id_map]
    rev_map = {v: k for k, v in id_map.items()}
    if not ids:
        return {}
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ",".join(ids),
        "vs_currencies": "usd",
        "include_24hr_change": "true",
        "include_last_updated_at": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        result = {}
        for cg_id, vals in data.items():
            sym = rev_map.get(cg_id)
            if sym:
                price = vals.get("usd", 0)
                chg_pct = vals.get("usd_24h_change", 0) or 0
                result[sym] = {
                    "price": price,
                    "change": price * chg_pct / 100,
                    "change_pct": chg_pct,
                }
        return result
    except Exception as e:
        log.warning(f"CoinGecko error: {e}")
        return {}

async def fetch_stock_prices(symbols: list[str]) -> dict:
    """Fetch from Yahoo Finance (unofficial, no key needed)"""
    result = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for sym in symbols:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                params = {"interval": "1d", "range": "2d"}
                headers = {"User-Agent": "Mozilla/5.0"}
                r = await client.get(url, params=params, headers=headers)
                r.raise_for_status()
                data = r.json()
                meta = data["chart"]["result"][0]["meta"]
                price = meta.get("regularMarketPrice") or meta.get("previousClose", 0)
                prev = meta.get("chartPreviousClose") or meta.get("previousClose", price)
                change = price - prev
                change_pct = (change / prev * 100) if prev else 0
                result[sym] = {"price": price, "change": change, "change_pct": change_pct}
                await asyncio.sleep(0.1)  # rate limit
            except Exception as e:
                log.warning(f"Yahoo error {sym}: {e}")
    return result

# Symbol classification
CRYPTO_SYMBOLS  = {"BTC","ETH","BNB","SOL","DOGE","XRP","ADA","AVAX","DOT","MATIC","LINK","UNI"}
YAHOO_OVERRIDE  = {"GOLD":"GC=F","SILVER":"SI=F","OIL":"CL=F","N225":"^N225","SPX":"^GSPC","IXIC":"^IXIC","USDTHB":"THBUSD=X","HSI":"^HSI","SENSEX":"^BSESN","NIFTY":"^NSEI","SSE":"000001.SS"}

async def get_prices(symbols: list[str]) -> dict:
    """Get prices with in-memory cache"""
    now = int(time.time())
    result = {}
    to_fetch_crypto, to_fetch_stock = [], []

    for sym in symbols:
        cached = price_memory.get(sym)
        if cached and (now - cached["cached_at"]) < CACHE_TTL:
            result[sym] = cached
        elif sym in CRYPTO_SYMBOLS:
            to_fetch_crypto.append(sym)
        else:
            to_fetch_stock.append(sym)

    if to_fetch_crypto:
        fresh = await fetch_crypto_prices(to_fetch_crypto)
        for sym, data in fresh.items():
            data["cached_at"] = now
            price_memory[sym] = data
            result[sym] = data

    if to_fetch_stock:
        yahoo_syms = [YAHOO_OVERRIDE.get(s, s) for s in to_fetch_stock]
        sym_map = {YAHOO_OVERRIDE.get(s, s): s for s in to_fetch_stock}
        fresh = await fetch_stock_prices(yahoo_syms)
        for yahoo_sym, data in fresh.items():
            orig = sym_map.get(yahoo_sym, yahoo_sym)
            data["cached_at"] = now
            price_memory[orig] = data
            result[orig] = data

    return result

# ─── APP ─────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("DB initialized")
    yield

app = FastAPI(title="Market Dashboard API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── MODELS ──────────────────────────────────────────────────────────────────
class AddAssetRequest(BaseModel):
    symbol: str
    amount_usd: float  # amount to invest in USD

class UpdateAssetRequest(BaseModel):
    qty: Optional[float] = None
    avg_price: Optional[float] = None

# ─── MARKET ENDPOINTS ────────────────────────────────────────────────────────
DEFAULT_SYMBOLS = [
    "BTC","ETH","BNB","SOL","DOGE",
    "AAPL","TSLA","MSFT","GOOGL","AMZN","NVDA",
    "N225","SPX","IXIC","GOLD","SILVER","OIL","USDTHB"
]

ASSET_META = {
    "BTC":    {"name":"Bitcoin",    "icon":"₿",  "color":"#f7931a","bg":"#f7931a20","category":"crypto"},
    "ETH":    {"name":"Ethereum",   "icon":"Ξ",  "color":"#627eea","bg":"#627eea20","category":"crypto"},
    "BNB":    {"name":"BNB",        "icon":"B",  "color":"#f3ba2f","bg":"#f3ba2f20","category":"crypto"},
    "SOL":    {"name":"Solana",     "icon":"◎",  "color":"#9945ff","bg":"#9945ff20","category":"crypto"},
    "DOGE":   {"name":"Dogecoin",   "icon":"Ð",  "color":"#c2a633","bg":"#c2a63320","category":"crypto"},
    "XRP":    {"name":"XRP",        "icon":"✕",  "color":"#346aa9","bg":"#346aa920","category":"crypto"},
    "ADA":    {"name":"Cardano",    "icon":"₳",  "color":"#0033ad","bg":"#0033ad20","category":"crypto"},
    "AVAX":   {"name":"Avalanche",  "icon":"A",  "color":"#e84142","bg":"#e8414220","category":"crypto"},
    "DOT":    {"name":"Polkadot",   "icon":"●",  "color":"#e6007a","bg":"#e6007a20","category":"crypto"},
    "MATIC":  {"name":"Polygon",    "icon":"M",  "color":"#8247e5","bg":"#8247e520","category":"crypto"},
    "LINK":   {"name":"Chainlink",  "icon":"⬡",  "color":"#2a5ada","bg":"#2a5ada20","category":"crypto"},
    "UNI":    {"name":"Uniswap",    "icon":"🦄", "color":"#ff007a","bg":"#ff007a20","category":"crypto"},
    "AAPL":   {"name":"Apple",      "icon":"🍎", "color":"#888888","bg":"#88888820","category":"stock"},
    "TSLA":   {"name":"Tesla",      "icon":"T",  "color":"#e82127","bg":"#e8212720","category":"stock"},
    "MSFT":   {"name":"Microsoft",  "icon":"⊞",  "color":"#0078d4","bg":"#0078d420","category":"stock"},
    "GOOGL":  {"name":"Google",     "icon":"G",  "color":"#4285f4","bg":"#4285f420","category":"stock"},
    "AMZN":   {"name":"Amazon",     "icon":"A",  "color":"#ff9900","bg":"#ff990020","category":"stock"},
    "NVDA":   {"name":"NVIDIA",     "icon":"N",  "color":"#76b900","bg":"#76b90020","category":"stock"},
    "N225":   {"name":"Nikkei 225", "icon":"🇯🇵","color":"#bc002d","bg":"#bc002d20","category":"index"},
    "SPX":    {"name":"S&P 500",    "icon":"🇺🇸","color":"#3c78d8","bg":"#3c78d820","category":"index"},
    "IXIC":   {"name":"NASDAQ",     "icon":"N",  "color":"#0085ca","bg":"#0085ca20","category":"index"},
    "HSI":    {"name":"Hang Seng",  "icon":"🇭🇰","color":"#dc241f","bg":"#dc241f20","category":"index"},
    "SENSEX": {"name":"SENSEX",     "icon":"🇮🇳","color":"#ff9933","bg":"#ff993320","category":"index"},
    "NIFTY":  {"name":"Nifty 50",   "icon":"N",  "color":"#6633cc","bg":"#6633cc20","category":"index"},
    "GOLD":   {"name":"Gold",       "icon":"★",  "color":"#ffd700","bg":"#ffd70020","category":"commodity"},
    "SILVER": {"name":"Silver",     "icon":"◈",  "color":"#aaaaaa","bg":"#aaaaaa20","category":"commodity"},
    "OIL":    {"name":"Crude Oil",  "icon":"●",  "color":"#555555","bg":"#55555540","category":"commodity"},
    "USDTHB": {"name":"USD/THB",    "icon":"฿",  "color":"#3c78d8","bg":"#3c78d820","category":"forex"},
}

@app.get("/api/market")
async def get_market(symbols: str = ",".join(DEFAULT_SYMBOLS)):
    """Get market prices for all or specified symbols"""
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    prices = await get_prices(sym_list)
    result = []
    for sym in sym_list:
        meta = ASSET_META.get(sym, {"name": sym, "icon": "?", "color": "#888", "bg": "#88888820", "category": "other"})
        p = prices.get(sym, {})
        result.append({
            "symbol": sym,
            "name": meta["name"],
            "icon": meta["icon"],
            "color": meta["color"],
            "bg": meta["bg"],
            "category": meta["category"],
            "price": p.get("price", 0),
            "change": p.get("change", 0),
            "change_pct": p.get("change_pct", 0),
        })
    return {"data": result, "updated_at": datetime.now().isoformat()}

@app.get("/api/market/{symbol}")
async def get_asset(symbol: str):
    """Get single asset price"""
    sym = symbol.upper()
    prices = await get_prices([sym])
    p = prices.get(sym, {})
    meta = ASSET_META.get(sym, {"name": sym, "icon": "?", "color": "#888", "bg": "#88888820", "category": "other"})
    return {**meta, "symbol": sym, **p, "updated_at": datetime.now().isoformat()}

@app.get("/api/search")
async def search_assets(q: str):
    """Search assets by symbol or name"""
    q = q.upper()
    matches = [
        {"symbol": sym, **meta}
        for sym, meta in ASSET_META.items()
        if q in sym or q in meta["name"].upper()
    ]
    return {"data": matches}

# ─── PORTFOLIO ENDPOINTS ─────────────────────────────────────────────────────
@app.get("/api/portfolio")
async def get_portfolio():
    """Get portfolio with live prices"""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM portfolio ORDER BY created_at").fetchall()
    if not rows:
        return {"data": [], "summary": {"total_value": 0, "total_invested": 0, "total_pnl": 0, "total_pnl_pct": 0}}

    symbols = [r["symbol"] for r in rows]
    prices = await get_prices(symbols)
    items = []
    total_value = 0
    total_invested = 0

    for row in rows:
        sym = row["symbol"]
        p = prices.get(sym, {})
        cp = p.get("price", row["avg_price"])
        value = row["qty"] * cp
        invested = row["qty"] * row["avg_price"]
        pnl = value - invested
        pnl_pct = (pnl / invested * 100) if invested else 0
        total_value += value
        total_invested += invested
        items.append({
            "id": row["id"],
            "symbol": sym,
            "name": row["name"],
            "qty": row["qty"],
            "avg_price": row["avg_price"],
            "current_price": cp,
            "value": value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "icon": row["icon"],
            "color": row["color"],
            "bg": row["bg"],
            "change_pct": p.get("change_pct", 0),
        })

    for item in items:
        item["allocation"] = (item["value"] / total_value * 100) if total_value else 0

    total_pnl = total_value - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0

    return {
        "data": items,
        "summary": {
            "total_value": total_value,
            "total_invested": total_invested,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
        },
        "updated_at": datetime.now().isoformat(),
    }

@app.post("/api/portfolio")
async def add_to_portfolio(req: AddAssetRequest):
    """Add or update asset in portfolio"""
    sym = req.symbol.upper()
    if req.amount_usd <= 0:
        raise HTTPException(400, "Amount must be positive")

    # Get live price
    prices = await get_prices([sym])
    p = prices.get(sym)
    if not p or p["price"] == 0:
        raise HTTPException(404, f"Symbol '{sym}' not found or price unavailable")

    cp = p["price"]
    qty_to_add = req.amount_usd / cp
    meta = ASSET_META.get(sym, {"name": sym, "icon": "?", "color": "#888", "bg": "#88888820"})

    with get_db() as conn:
        existing = conn.execute("SELECT * FROM portfolio WHERE symbol=?", (sym,)).fetchone()
        if existing:
            new_qty = existing["qty"] + qty_to_add
            new_avg = (existing["qty"] * existing["avg_price"] + req.amount_usd) / new_qty
            conn.execute(
                "UPDATE portfolio SET qty=?, avg_price=?, updated_at=datetime('now') WHERE symbol=?",
                (new_qty, new_avg, sym)
            )
        else:
            conn.execute(
                "INSERT INTO portfolio (symbol, name, qty, avg_price, icon, color, bg) VALUES (?,?,?,?,?,?,?)",
                (sym, meta["name"], qty_to_add, cp, meta["icon"], meta["color"], meta["bg"])
            )
        conn.commit()

    return {"message": f"Added {qty_to_add:.6f} {sym} at ${cp:.2f}", "symbol": sym, "qty": qty_to_add, "price": cp}

@app.delete("/api/portfolio/{symbol}")
async def remove_from_portfolio(symbol: str):
    """Remove asset from portfolio"""
    sym = symbol.upper()
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM portfolio WHERE symbol=?", (sym,)).fetchone()
        if not existing:
            raise HTTPException(404, f"Symbol '{sym}' not in portfolio")
        conn.execute("DELETE FROM portfolio WHERE symbol=?", (sym,))
        conn.commit()
    return {"message": f"Removed {sym} from portfolio"}

@app.put("/api/portfolio/{symbol}")
async def update_portfolio_asset(symbol: str, req: UpdateAssetRequest):
    """Manually update qty or avg_price"""
    sym = symbol.upper()
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM portfolio WHERE symbol=?", (sym,)).fetchone()
        if not existing:
            raise HTTPException(404, f"Symbol '{sym}' not in portfolio")
        qty = req.qty if req.qty is not None else existing["qty"]
        avg = req.avg_price if req.avg_price is not None else existing["avg_price"]
        conn.execute(
            "UPDATE portfolio SET qty=?, avg_price=?, updated_at=datetime('now') WHERE symbol=?",
            (qty, avg, sym)
        )
        conn.commit()
    return {"message": f"Updated {sym}"}

@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}
