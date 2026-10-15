"""Single local touchscreen application lock; remote permissions remain separate.

Face-engine substitutes in unit tests verify this permission flow, not camera hardware.
"""
import asyncio
from collections import deque
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import time

from aiohttp import web
from face_engine import FaceCaptureError, valid_samples


PIN_ROUNDS = 600_000
PIN_PATTERN = re.compile(r"[0-9]{6}")
PREFIX = "/api/screen-auth/"
CALL_WHILE_LOCKED = frozenset({
    "/api/call/accept", "/api/call/end", "/api/call/up",
    "/api/call/rtc/offer", "/api/call/rtc/stats",
})


class AuthError(Exception):
    def __init__(self, status, message, retry_after=0):
        self.status, self.message, self.retry_after = status, message, retry_after


def error_response(status, message, retry_after=0):
    headers = {"Cache-Control": "no-store"}
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return web.json_response({"error": message}, status=status, headers=headers)


async def body_fields(request, allowed):
    if request.content_length and request.content_length > 1024:
        raise AuthError(413, "认证请求内容过长")
    try:
        raw = await request.read()
        if len(raw) > 1024:
            raise AuthError(413, "认证请求内容过长")
        body = json.loads(raw) if raw else {}
    except (ValueError, UnicodeError):
        raise AuthError(400, "请求内容不是有效 JSON")
    if not isinstance(body, dict) or set(body) - set(allowed):
        raise AuthError(400, "认证请求字段无效")
    return body


def validate_pin(pin):
    if not isinstance(pin, str) or not PIN_PATTERN.fullmatch(pin):
        raise AuthError(400, "PIN 应为六位数字")


