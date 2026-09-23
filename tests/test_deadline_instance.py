"""
tests/test_deadline_instance.py
================================
Tests for pure instance-based monotonic Deadline and DeadlineExceeded exception.

Instance API:
    dl = Deadline(seconds)
    child = dl.child(max_seconds)
    dl.is_exceeded()      -> bool
    dl.remaining()        -> float
    dl.require(min_sec)   -> float or raises DeadlineExceeded
    dl.bounded_timeout(default) -> float or raises DeadlineExceeded
"""

import time
import threading
import unittest

from utils.deadline import Deadline, DeadlineExceeded


class TestDeadlineInstance(unittest.TestCase):
    """Instance-based Deadline: basic monotonic behaviour and derived child deadlines."""

    def test_not_exceeded_immediately(self):
        dl = Deadline(10.0)
        self.assertFalse(dl.is_exceeded())

    def test_exceeded_after_expiry(self):
        dl = Deadline(0.05)  # 50 ms
        time.sleep(0.12)
        self.assertTrue(dl.is_exceeded())

    def test_remaining_decreases(self):
        dl = Deadline(5.0)
        r1 = dl.remaining()
        time.sleep(0.05)
        r2 = dl.remaining()
        self.assertGreater(r1, r2)

    def test_remaining_never_negative(self):
        dl = Deadline(0.01)
        time.sleep(0.1)
        self.assertEqual(dl.remaining(), 0.0)

    def test_bounded_timeout_caps_at_default(self):
        dl = Deadline(30.0)
        self.assertAlmostEqual(dl.bounded_timeout(10.0), 10.0)

    def test_bounded_timeout_caps_at_remaining(self):
        dl = Deadline(3.0)
        self.assertLessEqual(dl.bounded_timeout(10.0), 3.0)

    def test_bounded_timeout_raises_when_insufficient(self):
        dl = Deadline(0.5)
        with self.assertRaises(DeadlineExceeded):
            dl.bounded_timeout(10.0)

    def test_require_raises_when_remaining_less_than_min(self):
        dl = Deadline(0.5)
        with self.assertRaises(DeadlineExceeded):
            dl.require(1.0)

    def test_child_deadline_bounded_by_parent(self):
        from unittest.mock import patch
        with patch("time.monotonic", return_value=1000.0):
            parent = Deadline(2.0)
            child = parent.child(10.0)
            self.assertLessEqual(child.remaining(), parent.remaining())

    def test_child_deadline_bounded_by_max_seconds(self):
        parent = Deadline(10.0)
        child = parent.child(2.0)
        self.assertLessEqual(child.remaining(), 2.05)

    def test_two_instances_are_independent(self):
        """Core safety property: two instances never interfere."""
        dl_a = Deadline(10.0)   # long
        dl_b = Deadline(0.01)   # short

        time.sleep(0.1)

        self.assertTrue(dl_b.is_exceeded(),  "dl_b should be exceeded")
        self.assertFalse(dl_a.is_exceeded(), "dl_a must NOT be affected by dl_b expiry")

    def test_concurrent_instances_independent(self):
        """Simulate two concurrent requests: each instance tracks its own deadline."""
        results = {}

        def request_a():
            dl = Deadline(10.0)   # long
            time.sleep(0.15)
            results["a_exceeded"] = dl.is_exceeded()

        def request_b():
            dl = Deadline(0.02)   # short
            time.sleep(0.15)
            results["b_exceeded"] = dl.is_exceeded()

        t_a = threading.Thread(target=request_a)
        t_b = threading.Thread(target=request_b)
        t_a.start(); t_b.start()
        t_a.join(); t_b.join()

        self.assertFalse(results["a_exceeded"], "Request A deadline must still be alive")
        self.assertTrue(results["b_exceeded"],  "Request B deadline must be exceeded")

    def test_deadline_exceeded_exception(self):
        with self.assertRaises(DeadlineExceeded):
            raise DeadlineExceeded("Budget exhausted")


if __name__ == "__main__":
    unittest.main()
