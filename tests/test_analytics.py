"""Tests for analytics endpoints."""
import pytest

class TestAnalyticsEndpoints:

    def test_analytics_200(self, client):
        r = client.get("/customers/analytics")
        assert r.status_code == 200

    def test_analytics_has_top_spenders(self, client):
        r = client.get("/customers/analytics")
        data = r.json()
        assert "top_spenders" in data
        assert isinstance(data["top_spenders"], list)

    def test_analytics_has_top_orderers(self, client):
        r = client.get("/customers/analytics")
        assert "top_orderers" in r.json()

    def test_analytics_has_monthly(self, client):
        r = client.get("/customers/analytics")
        assert "monthly" in r.json()

    def test_monthly_has_revenue(self, client):
        r = client.get("/customers/analytics")
        monthly = r.json()["monthly"]
        assert "total_revenue" in monthly

    def test_monthly_revenue_is_numeric(self, client):
        r = client.get("/customers/analytics")
        revenue = r.json()["monthly"]["total_revenue"]
        assert isinstance(revenue, (int, float))

    def test_all_customers_200(self, client):
        r = client.get("/customers/all")
        assert r.status_code == 200

    def test_all_customers_returns_list(self, client):
        r = client.get("/customers/all")
        assert "customers" in r.json()
        assert isinstance(r.json()["customers"], list)

    def test_all_customers_has_count(self, client):
        r = client.get("/customers/all")
        data = r.json()
        assert "count" in data
        assert data["count"] == len(data["customers"])

    def test_spender_fields(self, client, add_order):
        r = client.get("/customers/analytics")
        spenders = r.json()["top_spenders"]
        if spenders:
            s = spenders[0]
            assert "name" in s
            assert "phone" in s
