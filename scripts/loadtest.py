"""
scripts/loadtest.py
High-concurrency load testing harness for CODE OS backend API.
Simulates 50 concurrent async clients against /api/health over a configurable duration.
Outputs request volume, error rate, P50, P95, and P99 latency percentiles.
"""
import argparse
import asyncio
import statistics
import time
import aiohttp


async def run_load_test(url: str, clients: int, duration: int):
    print(f"Starting Load Test: {clients} concurrent clients, duration={duration}s against {url}")
    latencies: list[float] = []
    errors = 0
    start = time.time()

    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def worker():
            nonlocal errors
            while time.time() - start < duration:
                t0 = time.time()
                try:
                    async with session.get(url) as resp:
                        await resp.read()
                        if resp.status == 200:
                            latencies.append((time.time() - t0) * 1000)
                        else:
                            errors += 1
                except Exception:
                    errors += 1
                await asyncio.sleep(0.01)

        await asyncio.gather(*[worker() for _ in range(clients)])

    total_reqs = len(latencies) + errors
    print("\n═══════════════════════════════════════════════════════════════")
    print("CODE OS LOAD TEST BENCHMARK RESULTS")
    print("═══════════════════════════════════════════════════════════════")
    print(f"Target URL:        {url}")
    print(f"Concurrent Clients:{clients}")
    print(f"Duration:          {duration}s")
    print(f"Total Requests:    {total_reqs}")
    print(f"Successful Reqs:   {len(latencies)}")
    print(f"Failed Requests:   {errors}")
    err_rate = (errors / max(total_reqs, 1)) * 100
    print(f"Error Rate:        {err_rate:.2f}%")

    if latencies:
        latencies.sort()
        p50 = latencies[int(len(latencies) * 0.50)]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        avg = statistics.mean(latencies)
        rps = len(latencies) / duration
        print(f"Throughput:        {rps:.1f} req/s")
        print(f"Average Latency:   {avg:.2f}ms")
        print(f"P50 Latency:       {p50:.2f}ms")
        print(f"P95 Latency:       {p95:.2f}ms")
        print(f"P99 Latency:       {p99:.2f}ms")
    print("═══════════════════════════════════════════════════════════════\n")


def main():
    parser = argparse.ArgumentParser(description="CODE OS Load Tester")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/health", help="Target endpoint")
    parser.add_argument("--clients", type=int, default=50, help="Number of concurrent clients")
    parser.add_argument("--duration", type=int, default=30, help="Duration in seconds (default 30)")
    args = parser.parse_args()

    asyncio.run(run_load_test(args.url, args.clients, args.duration))


if __name__ == "__main__":
    main()
