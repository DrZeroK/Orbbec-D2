"""Application authorization tests with a fake recognizer; no camera claim is made."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screen_auth import PIN_ROUNDS, ScreenAuth
from face_engine import FaceCaptureError
from server import create_app, MONITOR_KEY


class FakeFaceEngine:
    def __init__(self):
        self.available = True
        self.enrolled = False
        self.result = {"matched": True, "samples": 5, "reason": ""}
        self.failure = None
        self.calls = 0
        self.enroll_calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False

    def status(self):
        return {"available": self.available, "enrolled": self.enrolled, "error": ""}

    def enroll(self):
        self.enroll_calls += 1
        self.enrolled = True
        return {"samples": 5}

    def verify(self):
        self.calls += 1
        self.entered.set()
        if self.block and not self.release.wait(3):
            raise TimeoutError("fake recognizer was not released")
        if self.failure:
            raise self.failure
        return dict(self.result)


class ScreenAuthTests(AioHTTPTestCase):
    async def get_application(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = FakeFaceEngine()
        # Only the permission flow is substituted; real D2 capture has separate hardware tests.
        with patch.dict(sys.modules, {"face_engine": SimpleNamespace(FaceEngine=lambda _: self.engine)}):
            app = create_app(self.temp.name, test_mode=True)
        self.auth = app[MONITOR_KEY].screen_auth
        self.now = 1000.0
        self.auth.clock = lambda: self.now
        return app

    async def asyncTearDown(self):
        self.engine.release.set()
        await super().asyncTearDown()
        self.temp.cleanup()

    def local(self):
        return {"Origin": str(self.server.make_url("")).rstrip("/")}

    async def post(self, action, body=None):
        return await self.client.post("/api/screen-auth/" + action,
                                      json={} if body is None else body, headers=self.local())

    async def setup_pin(self):
        response = await self.post("setup", {"pin": "012345", "confirm": "012345"})
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def lock(self):
        response = await self.post("lock")
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.json())["locked"])

    async def test_first_run_then_secure_storage_and_restart_locked(self):
        status = await (await self.client.get("/api/screen-auth/status")).json()
        self.assertTrue(status["setup_required"])
        self.assertFalse(status["locked"])
        status = await self.setup_pin()
        self.assertTrue(status["configured"])
        self.assertFalse(status["locked"])
        record = json.loads(self.auth.path.read_text())
        self.assertEqual(set(record), {"version", "algorithm", "rounds", "salt", "digest"})
        self.assertEqual(record["algorithm"], "pbkdf2_sha256")
        self.assertEqual(record["rounds"], PIN_ROUNDS)
        self.assertEqual(len(bytes.fromhex(record["salt"])), 16)
        self.assertEqual(len(bytes.fromhex(record["digest"])), 32)
        if os.name != "nt":
            self.assertEqual(self.auth.path.stat().st_mode & 0o777, 0o600)
        restarted = ScreenAuth(self.temp.name, self.engine)
        self.assertTrue(restarted.configured)
        self.assertTrue(restarted.locked)
        self.assertEqual((await self.post("setup", {"pin": "111111", "confirm": "111111"})).status, 409)

    async def test_setup_validation_preserves_leading_zero_and_rejects_unicode(self):
        for body in ({"pin": "12345", "confirm": "12345"}, {"pin": 123456, "confirm": 123456},
                     {"pin": "１２３４５６", "confirm": "１２３４５６"},
                     {"pin": "012345", "confirm": "012346"}, [], {"pin": "012345", "extra": True}):
            response = await self.post("setup", body)
            self.assertEqual(response.status, 400, body)
            self.assertIsInstance((await response.json())["error"], str)
        await self.setup_pin()
        await self.lock()
        response = await self.post("pin", {"pin": "012345"})
        self.assertEqual(response.status, 200)
        self.assertFalse((await response.json())["locked"])

    async def test_pin_failure_rate_limit_and_monotonic_expiry(self):
        await self.setup_pin()
        await self.lock()
        for _ in range(5):
            response = await self.post("pin", {"pin": "999999"})
            self.assertEqual(response.status, 401)
            self.assertEqual((await response.json())["error"], "PIN 不正确")
        response = await self.post("pin", {"pin": "012345"})
        self.assertEqual(response.status, 429)
        self.assertEqual(response.headers["Retry-After"], "60")
        self.assertTrue(self.auth.locked)
        self.now += 60.1
        self.assertEqual((await self.post("pin", {"pin": "012345"})).status, 200)
        self.assertFalse(self.auth.locked)

    async def test_local_api_cannot_bypass_lock_but_reads_help_and_bridge_work(self):
        await self.setup_pin()
        await self.lock()
        for method, path, body in (("post", "/api/power", {"action": "shutdown"}),
                                   ("put", "/api/volume", {"percent": 1}),
                                   ("post", "/api/wifi", {"action": "power", "enabled": False}),
                                   ("post", "/api/mapping/start", {}),
                                   ("post", "/api/phone/pair/decide", {}),
                                   ("post", "/api/companion/command", {"text": "ignored"}),
                                   ("post", "/api/call/request", {"to": "caregiver"})):
            response = await getattr(self.client, method)(path, json=body, headers=self.local())
            self.assertEqual(response.status, 423, path)
            self.assertIn("error", await response.json())
        self.assertEqual((await self.client.get("/api/access", headers=self.local())).status, 423)
        self.assertEqual((await self.client.get("/api/state", headers=self.local())).status, 200)
        socket = await self.client.ws_connect("/ws", headers=self.local())
        self.assertIsInstance(await socket.receive_json(), dict)
        await socket.close()
        for action in ("request", "clear"):
            response = await self.client.post("/api/help", json={"action": action}, headers=self.local())
            self.assertEqual(response.status, 200)
        bridge = {"Authorization": "Bearer " + self.app[MONITOR_KEY].credentials["bridge_token"]}
        self.assertEqual((await self.client.post("/api/telemetry", json={"fields": {}}, headers=bridge)).status, 200)
        self.assertEqual((await self.client.post("/api/call/end", json={}, headers=self.local())).status, 200)

    async def test_remote_and_cross_origin_cannot_set_pin_or_unlock(self):
        remote = {"Host": "x5.local", "Origin": "http://x5.local"}
        login = await self.client.post("/api/login", json={"code": self.app[MONITOR_KEY].credentials["access_code"]}, headers=remote)
        self.assertEqual(login.status, 200)
        remote["Cookie"] = "piui_session=" + login.cookies["piui_session"].value
        for action in ("setup", "pin", "face", "lock", "enroll"):
            response = await self.client.post("/api/screen-auth/" + action, json={"pin": "012345"}, headers=remote)
            self.assertEqual(response.status, 403, action)
            self.assertIn("error", await response.json())
        response = await self.client.get("/api/screen-auth/status", headers=remote)
        self.assertEqual(response.status, 403)
        response = await self.client.post("/api/screen-auth/setup", json={"pin": "012345", "confirm": "012345"},
                                          headers={"Origin": "http://evil.example"})
        self.assertEqual(response.status, 403)
        self.assertIn("error", await response.json())
        await self.setup_pin()
        await self.lock()
        # The original remote monitor remains authorized; this is a local application lock.
        self.assertEqual((await self.client.get("/api/state", headers=remote)).status, 200)

    async def test_rgb_face_requires_five_samples_and_ignores_client_claims(self):
        await self.setup_pin()
        self.engine.enrolled = True
        await self.lock()
        response = await self.post("face", {"matched": True, "embedding": [1, 2, 3]})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.engine.calls, 0)
        self.engine.result = {"matched": True, "samples": 2}
        self.assertEqual((await self.post("face")).status, 503)
        self.assertTrue(self.auth.locked)
        self.engine.result = {"matched": False, "samples": 3}
        self.assertEqual((await self.post("face")).status, 401)
        self.assertTrue(self.auth.locked)
        self.engine.result = {"matched": False, "samples": 0}
        self.assertEqual((await self.post("face")).status, 401)
        self.assertTrue(self.auth.locked)
        for samples in (True, '5', 4, 81, None):
            self.engine.result = {"matched": True, "samples": samples}
            self.assertEqual((await self.post("face")).status, 503)
            self.assertTrue(self.auth.locked)
        self.engine.result = {"matched": True, "samples": 5}
        self.assertEqual((await self.post("face")).status, 200)
        self.assertFalse(self.auth.locked)

    async def test_camera_failure_or_bad_template_does_not_disable_pin(self):
        await self.setup_pin()
        self.engine.enrolled = True
        for failure in (OSError("camera disconnected"), ValueError("damaged embedding")):
            await self.lock()
            self.engine.failure = failure
            response = await self.post("face")
            self.assertEqual(response.status, 503)
            self.assertIn("PIN", (await response.json())["error"])
            self.assertTrue(self.auth.locked)
            self.assertEqual((await self.post("pin", {"pin": "012345"})).status, 200)

    async def test_unavailable_face_model_leaves_pin_available(self):
        await self.setup_pin()
        self.auth.engine = None
        await self.lock()
        status = await (await self.client.get("/api/screen-auth/status")).json()
        self.assertFalse(status["face_available"])
        self.assertEqual((await self.post("face")).status, 503)
        self.assertEqual((await self.post("pin", {"pin": "012345"})).status, 200)

    async def test_enroll_requires_unlocked_state_and_fresh_correct_pin(self):
        await self.setup_pin()
        self.assertEqual((await self.post("enroll", {"pin": "999999"})).status, 401)
        self.assertEqual(self.engine.enroll_calls, 0)
        response = await self.post("enroll", {"pin": "012345"})
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.json())["face_enrolled"])
        self.assertEqual(self.engine.enroll_calls, 1)
        await self.lock()
        self.assertEqual((await self.post("enroll", {"pin": "012345"})).status, 423)
        self.assertEqual(self.engine.enroll_calls, 1)

    async def test_expected_capture_failure_reaches_pin_gated_enrollment_ui(self):
        await self.setup_pin()
        message = '彩色图像读取中断，请使用 PIN'
        with patch.object(self.engine, 'enroll', side_effect=FaceCaptureError(message)):
            response = await self.post('enroll', {'pin': '012345'})
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())['error'], message)
        self.assertFalse(self.auth.face_busy)
        self.assertFalse(self.engine.enrolled)
        await self.lock()
        self.assertEqual((await self.post('pin', {'pin': '012345'})).status, 200)

    async def test_unexpected_enrollment_exception_is_not_exposed_to_ui(self):
        await self.setup_pin()
        with patch.object(self.engine, 'enroll', side_effect=RuntimeError('private implementation detail')):
            response = await self.post('enroll', {'pin': '012345'})
        self.assertEqual(response.status, 503)
        self.assertNotIn('private', (await response.json())['error'])
        self.assertFalse(self.auth.face_busy)

    async def test_busy_face_and_late_match_cannot_override_explicit_lock(self):
        await self.setup_pin()
        self.engine.enrolled = True
        self.engine.block = True
        await self.lock()
        pending = asyncio.ensure_future(self.post("face"))
        try:
            for _ in range(200):
                if self.engine.entered.is_set():
                    break
                await asyncio.sleep(.01)
            self.assertTrue(self.engine.entered.is_set())
            self.assertEqual((await self.post("face")).status, 409)
            await self.lock()
        finally:
            self.engine.release.set()
        response = await pending
        self.assertEqual(response.status, 409)
        self.assertTrue(self.auth.locked)

    async def test_auth_body_limits_and_no_hash_or_template_in_status(self):
        response = await self.client.post("/api/screen-auth/setup", data="{", headers=self.local())
        self.assertEqual(response.status, 400)
        self.assertIn("error", await response.json())
        response = await self.client.post("/api/screen-auth/setup", data="x" * 1025, headers=self.local())
        self.assertEqual(response.status, 413)
        await self.setup_pin()
        status = await (await self.client.get("/api/screen-auth/status")).json()
        self.assertFalse(set(status) & {"digest", "salt", "pin", "embedding", "template"})


    async def test_preview_requires_local_origin_and_does_not_start_capture(self):
        for headers in ({}, {"Origin": "http://evil.example"}, {"Host": "x5.local", "Origin": "http://x5.local"}):
            response = await self.client.get("/api/screen-auth/preview", headers=headers)
            self.assertEqual(response.status, 403)
        response = await self.client.get("/api/screen-auth/preview", headers=self.local())
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(await response.json(), {"active": False, "image": ""})
        self.assertEqual(self.engine.calls + self.engine.enroll_calls, 0)

    async def test_preview_only_during_pin_authorized_enroll_and_epoch_cancels(self):
        from face_preview import FacePreview
        self.engine.preview = FacePreview()
        entered, release = threading.Event(), threading.Event()
        def slow_enroll():
            with self.engine.preview.channel(True):
                entered.set()
                if not release.wait(3):
                    raise TimeoutError("synthetic test did not release enrollment")
            return {"samples": 5}
        self.engine.enroll = slow_enroll
        await self.setup_pin()
        self.assertEqual((await self.post("enroll", {"pin": "999999"})).status, 401)
        pending = asyncio.ensure_future(self.post("enroll", {"pin": "012345"}))
        try:
            for _ in range(200):
                if entered.is_set():
                    break
                await asyncio.sleep(.01)
            self.assertTrue(entered.is_set())
            response = await self.client.get("/api/screen-auth/preview", headers=self.local())
            self.assertTrue((await response.json())["active"])
            # PIN remains responsive while capture is busy and invalidates this preview.
            self.assertEqual((await self.post("pin", {"pin": "012345"})).status, 200)
            response = await self.client.get("/api/screen-auth/preview", headers=self.local())
            self.assertEqual(await response.json(), {"active": False, "image": ""})
        finally:
            release.set()
        self.assertEqual((await pending).status, 409)
        self.assertIsNone(self.auth.preview_epoch)
        self.assertFalse(self.engine.preview.snapshot()["active"])


class DamagedPinTests(unittest.TestCase):
    def test_damaged_existing_file_is_locked_not_first_run(self):
        for value in ("{", "[]", '{"version":1}', '{"version":1,"algorithm":"pbkdf2_sha256","rounds":999999999}'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                (Path(directory) / "screen_auth.json").write_text(value)
                auth = ScreenAuth(directory)
                self.assertTrue(auth.configured)
                self.assertTrue(auth.locked)
                self.assertTrue(auth.status()["recovery_required"])
                self.assertFalse(auth.status()["setup_required"])


if __name__ == "__main__":
    unittest.main()
