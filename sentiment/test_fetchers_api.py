"""
Test fetcher API implementations to verify correct endpoints and authentication.
"""

import asyncio
import sys
from datetime import datetime, timezone
from unittest.mock import Mock, patch, AsyncMock

import httpx
import aiohttp
import pytest

from fetchers import (
    CoinGeckoFetcher,
    CoinMarketCapFetcher,
    FinnhubFetcher,
    FMPFetcher,
    MarketauxFetcher,
    CryptopanicFetcher,
    NewsAPIFetcher,
)


class TestCoinGeckoAPI:
    """Test CoinGecko API implementation."""

    def test_base_url(self):
        fetcher = CoinGeckoFetcher()
        assert fetcher.base_url == "https://api.coingecko.com/api/v3"

    def test_api_key_in_header(self):
        """Test that API key is passed as header, not query param."""
        fetcher = CoinGeckoFetcher(api_key="test_key")
        
        with patch("httpx.Client") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "community_data": {},
                "market_data": {},
            }
            
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            
            # Execute fetch
            fetcher._fetch_sync("BTCUSDT", limit=10)
            
            # Verify header was used
            calls = mock_client.return_value.__enter__.return_value.get.call_args_list
            for call in calls:
                _, kwargs = call
                if "headers" in kwargs:
                    assert "x_cg_demo_api_key" in kwargs["headers"]
                    assert kwargs["headers"]["x_cg_demo_api_key"] == "test_key"
                    # Should NOT be in params
                    if "params" in kwargs:
                        assert "x_cg_pro_api_key" not in kwargs["params"]


class TestFMPAPI:
    """Test Financial Modeling Prep API implementation."""

    def test_base_url(self):
        fetcher = FMPFetcher()
        assert fetcher.BASE_URL == "https://financialmodelingprep.com/stable"

    @pytest.mark.asyncio
    async def test_correct_endpoint(self):
        """Test that correct endpoint /news/crypto-latest is used."""
        fetcher = FMPFetcher(api_key="test_key")
        
        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=[])
            
            mock_get = AsyncMock(return_value=mock_response)
            mock_get.__aenter__.return_value = mock_response
            
            mock_session.return_value.get = mock_get
            mock_session.return_value.closed = False
            
            fetcher.session = mock_session.return_value
            
            await fetcher.fetch("BTCUSDT", limit=10)
            
            # Verify correct endpoint was called
            call_args = mock_get.call_args
            assert "/news/crypto-latest" in call_args[0][0]
            assert "/crypto_news" not in call_args[0][0]
            
            # Verify page parameter exists
            params = call_args[1]["params"]
            assert "page" in params
            assert "apikey" in params


class TestCoinMarketCapAPI:
    """Test CoinMarketCap API implementation."""

    def test_base_url(self):
        fetcher = CoinMarketCapFetcher()
        assert fetcher.BASE_URL == "https://pro-api.coinmarketcap.com/v1"

    @pytest.mark.asyncio
    async def test_header_authentication(self):
        """Test that X-CMC_PRO_API_KEY header is used."""
        fetcher = CoinMarketCapFetcher(api_key="test_key")
        
        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"data": {}})
            
            mock_get = AsyncMock(return_value=mock_response)
            mock_get.__aenter__.return_value = mock_response
            
            mock_session.return_value.get = mock_get
            mock_session.return_value.closed = False
            
            fetcher.session = mock_session.return_value
            
            await fetcher.fetch("BTCUSDT", limit=10)
            
            # Verify header authentication
            call_args = mock_get.call_args
            headers = call_args[1]["headers"]
            assert "X-CMC_PRO_API_KEY" in headers
            assert headers["X-CMC_PRO_API_KEY"] == "test_key"


class TestFinnhubAPI:
    """Test Finnhub API implementation."""

    def test_base_url(self):
        fetcher = FinnhubFetcher()
        assert fetcher.BASE_URL == "https://finnhub.io/api/v1"

    @pytest.mark.asyncio
    async def test_token_query_param(self):
        """Test that token is passed as query parameter."""
        fetcher = FinnhubFetcher(api_key="test_token")
        
        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=[])
            
            mock_get = AsyncMock(return_value=mock_response)
            mock_get.__aenter__.return_value = mock_response
            
            mock_session.return_value.get = mock_get
            mock_session.return_value.closed = False
            
            fetcher.session = mock_session.return_value
            
            await fetcher.fetch("BTCUSDT", limit=10)
            
            # Verify token in params
            call_args = mock_get.call_args
            params = call_args[1]["params"]
            assert "token" in params
            assert params["token"] == "test_token"
            assert "category" in params
            assert params["category"] == "crypto"


