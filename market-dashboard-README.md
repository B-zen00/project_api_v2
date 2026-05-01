# Market Dashboard V2

## Architecture

```
market-dashboard/
├── backend/
│   ├── main.py          ← FastAPI app (Python)
│   ├── requirements.txt
│   ├── start.sh         ← รัน backend ด้วย script นี้
│   └── portfolio.db     ← SQLite (สร้างอัตโนมัติ)
└── frontend/
    └── index.html       ← เปิดใน browser ได้เลย
```

## Data Sources

| ประเภท | API |
|--------|-----|
| Crypto (BTC, ETH…) | CoinGecko (ฟรี ไม่ต้อง API key) |
| Stocks (AAPL, TSLA…) | Yahoo Finance (ไม่ต้อง API key) |
| Indices, Commodities, Forex | Yahoo Finance |

## Setup

### 1. รัน Backend

```bash
cd backend
chmod +x start.sh
./start.sh
```

หรือรันด้วยตนเอง:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 2. เปิด Frontend

เปิดไฟล์ `frontend/index.html` ใน browser ได้เลย

หรือรัน local server:
```bash
cd frontend
python3 -m http.server 3000
# เปิด http://localhost:3000
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/health | Status check |
| GET | /api/market | ราคาสินทรัพย์ทั้งหมด |
| GET | /api/market/{symbol} | ราคา symbol เดียว |
| GET | /api/search?q=BTC | ค้นหา symbol |
| GET | /api/portfolio | ดู portfolio |
| POST | /api/portfolio | เพิ่มสินทรัพย์ `{symbol, amount_usd}` |
| DELETE | /api/portfolio/{symbol} | ลบสินทรัพย์ |
| PUT | /api/portfolio/{symbol} | แก้ไข qty/avg_price |

### Docs (Swagger UI)
```
http://localhost:8000/docs
```

## Price Cache

ราคาจะ cache ไว้ใน memory **60 วินาที** เพื่อไม่ให้ call API บ่อยเกินไป  
Frontend จะ refresh ทุก 60 วินาทีอัตโนมัติ

## Portfolio Storage

Portfolio เก็บใน `backend/portfolio.db` (SQLite)  
ข้อมูลจะยังอยู่แม้ปิด server

## Supported Symbols

**Crypto**: BTC, ETH, BNB, SOL, DOGE, XRP, ADA, AVAX, DOT, MATIC, LINK, UNI  
**Stocks**: AAPL, TSLA, MSFT, GOOGL, AMZN, NVDA (และ stocks อื่นๆ ที่อยู่ใน Yahoo Finance)  
**Indices**: N225, SPX, IXIC, HSI, SENSEX, NIFTY, SSE  
**Commodities**: GOLD, SILVER, OIL  
**Forex**: USDTHB, XAUUSD
