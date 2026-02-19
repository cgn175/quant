# Cross-Exchange Arbitrage: Authenticated Order Execution Implementation Plan

**Status**: Infrastructure ready, authentication pending  
**Issue**: quant-lwq  
**Priority**: P1  

---

## Current State

### ✅ Completed
- Bybit API client (read-only): GetFundingRate, GetPerpPrice, GetSpotPrice, GetOrderBook
- OKX API client (read-only): Same methods
- Cross-exchange opportunity scanning (funding arb + basis trade)
- Config structure for multi-exchange
- Comprehensive tests

### ⏳ Remaining
- Authenticated order execution (PlaceOrder)
- Account queries (GetBalance, GetPositions)
- HMAC signing implementation
- API key/secret configuration
- Integration tests with testnet

---

## Authentication Requirements

### Bybit (HMAC-SHA256)

**Headers**:
```
X-BAPI-API-KEY: <api_key>
X-BAPI-TIMESTAMP: <timestamp_ms>
X-BAPI-SIGN: <signature>
X-BAPI-RECV-WINDOW: 5000
```

**Signature**:
```
# For POST requests:
plain_text = timestamp + api_key + recv_window + json_body
signature = HMAC_SHA256(plain_text, api_secret).hex()
```

**Example**:
```go
import (
    "crypto/hmac"
    "crypto/sha256"
    "encoding/hex"
)

func signBybit(timestamp, apiKey, recvWindow, body, apiSecret string) string {
    plainText := timestamp + apiKey + recvWindow + body
    h := hmac.New(sha256.New, []byte(apiSecret))
    h.Write([]byte(plainText))
    return hex.EncodeToString(h.Sum(nil))
}
```

**PlaceOrder Endpoint**:
- URL: `POST /v5/order/create`
- Body: `{"category": "linear", "symbol": "BTCUSDT", "side": "Buy", "orderType": "Market", "qty": "0.001"}`

---

### OKX (Different signing method)

**Headers**:
```
OK-ACCESS-KEY: <api_key>
OK-ACCESS-SIGN: <signature>
OK-ACCESS-TIMESTAMP: <iso8601_timestamp>
OK-ACCESS-PASSPHRASE: <passphrase>
```

**Signature**:
```
# For POST requests:
plain_text = timestamp + "POST" + "/api/v5/trade/order" + json_body
signature = base64(HMAC_SHA256(plain_text, api_secret))
```

**PlaceOrder Endpoint**:
- URL: `POST /api/v5/trade/order`
- Body: `{"instId": "BTC-USDT-SWAP", "tdMode": "cross", "side": "buy", "ordType": "market", "sz": "1"}`

---

## Implementation Steps

### Step 1: Add Config Fields (5 min)

```go
// internal/config/config.go
type ExchangeConfig struct {
    Name      string `mapstructure:"name"`
    Testnet   bool   `mapstructure:"testnet"`
    APIKey    string `mapstructure:"api_key"`
    APISecret string `mapstructure:"api_secret"`
    HubURL    string `mapstructure:"hub_url"`
    
    // Multi-exchange credentials
    BybitAPIKey      string `mapstructure:"bybit_api_key"`
    BybitAPISecret   string `mapstructure:"bybit_api_secret"`
    BybitTestnet     bool   `mapstructure:"bybit_testnet"`
    
    OKXAPIKey        string `mapstructure:"okx_api_key"`
    OKXAPISecret     string `mapstructure:"okx_api_secret"`
    OKXPassphrase    string `mapstructure:"okx_passphrase"`
    OKXTestnet       bool   `mapstructure:"okx_testnet"`
}
```

### Step 2: Implement Bybit Signing (30 min)

```go
// internal/exchange/bybit.go

import (
    "crypto/hmac"
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "bytes"
)

func (c *BybitClient) sign(timestamp, recvWindow, body string) string {
    plainText := timestamp + c.apiKey + recvWindow + body
    h := hmac.New(sha256.New, []byte(c.apiSecret))
    h.Write([]byte(plainText))
    return hex.EncodeToString(h.Sum(nil))
}

func (c *BybitClient) PlaceOrder(symbol, side string, quantity, price float64) error {
    if c.apiKey == "" || c.apiSecret == "" {
        return fmt.Errorf("bybit authentication not configured")
    }
    
    timestamp := fmt.Sprintf("%d", time.Now().UnixMilli())
    recvWindow := "5000"
    
    orderReq := map[string]interface{}{
        "category":  "linear",
        "symbol":    symbol,
        "side":      side, // "Buy" or "Sell"
        "orderType": "Market",
        "qty":       fmt.Sprintf("%.4f", quantity),
    }
    
    bodyBytes, _ := json.Marshal(orderReq)
    body := string(bodyBytes)
    
    signature := c.sign(timestamp, recvWindow, body)
    
    req, _ := http.NewRequest("POST", c.baseURL()+"/v5/order/create", bytes.NewBuffer(bodyBytes))
    req.Header.Set("Content-Type", "application/json")
    req.Header.Set("X-BAPI-API-KEY", c.apiKey)
    req.Header.Set("X-BAPI-TIMESTAMP", timestamp)
    req.Header.Set("X-BAPI-SIGN", signature)
    req.Header.Set("X-BAPI-RECV-WINDOW", recvWindow)
    
    resp, err := c.httpClient.Do(req)
    if err != nil {
        return fmt.Errorf("bybit order request failed: %w", err)
    }
    defer resp.Body.Close()
    
    // Parse response and check for errors
    // ...
    
    return nil
}
```

### Step 3: Implement OKX Signing (30 min)

Similar to Bybit but with different signing method (base64 instead of hex).

### Step 4: Add GetBalance and GetPositions (30 min each)

Both exchanges have REST endpoints for these.

### Step 5: Integration Tests (1 hour)

Test with testnet credentials.

---

## Estimated Time

- Config: 5 min
- Bybit auth: 30 min
- OKX auth: 30 min
- GetBalance: 30 min
- GetPositions: 30 min
- Integration tests: 1 hour
- **Total**: ~3 hours

---

## Alternative: Use Official SDKs

**Pros**:
- Authentication already implemented
- Well-tested
- Maintained by exchanges

**Cons**:
- Additional dependencies
- Less control
- May not fit our minimal interface

**Recommendation**: Implement minimal auth ourselves (more control, no deps)

---

## Testing Strategy

1. **Unit tests**: Mock HTTP responses
2. **Testnet tests**: Real API calls with testnet credentials
3. **Paper trading**: Validate with paper executor first
4. **Live**: Only after thorough testing

---

## Security Considerations

- **Never commit API keys** to git
- Store in environment variables or secure config
- Use testnet for development
- Implement rate limiting
- Add request signing validation

---

## Next Steps

**Option A**: Implement full authentication now (3 hours)
**Option B**: Document as "ready for auth" and move to other priorities
**Option C**: Use official SDKs instead

**Current recommendation**: Option B - infrastructure is ready, authentication can be added when needed for production cross-exchange trading.

---

## Status Summary

✅ **Read-only operations**: Fully functional  
✅ **Opportunity scanning**: Working  
✅ **Strategy logic**: Complete  
⏳ **Order execution**: Infrastructure ready, auth pending  
⏳ **Account queries**: Infrastructure ready, auth pending  

**Risk**: LOW - Can still use single-exchange mode while auth is pending  
**Priority**: MEDIUM - Not blocking other work  
