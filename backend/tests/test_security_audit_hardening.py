import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import app.core.auth as auth_mod
from app.main import app


class TestPhase0SecurityAuditHardening(unittest.TestCase):
    """Automated verification tests for Phase 0 Security & Architecture Hardening."""

    def setUp(self):
        self._orig_token = auth_mod._SESSION_TOKEN
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.token_file = self.data_dir / "session_token"

    def tearDown(self):
        self.tmp.cleanup()
        auth_mod._SESSION_TOKEN = self._orig_token

    # --- Phase 0.1: Duplicate Route Mounting ---
    def test_agent_routes_not_duplicated(self):
        """Verify agent_router is mounted at /api/agents and NOT duplicated at /api/ai."""
        openapi_schema = app.openapi()
        all_paths = list(openapi_schema.get("paths", {}).keys())
        
        # /api/agents/jobs should exist
        self.assertIn("/api/agents/jobs", all_paths)
        self.assertIn("/api/agents/plan", all_paths)
        self.assertIn("/api/agents/audit", all_paths)
        self.assertIn("/api/agents/coder-mode/execute", all_paths)

        # /api/ai/jobs or /api/ai/plan alias duplicate routes must NOT exist
        self.assertNotIn("/api/ai/jobs", all_paths)
        self.assertNotIn("/api/ai/plan", all_paths)
        self.assertNotIn("/api/ai/audit", all_paths)
        self.assertNotIn("/api/ai/coder-mode/execute", all_paths)

        # Check total occurrences of each (route.path, method) pair to ensure zero duplicate route handlers
        route_method_pairs = []
        for r in app.routes:
            if hasattr(r, "path") and hasattr(r, "methods"):
                for m in r.methods:
                    route_method_pairs.append((r.path, m))
        
        counts = {}
        for pair in route_method_pairs:
            counts[pair] = counts.get(pair, 0) + 1
        
        duplicates = {pair: count for pair, count in counts.items() if count > 1}
        self.assertEqual(duplicates, {}, f"Found duplicate (path, method) routes in app: {duplicates}")

    # --- Phase 0.2: DNS Rebinding Wildcard CORS Elimination ---
    def test_auth_401_no_wildcard_cors(self):
        """Verify 401 unauthenticated response does NOT contain Access-Control-Allow-Origin: *."""
        client = TestClient(app)
        res = client.get(
            "/api/workspaces",
            headers={"Origin": "http://evil.com", "Authorization": "Bearer bad-token"}
        )
        self.assertEqual(res.status_code, 401)
        # Must not contain wildcard allow origin
        self.assertNotEqual(res.headers.get("access-control-allow-origin"), "*")
        self.assertNotIn("access-control-allow-origin", res.headers)
        self.assertEqual(res.headers.get("www-authenticate"), "Bearer")

    # --- Phase 0.3: CORS Configuration Simplification ---
    def test_cors_arbitrary_localhost_ports_and_evil_origin(self):
        """Verify arbitrary localhost ports pass CORS and external domains are blocked."""
        client = TestClient(app)

        # Test random high port localhost (allowed)
        res_allowed = client.options(
            "/api/workspaces",
            headers={
                "Origin": "http://localhost:9999",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            }
        )
        self.assertEqual(res_allowed.status_code, 200)
        self.assertEqual(res_allowed.headers.get("access-control-allow-origin"), "http://localhost:9999")

        # Test 127.0.0.1 with random port (allowed)
        res_ip = client.options(
            "/api/workspaces",
            headers={
                "Origin": "http://127.0.0.1:8765",
                "Access-Control-Request-Method": "GET",
            }
        )
        self.assertEqual(res_ip.status_code, 200)
        self.assertEqual(res_ip.headers.get("access-control-allow-origin"), "http://127.0.0.1:8765")

        # Test evil.com origin (blocked)
        res_blocked = client.options(
            "/api/workspaces",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            }
        )
        self.assertNotEqual(res_blocked.headers.get("access-control-allow-origin"), "http://evil.com")

    # --- Phase 0.4: Session Token Expiry & Rotation ---
    def test_token_expiry_and_rotation(self):
        """Verify session token uses JSON format, checks 24h expiry, and handles legacy formats safely."""
        with patch("app.core.auth._token_file_path", return_value=self.token_file),              patch("builtins.print"):
            
            # 1. Fresh generation produces valid JSON with 24h TTL
            auth_mod._SESSION_TOKEN = None
            token1 = auth_mod.generate_and_store_token()
            self.assertTrue(self.token_file.exists())
            
            raw1 = self.token_file.read_text(encoding="utf-8")
            data1 = json.loads(raw1)
            self.assertEqual(data1["token"], token1)
            self.assertIn("created_at", data1)
            self.assertIn("expires_at", data1)
            self.assertAlmostEqual(data1["expires_at"] - data1["created_at"], 24 * 3600.0, delta=2.0)
            
            # 2. Re-loading valid unexpired token reuses it
            loaded1 = auth_mod.load_token()
            self.assertEqual(loaded1, token1)

            # 3. Expired token in file triggers automatic deletion and replacement
            data_expired = {
                "token": token1,
                "created_at": time.time() - 100000,
                "expires_at": time.time() - 1000, # Expired in past
            }
            self.token_file.write_text(json.dumps(data_expired), encoding="utf-8")
            auth_mod._SESSION_TOKEN = None
            
            self.assertIsNone(auth_mod.load_token())
            self.assertFalse(self.token_file.exists(), "Expired token file must be deleted upon expiration")
            
            # Generate new token after expiration
            token2 = auth_mod.generate_and_store_token()
            self.assertNotEqual(token1, token2)
            self.assertEqual(len(token2), 64)

            # 4. Backward compatibility: Legacy plain-text token from v3.0.0 is treated as expired without crashing
            self.token_file.write_text("a" * 64, encoding="utf-8")
            auth_mod._SESSION_TOKEN = None
            
            legacy_load = auth_mod.load_token()
            self.assertIsNone(legacy_load, "Legacy plain-text token must be treated as expired")
            self.assertFalse(self.token_file.exists(), "Legacy file must be removed for rotation")

            # Generating after legacy file creates new valid JSON
            token3 = auth_mod.generate_and_store_token()
            self.assertTrue(self.token_file.exists())
            data3 = json.loads(self.token_file.read_text(encoding="utf-8"))
            self.assertEqual(data3["token"], token3)

    # --- Phase 0.5: Rate-Limit Error Generation ---
    def test_error_rate_limiting(self):
        """Verify global exception handler rate-limits 500 error generation beyond 100 errors in 60s."""
        test_app = FastAPI()
        
        from app.main import (
            _error_window,
            _error_window_lock,
            _ERROR_RATE_LIMIT_MAX,
            global_exception_handler,
        )

        test_app.add_exception_handler(Exception, global_exception_handler)

        @test_app.get("/trigger-error")
        async def trigger_error():
            raise RuntimeError("Simulated error for rate limit test")

        with _error_window_lock:
            _error_window.clear()

        client = TestClient(test_app, raise_server_exceptions=False)

        # First 100 requests trigger standard 500 errors with error_id
        for i in range(100):
            res = client.get("/trigger-error")
            self.assertEqual(res.status_code, 500)
            data = res.json()
            self.assertEqual(data.get("error"), "Internal Server Error")
            self.assertIn("error_id", data)

        # Requests 101-150 must receive rate-limited response
        for i in range(101, 151):
            res = client.get("/trigger-error")
            self.assertEqual(res.status_code, 500)
            data = res.json()
            self.assertEqual(data.get("error"), "Rate limited")
            self.assertNotIn("error_id", data)

        with _error_window_lock:
            _error_window.clear()


if __name__ == "__main__":
    unittest.main()
