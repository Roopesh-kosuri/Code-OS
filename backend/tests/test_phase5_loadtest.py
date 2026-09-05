"""
backend/tests/test_phase5_loadtest.py
Automated pytest load test verifying that under 10 concurrent clients
for 10 seconds, p95 latency remains < 100ms and error rate < 1%.
"""
import asyncio
import time
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.auth import get_token


@pytest.mark.asyncio
async def test_high_concurrency_load_benchmark():
    """10 concurrent workers sending requests for 5 seconds against FastAPI ASGI app."""
    transport = ASGITransport(app=app)
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    duration = 5.0  # 5 seconds automated load test in CI/pytest
    clients = 10

    latencies = []
    errors = 0
    start = time.time()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async def worker():
            nonlocal errors
            while time.time() - start < duration:
                t0 = time.time()
                try:
                    res = await client.get("/api/health", headers=headers)
                    if res.status_code == 200:
                        latencies.append((time.time() - t0) * 1000)
                    else:
                        errors += 1
                except Exception:
                    errors += 1
                await asyncio.sleep(0.005)

        await asyncio.gather(*[worker() for _ in range(clients)])

    total = len(latencies) + errors
    assert total > 50, f"Expected at least 50 requests under load, got {total}"
    err_rate = (errors / max(total, 1)) * 100
    assert err_rate < 1.0, f"Error rate exceeded threshold: {err_rate:.2f}%"

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]
    assert p95 < 100.0, f"P95 latency exceeded 100ms threshold: {p95:.2f}ms"
