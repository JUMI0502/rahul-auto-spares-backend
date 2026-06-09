"""Tests for /orders endpoints."""
import pytest

class TestOrderEndpoints:

    def test_get_orders_200(self, client):
        r = client.get("/orders")
        assert r.status_code == 200

    def test_get_orders_returns_list(self, client):
        r = client.get("/orders")
        assert "orders" in r.json()
        assert isinstance(r.json()["orders"], list)

    def test_create_order_200(self, client):
        r = client.post("/orders", json={
            "customer_name": "Suresh",
            "customer_phone": "9876543210",
            "total_amount": 350.0,
            "pickup_time": "Today 5PM",
            "items": []
        })
        assert r.status_code == 200

    def test_create_order_returns_id(self, client):
        r = client.post("/orders", json={
            "customer_name": "Lakshmi",
            "customer_phone": "9123456789",
            "total_amount": 500.0,
            "pickup_time": "Tomorrow 11AM",
            "items": []
        })
        data = r.json()
        assert "id" in data or "custom_id" in data

    def test_new_order_status_is_new(self, client, add_order):
        r = client.get("/orders")
        orders = r.json()["orders"]
        assert len(orders) > 0
        order = orders[0]
        assert order["status"] == "new"

    def test_order_amount_correct(self, client, add_order):
        r = client.get("/orders")
        orders = r.json()["orders"]
        assert float(orders[0]["total_amount"]) == 450.0

    def test_update_order_to_packing(self, client, add_order):
        order_id = add_order.get("id", 1)
        r = client.put(f"/orders/{order_id}", json={
            "status": "packing", "collected_by": "Staff"
        })
        assert r.status_code == 200

    def test_update_order_to_ready(self, client, add_order):
        order_id = add_order.get("id", 1)
        r = client.put(f"/orders/{order_id}", json={
            "status": "ready", "collected_by": "Staff"
        })
        assert r.status_code == 200

    def test_update_order_to_collected(self, client, add_order):
        order_id = add_order.get("id", 1)
        r = client.put(f"/orders/{order_id}", json={
            "status": "collected", "collected_by": "Owner"
        })
        assert r.status_code == 200

    def test_update_payment_cash(self, client, add_order):
        order_id = add_order.get("id", 1)
        r = client.put(f"/orders/{order_id}", json={"payment_type": "cash"})
        assert r.status_code == 200

    def test_update_payment_upi(self, client, add_order):
        order_id = add_order.get("id", 1)
        r = client.put(f"/orders/{order_id}", json={"payment_type": "upi"})
        assert r.status_code == 200

    def test_customer_orders_by_phone(self, client, add_order):
        r = client.get("/orders/customer/9876543210")
        assert r.status_code == 200
        assert "orders" in r.json()

    def test_unknown_phone_returns_empty(self, client):
        r = client.get("/orders/customer/0000000000")
        assert r.status_code == 200
        assert r.json()["orders"] == []
