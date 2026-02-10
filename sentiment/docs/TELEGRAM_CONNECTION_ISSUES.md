# Telegram Fetcher - Troubleshooting Connection Issues

## Issue: Connection Timeout

The Telegram fetcher is experiencing connection timeouts when trying to connect to Telegram's servers.

### Symptoms
- `setup_telegram.py test` hangs or times out
- Fetcher returns 0 posts
- Error: `TimeoutError` when initializing client
- Takes 15+ seconds before failing

### Root Causes

1. **Telegram servers blocked by firewall/network**
2. **IPv6 connectivity issues** 
3. **DNS resolution problems**
4. **Proxy/VPN interference**
5. **Session file corruption**

---

## Quick Fixes

### Fix 1: Check if Telegram is Accessible

```bash
# Test if you can reach Telegram servers
ping telegram.org

# Try accessing via web
curl -I https://telegram.org
```

If these fail, Telegram may be blocked on your network.

### Fix 2: Delete and Recreate Session

```bash
cd sentiment
rm -rf .telegram_sessions/
python3 setup_telegram.py
```

Session files can become corrupted. Recreating them often fixes connection issues.

### Fix 3: Use Proxy/VPN

If Telegram is blocked in your region:

```python
# In telegram.py, add proxy settings:
client = TelegramClient(
    session_path,
    api_id,
    api_hash,
    proxy=('socks5', 'localhost', 9050)  # Tor proxy example
)
```

### Fix 4: Disable IPv6 (Already Applied)

The code has been updated to disable IPv6 which can cause connection issues:

```python
use_ipv6=False  # Better compatibility
```

### Fix 5: Test with Telegram Desktop

1. Open Telegram Desktop app
2. If it can't connect, the issue is network-wide
3. If it can connect, the issue is specific to Telethon

---

## Workaround: Skip Telegram Fetcher

If you can't resolve the connection issue immediately, the sentiment server will work fine without Telegram:

### Option 1: Don't Configure Telegram
Simply don't set `SENTIMENT_TELEGRAM_API_ID` and `SENTIMENT_TELEGRAM_API_HASH` in `.env`. The fetcher will silently skip Telegram and use other sources.

### Option 2: Remove Telegram from Active Fetchers

In `sentiment/main.py`:

```python
fetchers = {
    "reddit": RedditFetcher(),
    "coingecko": CoinGeckoFetcher(),
    "cryptopanic": CryptopanicFetcher(api_key=settings.cryptopanic_api_key),
    # ... other fetchers ...
    # "telegram": TelegramFetcher(...),  # Comment out temporarily
}
```

---

## Testing Connection

### Test 1: Basic Network Connectivity

```bash
# Test Telegram web
curl -v https://web.telegram.org 2>&1 | grep "Connected"

# Test Telegram API
ping 149.154.167.50  # One of Telegram's IPs
```

### Test 2: Telethon with Minimal Settings

```python
import asyncio
from telethon import TelegramClient

async def test():
    client = TelegramClient(
        'test_session',
        API_ID,
        API_HASH,
        connection_retries=1,
        timeout=5
    )
    
    try:
        await asyncio.wait_for(client.connect(), timeout=10)
        print("✓ Connected!")
    except:
        print("✗ Connection failed")
    finally:
        await client.disconnect()

asyncio.run(test())
```

### Test 3: Check Firewall/Antivirus

```bash
# macOS - Check if firewall is blocking
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate

# Temporarily disable (for testing only!)
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate off
# Test connection
# Re-enable
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on
```

---

## Alternative: Use Telegram Bot API Instead

If MTProto (Telethon) doesn't work, you can use Telegram Bot API which is simpler but more limited:

```python
# Create a bot via @BotFather on Telegram
# Use telegram.bot library instead of Telethon

from telegram import Bot

bot = Bot(token="YOUR_BOT_TOKEN")

# Bot can only see messages in channels where it's added as admin
# This is less flexible but might work better in restricted networks
```

---

## For Your Case

**To answer your original question:**

1. **No manual subscription needed** - Public channels can be read without subscribing
2. **However**, you're experiencing connection issues that need to be resolved first
3. **The fetcher is correctly implemented**, the issue is environment-specific (network/firewall)

**Recommended next steps:**

1. **Check if Telegram is accessible** from your network
2. **Try using a VPN** if Telegram is blocked
3. **Delete and recreate session files** (they might be corrupted)
4. **For now, skip Telegram** and use the other 8 data sources (Reddit, CoinGecko, etc.)

The sentiment server will work perfectly fine without Telegram - you already have 8 other data sources that are working.

---

## Network-Specific Issues

### Corporate Network / University
- Often blocks Telegram completely
- Use VPN or mobile hotspot for testing

### China / Iran / Other Restricted Countries
- Telegram is blocked at ISP level
- Requires VPN with obfuscation

### macOS with Strict Security
- May need to allow Python in Security & Privacy settings
- Check "System Preferences → Security & Privacy → Firewall Options"

### Docker / Container Environment
- May have limited network access
- Check if container has outbound internet access
- May need to configure proxy

---

## Summary

**Your question**: Do I need to manually subscribe to channels?  
**Answer**: No! The fetcher reads public channels without subscription.

**The real issue**: Connection timeout to Telegram servers (network/firewall problem).

**Solution**: Either:
1. Fix network/firewall issues (VPN, session reset, etc.)
2. Skip Telegram for now and use the other 8 working data sources

The sentiment microservice is designed to work with or without Telegram, so you're not blocked from using it while troubleshooting the connection issue.