class ScreenAuth:
    def __init__(self, data_dir, engine=None, clock=time.monotonic):
        self.path = Path(data_dir) / "screen_auth.json"
        self.engine, self.clock = engine, clock
        self.record, self.pin_error = None, ""
        self.pin_busy = self.face_busy = False
        self.preview_epoch = None
        self.epoch = 0
        self.attempts = deque()
        self._load()
        self.locked = self.configured

    @property
    def configured(self):
        return self.record is not None or bool(self.pin_error)

    def _load(self):
        try:
            if self.path.stat().st_size > 4096:
                raise ValueError("oversized PIN record")
            record = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or type(record.get("version")) is not int or record["version"] != 1 or record.get("algorithm") != "pbkdf2_sha256":
                raise ValueError("invalid PIN record")
            rounds = record.get("rounds")
            if isinstance(rounds, bool) or not isinstance(rounds, int) or not PIN_ROUNDS <= rounds <= 2_000_000:
                raise ValueError("invalid PIN work factor")
            if not isinstance(record.get("salt"), str) or not re.fullmatch("[a-f0-9]{32}", record["salt"]):
                raise ValueError("invalid salt")
            if not isinstance(record.get("digest"), str) or not re.fullmatch("[a-f0-9]{64}", record["digest"]):
                raise ValueError("invalid digest")
            self.record = record
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            # A damaged configured file must never become an unprotected first-run setup.
            self.pin_error = "PIN 配置损坏，请在本机维护"

    def _write_pin(self, pin):
        salt = secrets.token_bytes(16)
        record = {"version": 1, "algorithm": "pbkdf2_sha256", "rounds": PIN_ROUNDS,
                  "salt": salt.hex(), "digest": hashlib.pbkdf2_hmac("sha256", pin.encode("ascii"), salt, PIN_ROUNDS).hex()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp-" + secrets.token_hex(8))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return record

    def _retry_after(self):
        now = self.clock()
        while self.attempts and self.attempts[0] <= now - 60:
            self.attempts.popleft()
        return max(1, math.ceil(self.attempts[0] + 60 - now)) if len(self.attempts) >= 5 else 0

    def _face_status(self):
        if self.engine is not None:
            try:
                status = self.engine.status()
                if isinstance(status, dict):
                    return {"available": status.get("available") is True,
                            "enrolled": status.get("enrolled") is True,
                            "error": str(status.get("error") or "")[:180]}
            except Exception:
                pass
        return {"available": False, "enrolled": False, "error": "人脸服务暂不可用，可使用 PIN"}

    def status(self):
        face = self._face_status()
        return {"configured": self.configured, "setup_required": not self.configured,
                "locked": self.locked, "face_available": face["available"],
                "face_enrolled": face["enrolled"], "busy": self.pin_busy or self.face_busy,
                "retry_after": self._retry_after(), "recovery_required": bool(self.pin_error),
                "error": self.pin_error or face["error"],
                "face_mode": "rgb-only", "face_calibration_source": "none"}

    def _require_configured(self):
        if self.pin_error:
            raise AuthError(503, self.pin_error)
        if not self.configured:
            raise AuthError(409, "请先在触屏设置 PIN")

    def _matches_pin(self, pin):
        record = self.record
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode("ascii"), bytes.fromhex(record["salt"]), record["rounds"])
        return hmac.compare_digest(digest, bytes.fromhex(record["digest"]))

    async def _verify_pin(self, pin):
        self._require_configured()
        validate_pin(pin)
        retry = self._retry_after()
        if retry:
            raise AuthError(429, "PIN 尝试过于频繁，请稍后再试", retry)
        if self.pin_busy:
            raise AuthError(409, "正在验证 PIN，请稍后再试")
        self.attempts.append(self.clock())
        self.pin_busy = True
        try:
            matched = await asyncio.to_thread(self._matches_pin, pin)
        finally:
            self.pin_busy = False
        if not matched:
            raise AuthError(401, "PIN 不正确")
        self.attempts.clear()

    async def get_status(self, request):
        return self.status()

    async def get_preview(self, request):
        if self.locked or not self.face_busy or self.preview_epoch != self.epoch:
            return {"active": False, "image": ""}
        return self.engine.preview.snapshot()

    async def setup(self, request):
        body = await body_fields(request, {"pin", "confirm"})
        if self.configured:
            raise AuthError(409, "已设置 PIN，不能重复初始化")
        if self.pin_busy:
            raise AuthError(409, "正在保存 PIN，请稍后再试")
        validate_pin(body.get("pin"))
        validate_pin(body.get("confirm"))
        if not hmac.compare_digest(body["pin"], body["confirm"]):
            raise AuthError(400, "两次输入的 PIN 不一致")
        self.pin_busy = True
        try:
            self.record = await asyncio.to_thread(self._write_pin, body["pin"])
        except OSError:
            # A failed directory fsync may follow a successful replace: reload fail-closed.
            self._load()
            self.locked = self.configured
            raise AuthError(503, "PIN 保存失败，请重试或在本机维护")
        finally:
            self.pin_busy = False
        self.locked = False
        self.epoch += 1
        return {"ok": True, **self.status()}

    async def pin(self, request):
        body = await body_fields(request, {"pin"})
        epoch = self.epoch
        await self._verify_pin(body.get("pin"))
        if epoch != self.epoch:
            raise AuthError(409, "屏幕锁状态已改变，请重新验证")
        self.locked = False
        self.epoch += 1
        return {"ok": True, **self.status()}

    async def lock(self, request):
        await body_fields(request, set())
        self._require_configured()
        self.locked = True
        self.epoch += 1
        return {"ok": True, **self.status()}

    def _admit_face(self, enrolling=False):
        self._require_configured()
        if self.face_busy:
            raise AuthError(409, "正在处理人脸，请稍后再试")
        status = self._face_status()
        if not status["available"]:
            raise AuthError(503, "人脸相机或模型不可用，请使用 PIN")
        if not enrolling and not status["enrolled"]:
            raise AuthError(409, "请先解锁屏幕并录入人脸")

    async def face(self, request):
        await body_fields(request, set())
        self._admit_face()
        epoch = self.epoch
        self.face_busy = True
        try:
            try:
                result = await asyncio.to_thread(self.engine.verify)
            except Exception:
                raise AuthError(503, "人脸识别暂不可用，请使用 PIN")
            if epoch != self.epoch:
                raise AuthError(409, "屏幕锁状态已改变，本次识别已取消")
            if not isinstance(result, dict):
                raise AuthError(503, "人脸服务响应无效，请使用 PIN")
            if result.get("matched") is not True:
                raise AuthError(401, "人脸不匹配，请重试或使用 PIN")
            if not valid_samples(result):
                raise AuthError(503, "未取得足够的连续彩色人脸画面，请使用 PIN")
            self.locked = False
            self.epoch += 1
            self.face_busy = False
            return {"ok": True, **self.status()}
        finally:
            self.face_busy = False

    async def enroll(self, request):
        body = await body_fields(request, {"pin"})
        self._require_configured()
        if self.locked:
            raise AuthError(423, "请先解锁屏幕，再录入人脸")
        epoch = self.epoch
        await self._verify_pin(body.get("pin"))
        if self.locked or epoch != self.epoch:
            raise AuthError(409, "屏幕已重新锁定，请重新验证 PIN")
        self._admit_face(enrolling=True)
        self.face_busy = True
        self.preview_epoch = epoch
        try:
            try:
                result = await asyncio.to_thread(self.engine.enroll)
            except FaceCaptureError as exc:
                raise AuthError(503, str(exc)[:160]) from exc
            except Exception:
                raise AuthError(503, "人脸录入失败，请保持 PIN 解锁并重试")
            if epoch != self.epoch:
                raise AuthError(409, "屏幕已重新锁定，请解锁后查看人脸录入状态")
            if not valid_samples(result):
                raise AuthError(503, "彩色人脸录入画面不足，请重试或使用 PIN")
            self.face_busy = False
            return {"ok": True, **self.status()}
        finally:
            self.preview_epoch = None
            self.face_busy = False

    async def gate(self, request):
        if not self.locked or request.path.startswith(PREFIX):
            return None
        if request.method in ("GET", "HEAD"):
            return error_response(423, "屏幕已锁定，请先解锁") if request.path == "/api/access" else None
        if request.method == "POST" and request.path in CALL_WHILE_LOCKED:
            return None
        if request.method == "POST" and request.path == "/api/help":
            try:
                body = await request.json()
            except (ValueError, UnicodeError):
                return error_response(400, "请求内容不是有效 JSON")
            if isinstance(body, dict) and body.get("action") in ("request", "clear"):
                return None
        return error_response(423, "屏幕已锁定，请先解锁")


