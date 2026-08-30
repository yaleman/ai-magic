import importlib.util
import json
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cloudflare_purge_cache.py"
spec = importlib.util.spec_from_file_location("cloudflare_purge_cache", SCRIPT)
if not spec or not spec.loader:
    raise ImportError(f"Cannot load module from {SCRIPT}")
cloudflare_purge_cache = importlib.util.module_from_spec(spec)
sys.modules["cloudflare_purge_cache"] = cloudflare_purge_cache

spec.loader.exec_module(cloudflare_purge_cache)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        pass


class RecordingOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=30):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CloudflarePurgeCacheTests(unittest.TestCase):
    def test_requires_cloudflare_api_token(self):
        with self.assertRaisesRegex(SystemExit, "CLOUDFLARE_API_TOKEN is not set"):
            cloudflare_purge_cache.main(["example.com"], env={})

    def test_purges_hostname_for_exact_zone_name(self):
        opener = RecordingOpener(
            [
                FakeResponse(
                    {
                        "success": True,
                        "result": [
                            {"id": "zone-123", "name": "example.com"},
                        ],
                    }
                ),
                FakeResponse({"success": True, "result": {"id": "purge-456"}}),
            ]
        )

        result = cloudflare_purge_cache.purge_hostname_cache(
            "example.com",
            "token-abc",
            opener=opener,
        )

        self.assertEqual(result.zone_id, "zone-123")
        self.assertEqual(result.zone_name, "example.com")
        self.assertEqual(len(opener.requests), 2)
        lookup, purge = opener.requests
        self.assertEqual(lookup.get_method(), "GET")
        self.assertIn("name=example.com", lookup.full_url)
        self.assertEqual(
            lookup.get_header("Authorization"),
            "Bearer token-abc",
        )
        self.assertEqual(purge.get_method(), "POST")
        self.assertTrue(purge.full_url.endswith("/zones/zone-123/purge_cache"))
        self.assertEqual(
            json.loads(purge.data.decode("utf-8")), {"hosts": ["example.com"]}
        )

    def test_purges_subdomain_using_parent_zone(self):
        opener = RecordingOpener(
            [
                FakeResponse({"success": True, "result": []}),
                FakeResponse(
                    {
                        "success": True,
                        "result": [
                            {"id": "zone-789", "name": "yaleman.org"},
                        ],
                    }
                ),
                FakeResponse({"success": True, "result": {"id": "purge-abc"}}),
            ]
        )

        result = cloudflare_purge_cache.purge_hostname_cache(
            "plzyes.yaleman.org",
            "token-abc",
            opener=opener,
        )

        self.assertEqual(result.zone_id, "zone-789")
        self.assertEqual(result.zone_name, "yaleman.org")
        self.assertEqual(result.hostname, "plzyes.yaleman.org")
        self.assertEqual(len(opener.requests), 3)
        self.assertIn("name=plzyes.yaleman.org", opener.requests[0].full_url)
        self.assertIn("name=yaleman.org", opener.requests[1].full_url)
        self.assertEqual(
            json.loads(opener.requests[2].data.decode("utf-8")),
            {"hosts": ["plzyes.yaleman.org"]},
        )

    def test_rejects_unknown_zone(self):
        opener = RecordingOpener(
            [
                FakeResponse({"success": True, "result": []}),
            ]
        )

        with self.assertRaisesRegex(
            cloudflare_purge_cache.CloudflareError,
            "No Cloudflare zone found for example.com or its parent domains",
        ):
            cloudflare_purge_cache.purge_hostname_cache(
                "example.com", "token-abc", opener=opener
            )

    def test_reports_cloudflare_api_errors(self):
        error_body = json.dumps(
            {
                "success": False,
                "errors": [{"code": 9109, "message": "Unauthorized"}],
            }
        ).encode("utf-8")
        opener = RecordingOpener(
            [
                HTTPError(
                    "https://api.cloudflare.com/client/v4/zones",
                    403,
                    "Forbidden",
                    hdrs=None,  # ty: ignore[invalid-argument-type]
                    fp=FakeResponse(
                        {"success": False, "errors": [{"message": "Unauthorized"}]}
                    ),  # ty: ignore[invalid-argument-type]
                )
            ]
        )
        opener.responses[0].fp.read = lambda: error_body

        with self.assertRaisesRegex(
            cloudflare_purge_cache.CloudflareError, "Unauthorized"
        ):
            cloudflare_purge_cache.purge_hostname_cache(
                "example.com", "token-abc", opener=opener
            )


if __name__ == "__main__":
    unittest.main()
