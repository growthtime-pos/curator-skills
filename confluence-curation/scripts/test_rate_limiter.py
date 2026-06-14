#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import fetch_confluence  # noqa: E402


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class RateLimiterTests(unittest.TestCase):
    def test_interval_mode_waits_between_every_request(self) -> None:
        clock = ManualClock()
        limiter = fetch_confluence.RateLimiter.interval(0.5, clock.monotonic, clock.sleep)

        limiter.wait()
        limiter.wait()
        limiter.wait()

        self.assertEqual(clock.sleeps, [2.0, 2.0])

    def test_window_mode_paces_initial_window_then_waits(self) -> None:
        clock = ManualClock()
        limiter = fetch_confluence.RateLimiter.window(3, 60, clock.monotonic, clock.sleep)

        for _ in range(3):
            limiter.wait()
        limiter.wait()

        self.assertEqual(clock.sleeps, [1.0, 1.0, 58.0])

    def test_window_mode_updates_from_success_headers(self) -> None:
        clock = ManualClock()
        limiter = fetch_confluence.RateLimiter.window(10, 60, clock.monotonic, clock.sleep)

        limiter.wait()
        limiter.update_from_headers(
            {
                "X-RateLimit-Limit": "10",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-FillRate": "10",
                "X-RateLimit-Interval-Seconds": "60",
                "Retry-After": "0",
            }
        )
        limiter.wait()

        self.assertEqual(clock.sleeps, [60.0])

    def test_retry_after_overrides_window_wait(self) -> None:
        clock = ManualClock()
        limiter = fetch_confluence.RateLimiter.window(10, 60, clock.monotonic, clock.sleep)

        limiter.update_from_headers({"Retry-After": "17"})
        limiter.wait_for_retry_after()

        self.assertEqual(clock.sleeps, [17.0])


if __name__ == "__main__":
    unittest.main()
