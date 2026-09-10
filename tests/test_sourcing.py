import unittest

from sourcing import compare_product_with_suppliers, match_score


class SourcingTests(unittest.TestCase):
    def test_match_score(self):
        self.assertGreater(match_score("Audifonos Bluetooth deportivos", "Audifonos Bluetooth deportivos Pro"), 0.4)

    def test_verified_supplier_calculates_net_profit(self):
        product = {"name": "Audifonos Bluetooth", "price": 500}
        suppliers = [{
            "name": "Audifonos Bluetooth", "supplier_name": "Proveedor demo",
            "cost": 300, "shipping_cost": 50, "verified": True, "available": True,
        }]
        result = compare_product_with_suppliers(product, suppliers, commission_rate=0.10)
        self.assertTrue(result[0]["cost_known"])
        self.assertEqual(result[0]["projected_profit"], 100.0)
        self.assertEqual(result[0]["projected_margin"], 0.2)

    def test_unverified_cost_never_becomes_known(self):
        product = {"name": "Audifonos Bluetooth", "price": 500}
        suppliers = [{"name": "Audifonos Bluetooth", "cost": 1, "verified": False}]
        result = compare_product_with_suppliers(product, suppliers)
        self.assertFalse(result[0]["cost_known"])
        self.assertIsNone(result[0]["supplier_cost"])


if __name__ == "__main__":
    unittest.main()
