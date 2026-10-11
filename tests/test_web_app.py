import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.posture import PostureMetrics
from web_app import StudyState, create_handler


class FakeAnalyzer:
    def __init__(self, _model_path):
        self.closed = False

    def process(self, _frame, _now):
        return PostureMetrics("Slouching", 12.0, 1.2, 70.0, True, True, (12.0, 1.2, 0.0, 0.1))

    def close(self):
        self.closed = True


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "sessions.db"
        self.state = StudyState(
            self.database_path,
            Path(self.temporary_directory.name) / "missing-model.joblib",
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(self.state))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        if self.state.status()["active"]:
            self.state.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def request(self, path, method="GET", body=None, headers=None):
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers or {},
            method=method,
        )
        with urlopen(request, timeout=5) as response:
            return response.status, response.headers, response.read()

    def test_serves_dashboard_and_status(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"Find your", body)

        status, _, body = self.request("/api/status")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["active"])

    def test_start_and_frame_processing_and_label_capture(self):
        with patch("web_app.PostureAnalyzer", FakeAnalyzer), patch(
            "web_app._decode_frame", return_value=object()
        ):
            status, _, body = self.request("/api/session/start", method="POST")
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["active"])

            status, _, body = self.request(
                "/api/frame",
                method="POST",
                body=b"fake-jpeg",
                headers={"Content-Type": "image/jpeg"},
            )
            self.assertEqual(status, 200)
            metrics = json.loads(body)
            self.assertEqual(metrics["metrics"]["status"], "Slouching")
            self.assertEqual(metrics["alerts"], [])

            status, _, body = self.request(
                "/api/label",
                method="POST",
                body=json.dumps({"label": "Slouching"}).encode(),
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["sample_counts"]["Slouching"], 1)

            status, _, body = self.request("/api/session/stop", method="POST")
            self.assertEqual(status, 200)
            self.assertFalse(json.loads(body)["active"])
            self.assertEqual(json.loads(body)["frame_count"], 1)
            self.assertTrue(self.database_path.exists())

    def test_rejects_invalid_frame_content_type(self):
        status, _, _ = self.request("/api/session/start", method="POST")
        self.assertEqual(status, 200)
        with self.assertRaises(HTTPError) as error:
            self.request(
                "/api/frame",
                method="POST",
                body=b"image",
                headers={"Content-Type": "text/plain"},
            )
        self.assertEqual(error.exception.code, 400)
        self.request("/api/session/stop", method="POST")


if __name__ == "__main__":
    unittest.main()
