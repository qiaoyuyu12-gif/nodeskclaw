"""登录接口限流：同一 IP 或同一账号在窗口期内失败次数超限则拒绝请求。

进程内内存滑动窗口计数器，写法参照
app/services/runtime/messaging/middlewares/rate_limit.py，不引入 Redis。
K8s 生产多副本部署下计数器不跨 Pod 共享（实际上限接近 副本数 x MAX_ATTEMPTS），
但足以挡住基础暴力破解脚本；后续如需跨副本精确限流可迁移到 Redis。
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request

from app.core.exceptions import AppException

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60

# key -> 该 key 在窗口期内的失败时间戳列表（time.monotonic()）
_failure_counters: dict[str, list[float]] = defaultdict(list)


class TooManyLoginAttemptsError(AppException):
    def __init__(self):
        super().__init__(
            code=42900,
            message="尝试次数过多，请 1 分钟后再试",
            status_code=429,
            message_key="errors.common.too_many_attempts",
        )


def get_client_ip(request: Request) -> str:
    """优先取 X-Forwarded-For 第一段（portal nginx / K8s ingress 场景会经过反向代理），
    否则退回直连的 request.client.host。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune(key: str, now: float) -> list[float]:
    timestamps = _failure_counters[key]
    cutoff = now - WINDOW_SECONDS
    timestamps[:] = [t for t in timestamps if t > cutoff]
    return timestamps


def check_login_rate_limit(*keys: str) -> None:
    """在真正校验密码/验证码之前调用；任一 key 已达到失败上限就直接拒绝。"""
    now = time.monotonic()
    for key in keys:
        if len(_prune(key, now)) >= MAX_ATTEMPTS:
            raise TooManyLoginAttemptsError()


def record_login_failure(*keys: str) -> None:
    """本次登录尝试失败后，给所有传入的 key 各记一次失败。"""
    now = time.monotonic()
    for key in keys:
        _prune(key, now).append(now)


def reset_login_failures(key: str) -> None:
    """登录成功后清空该 key 的失败计数（只清账号维度，IP 维度靠窗口期自然过期）。"""
    _failure_counters.pop(key, None)
