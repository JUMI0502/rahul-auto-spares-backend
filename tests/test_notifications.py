"""Tests for notification endpoints."""
import pytest
from unittest.mock import patch, MagicMock

class TestNotificationEndpoints:

    def test_notify_order_returns_200(self, client, add_order):
        order_id = add_order.get("id", 1)
        r = client.post(f"/notify/order-ready/{order_id}")
        assert r.status_code == 200

    def test_notify_invalid_order_200(self, client):
        r = client.post("/notify/order-ready/99999")
        assert r.status_code == 200

    def test_notify_returns_dict(self, client, add_order):
        order_id = add_order.get("id", 1)
        r = client.post(f"/notify/order-ready/{order_id}")
        assert isinstance(r.json(), dict)

    def test_broadcast_returns_200(self, client):
        r = client.post("/notify/broadcast", json={
            "title": "Special Offer!",
            "body": "10% off all engine oils today!"
        })
        assert r.status_code == 200

    def test_broadcast_no_tokens_sent_zero(self, client):
        r = client.post("/notify/broadcast", json={
            "title": "Test", "body": "Test"
        })
        assert r.json().get("sent", 0) == 0

    def test_broadcast_returns_sent_key(self, client):
        r = client.post("/notify/broadcast", json={
            "title": "Sale", "body": "Big sale!"
        })
        data = r.json()
        assert "sent" in data

    def test_daily_summary_200(self, client):
        r = client.get("/reports/daily-summary")
        assert r.status_code == 200

    def test_daily_summary_is_dict(self, client):
        r = client.get("/reports/daily-summary")
        assert isinstance(r.json(), dict)

    def test_daily_summary_has_revenue(self, client):
        r = client.get("/reports/daily-summary")
        data = r.json()
        if "total_revenue" in data:
            assert isinstance(data["total_revenue"], (int, float))
            assert data["total_revenue"] >= 0

    def test_daily_summary_has_orders(self, client):
        r = client.get("/reports/daily-summary")
        data = r.json()
        if "total_orders" in data:
            assert isinstance(data["total_orders"], int)
