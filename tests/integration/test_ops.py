import pytest

pytestmark = pytest.mark.integration


def test_health_reports_version_and_database(client):
    res = client.get("/health")
    body = res.get_json()
    assert res.status_code == 200
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["env"] == "testing"


def test_api_status(client):
    assert client.get("/api/status").get_json()["name"] == "Shelf"


def test_metrics_expose_http_and_business_metrics(client, member, make_book, api_token):
    book = make_book()
    client.post("/api/loans", json={"book_id": book.id}, headers=api_token(member.email))
    client.get("/")
    text = client.get("/metrics").get_data(as_text=True)
    assert "flask_http_request_total" in text
    assert "library_active_loans 1.0" in text
    assert 'library_loan_events_total{action="borrow"} 1.0' in text
    assert 'library_logins_total{outcome="success"} 1.0' in text
    assert "shelf_app_info" in text


def test_chaos_endpoints_for_incident_simulation(client):
    assert client.get("/_chaos/error").status_code == 500
    assert client.get("/_chaos/slow?seconds=0").get_json()["slept"] == 0


def test_chaos_disabled_by_default():
    from app import create_app

    app = create_app("development")
    assert app.test_client().get("/_chaos/error").status_code == 404


def test_security_headers(client):
    res = client.get("/")
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in res.headers["Content-Security-Policy"]


def test_api_404_is_json(client):
    res = client.get("/api/nope")
    assert res.status_code == 404 and res.get_json()["error"] == "Not found."
