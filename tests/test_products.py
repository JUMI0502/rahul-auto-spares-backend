"""Tests for /products endpoints."""
import pytest

class TestProductEndpoints:

    def test_get_products_returns_200(self, client):
        r = client.get("/products")
        assert r.status_code == 200

    def test_get_products_returns_list(self, client):
        r = client.get("/products")
        data = r.json()
        assert "products" in data
        assert isinstance(data["products"], list)

    def test_add_product_success(self, client):
        r = client.post("/products", json={
            "name_en": "Honda CB Shine Air Filter",
            "sku": "HND-CBS-001",
            "mrp": 180.0,
            "selling_price": 150.0,
            "stock_qty": 10
        })
        assert r.status_code == 200

    def test_add_product_appears_in_list(self, client, add_product):
        r = client.get("/products")
        skus = [p["sku"] for p in r.json()["products"]]
        assert "HRO-SPL-001" in skus

    def test_add_product_missing_name_fails(self, client):
        r = client.post("/products", json={
            "sku": "BAD-001", "mrp": 100.0, "selling_price": 80.0
        })
        data = r.json()
        assert "error" in data or r.status_code in [400, 422]

    def test_add_product_missing_mrp_fails(self, client):
        r = client.post("/products", json={
            "name_en": "Test", "sku": "BAD-002", "selling_price": 80.0
        })
        data = r.json()
        assert "error" in data or r.status_code in [400, 422]

    def test_duplicate_sku_returns_error(self, client, add_product):
        r = client.post("/products", json={
            "name_en": "Duplicate",
            "sku": "HRO-SPL-001",
            "mrp": 100.0,
            "selling_price": 80.0
        })
        assert "error" in r.json()

    def test_product_has_correct_price(self, client, add_product):
        r = client.get("/products")
        products = r.json()["products"]
        match = next((p for p in products if p["sku"] == "HRO-SPL-001"), None)
        assert match is not None
        assert float(match["mrp"]) == 250.0
        assert float(match["selling_price"]) == 210.0

    def test_product_has_stock_qty(self, client, add_product):
        r = client.get("/products")
        products = r.json()["products"]
        match = next((p for p in products if p["sku"] == "HRO-SPL-001"), None)
        assert match["stock_qty"] == 15

    def test_barcode_search_found(self, client, add_product):
        r = client.get("/products/barcode/HRO-SPL-001")
        assert r.status_code == 200
        data = r.json()
        assert data["found"] is True

    def test_barcode_search_not_found(self, client):
        r = client.get("/products/barcode/FAKE-999")
        assert r.status_code == 200
        assert r.json()["found"] is False

    def test_brand_filter_returns_products(self, client, add_product):
        r = client.get("/products/brand/HRO")
        assert r.status_code == 200
        data = r.json()
        assert "products" in data

    def test_brand_filter_correct_prefix(self, client, add_product):
        r = client.get("/products/brand/HRO")
        products = r.json()["products"]
        for p in products:
            assert p["sku"].startswith("HRO")

    def test_unknown_brand_empty_list(self, client):
        r = client.get("/products/brand/ZZZ")
        assert r.json()["products"] == []
