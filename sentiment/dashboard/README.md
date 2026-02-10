# Sentiment Dashboard

A simple web interface for visualizing crypto sentiment news from multiple sources.

## Features

- **Real-time sentiment visualization** - View news from all sources with FinBERT predictions
- **Selectable filters**:
  - Symbol: BTC, ETH, SOL, BNB, or MARKET (all crypto)
  - News count per source: 5, 10, or 15
  - Time range: Last 6, 12, 24, or 48 hours
- **Detailed sentiment scores**:
  - Positive, Negative, Neutral percentages
  - Prediction label (POSITIVE/NEGATIVE/NEUTRAL)
  - Confidence score
- **Source badges** - Color-coded by source (Reddit, Telegram, CryptoPanic, etc.)
- **Statistics overview** - Total news, distribution, active sources
- **Auto-refresh** - Updates every 5 minutes

## Usage

### Start the Sentiment Server

```bash
cd sentiment
python main.py
```

The server will start on `http://localhost:8000`

### Access the Dashboard

Open your browser and navigate to:

```
http://localhost:8000/
```

Or directly:

```
http://localhost:8000/dashboard/
```

## Interface

### Controls

1. **Symbol dropdown**: Choose which crypto to view sentiment for
   - BTCUSDT (Bitcoin)
   - ETHUSDT (Ethereum)
   - SOLUSDT (Solana)
   - BNBUSDT (BNB)
   - MARKET (General crypto market news)

2. **News per source**: Select how many top news items to show per source
   - 5 (quick overview)
   - 10 (default, balanced)
   - 15 (detailed view)

3. **Time range**: Filter news by recency
   - Last 6 hours (most recent)
   - Last 12 hours
   - Last 24 hours (default)
   - Last 48 hours (broader view)

4. **Refresh button**: Manually refresh data

### News Cards

Each news card displays:

- **Source badge**: Color-coded source identifier
- **Timestamp**: When the news was published
- **News text**: The actual news content
- **Sentiment scores**: 
  - Positive: Green background
  - Negative: Red background
  - Neutral: Gray background
- **Prediction**: Overall sentiment with confidence percentage

### Statistics Bar

Shows aggregate metrics:
- Total news count
- Positive count and percentage
- Negative count and percentage
- Neutral count and percentage
- Number of active sources

## How It Works

1. **Frontend** (`dashboard/index.html`):
   - Pure HTML/CSS/JavaScript (no frameworks needed)
   - Fetches data from `/predictions/{symbol}` API endpoint
   - Groups news by source
   - Displays top N items per source sorted by confidence

2. **Backend** (FastAPI):
   - Serves dashboard as static files
   - Provides `/predictions/{symbol}` endpoint with raw FinBERT predictions
   - Includes fetched news, sentiment scores, and prediction labels

3. **Data Flow**:
   ```
   Dashboard → /predictions/BTCUSDT?hours=24
             ↓
   Sentiment DB returns raw predictions with scores
             ↓
   Dashboard groups by source, sorts by confidence
             ↓
   Displays top N items per source
   ```

## API Endpoint

The dashboard uses the `/predictions/{symbol}` endpoint:

```bash
curl "http://localhost:8000/predictions/BTCUSDT?hours=24"
```

**Response**:
```json
{
  "symbol": "BTCUSDT",
  "count": 234,
  "predictions": [
    {
      "text": "Bitcoin surges past $100k milestone...",
      "source": "cryptopanic",
      "fetched_at": "2026-02-10T18:00:00Z",
      "published_at": "2026-02-10T17:45:00Z",
      "pred_positive": 0.85,
      "pred_negative": 0.05,
      "pred_neutral": 0.10,
      "pred_label": "positive",
      "pred_confidence": 0.85
    },
    ...
  ]
}
```

## Customization

### Colors

Edit the CSS in `dashboard/index.html`:

```css
/* Source badges */
.source-reddit { background: #FF4500; }
.source-telegram { background: #0088cc; }

/* Prediction colors */
.pred-positive { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
.pred-negative { background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%); }
```

### Default Settings

Change default dropdown values:

```html
<select id="count">
    <option value="5">5</option>
    <option value="10" selected>10</option>  <!-- Change 'selected' -->
    <option value="15">15</option>
</select>
```

### Auto-refresh Interval

Change the refresh interval (default: 5 minutes):

```javascript
// Auto-refresh every 5 minutes (300000 ms)
setInterval(() => {
    loadData();
}, 300000);  // Change this value
```

## Mobile Responsive

The dashboard is fully responsive and works on:
- Desktop (1400px+)
- Tablet (768px - 1399px)
- Mobile (<768px)

## Screenshot

```
┌─────────────────────────────────────────────────┐
│  📊 Crypto Sentiment Dashboard                  │
│  Real-time sentiment analysis from multiple     │
│  sources                                        │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  Symbol: [BTC ▼]  Count: [10 ▼]  Range: [24h ▼]│
│  [🔄 Refresh]                                   │
└─────────────────────────────────────────────────┘

┌────────┬────────┬────────┬────────┬──────────┐
│  234   │   89   │   45   │  100   │    5     │
│ Total  │Positive│Negative│Neutral │  Sources │
└────────┴────────┴────────┴────────┴──────────┘

┌───────────────────────────────────────────────┐
│ [TELEGRAM] 2026-02-10 17:45                   │
│ Bitcoin surges past $100k milestone as...     │
│ [Pos: 85%] [Neg: 5%] [Neu: 10%]              │
│ ═══════════════════════════════════════       │
│        POSITIVE (Confidence: 85%)             │
└───────────────────────────────────────────────┘
```

## Troubleshooting

### Dashboard doesn't load

**Problem**: `ERR_CONNECTION_REFUSED` or blank page

**Solution**:
1. Check sentiment server is running: `python main.py`
2. Verify port 8000 is not blocked by firewall
3. Try accessing: `http://localhost:8000/health`

### No data showing

**Problem**: Dashboard loads but shows "No news data available"

**Solution**:
1. Check if data exists: `curl http://localhost:8000/predictions/BTCUSDT?hours=24`
2. Verify fetchers are working (check logs)
3. Try different symbol or time range
4. Wait for initial data collection (may take a few minutes)

### CORS errors

**Problem**: Browser console shows CORS errors

**Solution**:
The dashboard is served by FastAPI on the same origin, so CORS shouldn't be an issue. If you see CORS errors:
1. Don't open `index.html` directly from file system
2. Access via `http://localhost:8000/` instead
3. If using reverse proxy, ensure CORS headers are set

## Future Enhancements

Potential additions:
- [ ] Real-time updates via WebSocket
- [ ] Charts/graphs for sentiment trends
- [ ] Export to CSV/JSON
- [ ] Filter by specific sources
- [ ] Search/filter by keywords
- [ ] Dark mode toggle
- [ ] Historical comparison views
- [ ] Sentiment heatmap by hour

## License

Same as main quant-bot project.
