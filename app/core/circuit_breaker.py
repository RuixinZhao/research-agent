import os
import time
import signal
import logging
import threading
from typing import Callable, Any, Optional, Dict

logger = logging.getLogger(__name__)

class TaskTimeoutException(BaseException):
    """任务执行超时硬中断异常（继承 BaseException 防止被通用 except Exception 静默捕获）"""
    pass

class CircuitBreakerOpenException(Exception):
    """熔断器处于开启状态（快速失败，阻止连续崩溃）"""
    pass

class TaskTimeoutGuard:
    """
    单任务 150 秒超时熔断守护器。
    
    在 Linux/macOS POSIX 环境的主线程中，利用 SIGALRM 提供硬中断保护；
    在子线程或非主线程环境中，使用计时监控与防御性中断。
    防止任务执行超过 150s 被平台 180s 杀死导致整题得 0 分。
    """
    def __init__(self, case_id: str, timeout_seconds: int = 150):
        self.case_id = case_id
        self.timeout_seconds = timeout_seconds
        self.start_time: float = 0.0
        self.duration: float = 0.0
        self.timed_out: bool = False
        self._old_signal_handler = None
        self._alarm_armed: bool = False

    def __enter__(self):
        self.start_time = time.time()
        self.timed_out = False
        self._alarm_armed = False

        # 如果在主线程且系统支持 SIGALRM，设置信号软中断
        if hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread():
            def _alarm_handler(signum, frame):
                self.timed_out = True
                logger.warning(f"TaskTimeoutGuard: Task {self.case_id} timed out after {self.timeout_seconds}s!")
                raise TaskTimeoutException(
                    f"Task {self.case_id} execution exceeded circuit breaker limit ({self.timeout_seconds}s)"
                )

            try:
                self._old_signal_handler = signal.signal(signal.SIGALRM, _alarm_handler)
                signal.alarm(int(self.timeout_seconds))
                self._alarm_armed = True
            except (ValueError, TypeError) as e:
                logger.debug(f"TaskTimeoutGuard: could not set SIGALRM: {e}")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._alarm_armed and hasattr(signal, "SIGALRM"):
            try:
                signal.alarm(0)
                if self._old_signal_handler is not None:
                    signal.signal(signal.SIGALRM, self._old_signal_handler)
            except Exception as e:
                logger.debug(f"TaskTimeoutGuard: error disarming alarm: {e}")

        self.duration = time.time() - self.start_time

        if exc_type is TaskTimeoutException:
            self.timed_out = True
            logger.error(f"TaskTimeoutGuard: Task {self.case_id} terminated due to timeout after {self.duration:.2f}s")
            # 不静默吞掉异常，留给上层 handler 或 server 进行合规降级
            return False

        if exc_type is not None:
            logger.error(f"TaskTimeoutGuard: Task {self.case_id} failed with error {exc_val} after {self.duration:.2f}s")
            return False

        return False

    @property
    def elapsed_time(self) -> float:
        if self.start_time == 0.0:
            return 0.0
        return time.time() - self.start_time

    def remaining_time(self) -> float:
        rem = self.timeout_seconds - self.elapsed_time
        return max(0.0, rem)

    def is_timed_out(self) -> bool:
        if self.timed_out:
            return True
        return self.elapsed_time >= self.timeout_seconds


class CircuitBreaker:
    """
    通用断路器（Circuit Breaker），用于防范级联失败。
    维护 CLOSED、OPEN、HALF_OPEN 三种状态。
    """
    STATE_CLOSED = "CLOSED"
    STATE_OPEN = "OPEN"
    STATE_HALF_OPEN = "HALF_OPEN"

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count: int = 0
        self.last_failure_time: float = 0.0
        self.state: str = self.STATE_CLOSED
        self._lock = threading.Lock()

    def record_success(self):
        with self._lock:
            self.failure_count = 0
            self.state = self.STATE_CLOSED

    def record_failure(self):
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = self.STATE_OPEN
                logger.warning(
                    f"CircuitBreaker: state tripped to OPEN after {self.failure_count} consecutive failures"
                )

    def can_execute(self) -> bool:
        with self._lock:
            if self.state == self.STATE_CLOSED:
                return True
            if self.state == self.STATE_OPEN:
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = self.STATE_HALF_OPEN
                    logger.info("CircuitBreaker: probe state shifted to HALF_OPEN")
                    return True
                return False
            if self.state == self.STATE_HALF_OPEN:
                return True
            return True

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        if not self.can_execute():
            raise CircuitBreakerOpenException("Circuit breaker is currently OPEN. Call rejected.")

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise e