def install(app, monitor_key, *, is_device, same_origin):
    monitor = app[monitor_key]
    try:
        # Construction/status only inspect local model files; capture occurs inside endpoints.
        from face_engine import FaceEngine
        engine = FaceEngine(monitor.root)
    except Exception:
        engine = None
    auth = monitor.screen_auth = ScreenAuth(monitor.root, engine)

    def endpoint(handler):
        async def route(request):
            if not is_device(request):
                return error_response(403, "屏幕解锁仅允许轮椅触屏本机操作")
            if (request.method != "GET" or request.path == PREFIX + "preview") and not same_origin(request):
                return error_response(403, "请求来源不匹配")
            try:
                return web.json_response(await handler(request), headers={"Cache-Control": "no-store"})
            except AuthError as error:
                return error_response(error.status, error.message, error.retry_after)
        return route

    app.add_routes([web.get(PREFIX + "status", endpoint(auth.get_status)),
                    web.get(PREFIX + "preview", endpoint(auth.get_preview)),
                    web.post(PREFIX + "setup", endpoint(auth.setup)),
                    web.post(PREFIX + "pin", endpoint(auth.pin)),
                    web.post(PREFIX + "face", endpoint(auth.face)),
                    web.post(PREFIX + "lock", endpoint(auth.lock)),
                    web.post(PREFIX + "enroll", endpoint(auth.enroll))])
    return auth
