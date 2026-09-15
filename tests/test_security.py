import unittest

from security import RateLimiter, constant_time_equal, redact


class SecurityTests(unittest.TestCase):
    def test_rate_limiter_blocks_after_limit(self):
        limiter = RateLimiter(limit=2, window_seconds=60)
        self.assertTrue(limiter.allow('client'))
        self.assertTrue(limiter.allow('client'))
        self.assertFalse(limiter.allow('client'))

    def test_rate_limiter_isolated_by_key(self):
        limiter = RateLimiter(limit=1, window_seconds=60)
        self.assertTrue(limiter.allow('a'))
        self.assertFalse(limiter.allow('a'))
        self.assertTrue(limiter.allow('b'))

    def test_constant_time_equal(self):
        self.assertTrue(constant_time_equal('secret', 'secret'))
        self.assertFalse(constant_time_equal('wrong', 'secret'))
        self.assertFalse(constant_time_equal(None, 'secret'))

    def test_redact_secrets(self):
        text = 'access_token=ABC123 client_secret=XYZ password=hunter2'
        cleaned = redact(text)
        self.assertNotIn('ABC123', cleaned)
        self.assertNotIn('XYZ', cleaned)
        self.assertNotIn('hunter2', cleaned)
        self.assertIn('[redacted]', cleaned)


if __name__ == '__main__':
    unittest.main()
