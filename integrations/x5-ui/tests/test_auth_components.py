"""PIN fallback and late-result boundaries; no server, camera or real credentials."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from screen_auth import AuthError, ScreenAuth


class Request:
    def __init__(self, value):
        self.raw = json.dumps(value).encode()
        self.content_length = len(self.raw)

    async def read(self):
        return self.raw


class AuthComponentsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = Mock()
        self.engine.status.return_value = {'available': True, 'enrolled': True, 'error': ''}
        self.auth = ScreenAuth(self.directory.name, self.engine)
        await self.auth.setup(Request({'pin': '012345', 'confirm': '012345'}))

    async def test_restart_locked_and_camera_failure_keeps_pin(self):
        fresh = ScreenAuth(self.directory.name, self.engine)
        self.assertTrue(fresh.locked)
        self.auth.locked = True
        self.engine.verify.side_effect = OSError('synthetic disconnected camera')
        with self.assertRaises(AuthError):
            await self.auth.face(Request({}))
        self.assertTrue(self.auth.locked)
        await self.auth.pin(Request({'pin': '012345'}))
        self.assertFalse(self.auth.locked)

    async def test_false_match_and_invalid_samples_stay_locked(self):
        for result in ({'matched': False, 'samples': 5}, {'matched': True, 'samples': True},
                       {'matched': True, 'samples': 4}):
            self.auth.locked = True
            self.engine.verify.return_value = result
            with self.assertRaises(AuthError):
                await self.auth.face(Request({}))
            self.assertTrue(self.auth.locked)

    async def test_late_match_cannot_override_new_lock(self):
        loop = asyncio.get_running_loop()
        entered, release = asyncio.Event(), __import__('threading').Event()
        def verify():
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise TimeoutError('synthetic timeout')
            return {'matched': True, 'samples': 5}
        self.engine.verify.side_effect = verify
        pending = asyncio.create_task(self.auth.face(Request({})))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            await self.auth.lock(Request({}))
        finally:
            release.set()
        with self.assertRaises(AuthError):
            await pending
        self.assertTrue(self.auth.locked)

    async def test_damaged_pin_cannot_reset_to_first_run(self):
        (Path(self.directory.name) / 'screen_auth.json').write_text('{', encoding='utf8')
        broken = ScreenAuth(self.directory.name)
        self.assertTrue(broken.configured)
        self.assertTrue(broken.locked)
        self.assertTrue(broken.status()['recovery_required'])
        self.assertFalse(broken.status()['setup_required'])


if __name__ == '__main__':
    unittest.main()
