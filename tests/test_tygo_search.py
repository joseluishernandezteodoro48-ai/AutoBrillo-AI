import unittest

from brillo import Brillo
from tygo_search import TygoSearchDecision


class FakeMemory:
    def __init__(self, events=None):
        self.events = events or []

    def recent(self, limit=100):
        return self.events[:limit]


class FakeCatalog:
    def __init__(self, products=None):
        self.products = products or []


class FakeAgent:
    def __init__(self, products=None, events=None):
        self.catalog = FakeCatalog(products)
        self.memory = FakeMemory(events)


class TygoSearchTests(unittest.TestCase):
    def test_productos_has_no_fixed_five_default(self):
        brillo = Brillo(agent=FakeAgent())
        intent = brillo.understand("productos")
        self.assertEqual(intent["product_count_source"], "tygo")
        self.assertNotEqual(intent["product_count"], 5)
        self.assertGreaterEqual(intent["product_count"], TygoSearchDecision.MIN_RESULTS)

    def test_explicit_quantity_is_honored(self):
        brillo = Brillo(agent=FakeAgent())
        intent = brillo.understand("consigue 8 productos")
        self.assertEqual(intent["product_count"], 8)
        self.assertEqual(intent["product_count_source"], "user")

    def test_tygo_count_is_bounded(self):
        decision = TygoSearchDecision().choose_count(FakeAgent(products=[{}] * 100))
        self.assertGreaterEqual(decision["count"], TygoSearchDecision.MIN_RESULTS)
        self.assertLessEqual(decision["count"], TygoSearchDecision.MAX_RESULTS)
        self.assertEqual(decision["source"], "tygo")


if __name__ == "__main__":
    unittest.main()
