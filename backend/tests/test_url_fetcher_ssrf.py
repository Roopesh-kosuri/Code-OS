from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from app.features.ai.url_fetcher import (
    PinnedTransport,
    validate_hostname_safe,
    is_safe_ip,
)


@pytest.mark.asyncio
async def test_pinned_transport_rewrites_host_to_pinned_ip():
    transport = PinnedTransport(pinned_ip="93.184.216.34", original_host="example.com")
    request = httpx.Request("GET", "https://example.com/api/data")

    # Mock super().handle_async_request
    mock_resp = httpx.Response(200, request=request)
    with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", new_callable=AsyncMock) as mock_handle:
        mock_handle.return_value = mock_resp
        await transport.handle_async_request(request)

        # Verify host in URL was rewritten to pinned IP
        assert request.url.host == "93.184.216.34"
        # Verify Host header is preserved
        assert request.headers["Host"] == "example.com"


def test_metadata_ip_blocked():
    assert is_safe_ip("169.254.169.254") is False
    with patch("app.features.ai.url_fetcher.resolve_hostname_ips", return_value=["169.254.169.254"]):
        with pytest.raises(ValueError, match="SSRF blocked"):
            validate_hostname_safe("cloud-metadata.internal")


def test_loopback_ip_blocked():
    assert is_safe_ip("127.0.0.1") is False
    with patch("app.features.ai.url_fetcher.resolve_hostname_ips", return_value=["127.0.0.1"]):
        with pytest.raises(ValueError, match="SSRF blocked"):
            validate_hostname_safe("localhost")