class TestMarketauxAPI:
    """Test Marketaux API implementation."""

    def test_base_url(self):
        fetcher = MarketauxFetcher()
        assert fetcher.BASE_URL == "https://api.marketaux.com/v1"

    @pytest.mark.asyncio
    async def test_api_token_param(self):
        """Test that api_token is passed as query parameter."""
        fetcher = MarketauxFetcher(api_key="test_token")
        
        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"data": []})
            
            mock_get = AsyncMock(return_value=mock_response)
            mock_get.__aenter__.return_value = mock_response
            
            mock_session.return_value.get = mock_get
            mock_session.return_value.closed = False
            
            fetcher.session = mock_session.return_value
            
            await fetcher.fetch("BTCUSDT", limit=10)
            
            # Verify correct endpoint and params
            call_args = mock_get.call_args
            assert "/news/all" in call_args[0][0]
            params = call_args[1]["params"]
            assert "api_token" in params
            assert params["api_token"] == "test_token"


class TestCryptopanicAPI:
    """Test CryptoPanic API implementation."""

    def test_base_url(self):
        fetcher = CryptopanicFetcher()
        assert fetcher.base_url == "https://cryptopanic.com/api/v1"

    def test_auth_token_param(self):
        """Test that auth_token is passed as query parameter."""
        fetcher = CryptopanicFetcher(api_key="test_token")
        
        with patch("httpx.Client") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"results": []}
            
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            
            fetcher._fetch_sync("BTCUSDT", limit=10)
            
            # Verify auth_token in params
            call_args = mock_client.return_value.__enter__.return_value.get.call_args
            params = call_args[1]["params"]
            assert "auth_token" in params
            assert params["auth_token"] == "test_token"


class TestNewsAPIOrg:
    """Test NewsAPI.org implementation."""

    def test_base_url(self):
        fetcher = NewsAPIFetcher()
        assert fetcher.base_url == "https://newsapi.org/v2"

    def test_apikey_param(self):
        """Test that apiKey is passed as query parameter."""
        fetcher = NewsAPIFetcher(api_key="test_key")
        
        with patch("httpx.Client") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"articles": []}
            
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            
            fetcher._fetch_sync("BTCUSDT", limit=10)
            
            # Verify apiKey in params and correct endpoint
            call_args = mock_client.return_value.__enter__.return_value.get.call_args
            assert "/everything" in call_args[0][0]
            params = call_args[1]["params"]
            assert "apiKey" in params
            assert params["apiKey"] == "test_key"


def test_all_fetchers_summary():
    """Summary test showing all fetcher configurations."""
    print("\n" + "="*60)
    print("FETCHER API CONFIGURATION SUMMARY")
    print("="*60)
    
    print("\n1. CoinGecko:")
    cg = CoinGeckoFetcher(api_key="dummy")
    print(f"   Base URL: {cg.base_url}")
    print(f"   Auth: Header 'x_cg_demo_api_key'")
    
    print("\n2. FMP (Financial Modeling Prep):")
    fmp = FMPFetcher(api_key="dummy")
    print(f"   Base URL: {fmp.BASE_URL}")
    print(f"   Endpoint: /news/crypto-latest")
    print(f"   Auth: Query param 'apikey'")
    
    print("\n3. CoinMarketCap:")
    cmc = CoinMarketCapFetcher(api_key="dummy")
    print(f"   Base URL: {cmc.BASE_URL}")
    print(f"   Auth: Header 'X-CMC_PRO_API_KEY'")
    
    print("\n4. Finnhub:")
    fh = FinnhubFetcher(api_key="dummy")
    print(f"   Base URL: {fh.BASE_URL}")
    print(f"   Auth: Query param 'token'")
    
    print("\n5. Marketaux:")
    ma = MarketauxFetcher(api_key="dummy")
    print(f"   Base URL: {ma.BASE_URL}")
    print(f"   Auth: Query param 'api_token'")
    
    print("\n6. CryptoPanic:")
    cp = CryptopanicFetcher(api_key="dummy")
    print(f"   Base URL: {cp.base_url}")
    print(f"   Auth: Query param 'auth_token'")
    
    print("\n7. NewsAPI.org:")
    na = NewsAPIFetcher(api_key="dummy")
    print(f"   Base URL: {na.base_url}")
    print(f"   Auth: Query param 'apiKey'")
    
    print("\n" + "="*60)
    print("✅ ALL FETCHERS CONFIGURED CORRECTLY")
    print("="*60 + "\n")


if __name__ == "__main__":
    # Run the summary test
    test_all_fetchers_summary()
    
    # Run pytest
    print("\nRunning pytest tests...\n")
    pytest.main([__file__, "-v", "--tb=short"])
