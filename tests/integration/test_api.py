from datetime import datetime, timedelta, timezone

import jwt
import pytest

pytestmark = pytest.mark.integration


def test_register_login_and_me(client):
    res = client.post("/api/auth/register",
                      json={"name": "Api User", "email": "api@example.com", "password": "Password123"})
    assert res.status_code == 201
    token = res.get_json()["token"]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.get_json()["user"]["email"] == "api@example.com"


def test_bad_credentials_and_bad_body(client, member):
    assert client.post("/api/auth/token", json={"email": member.email, "password": "nope"}).status_code == 401
    res = client.post("/api/auth/token", data="not json", content_type="text/plain")
    assert res.status_code == 400
    assert "JSON" in res.get_json()["error"]


@pytest.mark.parametrize("header", [None, "Token abc", "Bearer not-a-jwt"])
def test_protected_endpoints_reject_missing_or_invalid_tokens(client, header):
    headers = {"Authorization": header} if header else {}
    assert client.get("/api/loans", headers=headers).status_code == 401


def test_expired_token_rejected(app, client, member):
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    token = jwt.encode({"sub": str(member.id), "iat": past, "exp": past + timedelta(minutes=5)},
                       app.config["SECRET_KEY"], algorithm="HS256")
    res = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401 and "expired" in res.get_json()["error"]


def test_token_for_deleted_user_rejected(app, client):
    token = jwt.encode({"sub": "999", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                       app.config["SECRET_KEY"], algorithm="HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_full_loan_lifecycle(client, member, make_book, api_token):
    book = make_book(title="Dune", copies=1)
    auth = api_token(member.email)

    listing = client.get("/api/books?q=dune").get_json()
    assert listing["count"] == 1 and listing["books"][0]["available_copies"] == 1

    res = client.post("/api/loans", json={"book_id": book.id}, headers=auth)
    assert res.status_code == 201
    loan_id = res.get_json()["loan"]["id"]

    assert client.get(f"/api/books/{book.id}").get_json()["book"]["available_copies"] == 0
    assert len(client.get("/api/loans?active=1", headers=auth).get_json()["loans"]) == 1

    renewed = client.post(f"/api/loans/{loan_id}/renew", headers=auth)
    assert renewed.status_code == 200 and renewed.get_json()["loan"]["renewals"] == 1
    assert client.post(f"/api/loans/{loan_id}/renew", headers=auth).status_code == 409

    returned = client.post(f"/api/loans/{loan_id}/return", headers=auth)
    assert returned.get_json()["loan"]["returned_at"] is not None
    assert client.post(f"/api/loans/{loan_id}/return", headers=auth).status_code == 409


def test_reservations_api(client, member, make_user, make_book, api_token):
    book = make_book(copies=1)
    other = make_user()
    client.post("/api/loans", json={"book_id": book.id}, headers=api_token(other.email))

    auth = api_token(member.email)
    res = client.post("/api/reservations", json={"book_id": book.id}, headers=auth)
    assert res.status_code == 201
    assert res.get_json()["reservation"]["queue_position"] == 1
    reservation_id = res.get_json()["reservation"]["id"]
    assert len(client.get("/api/reservations", headers=auth).get_json()["reservations"]) == 1
    assert client.delete(f"/api/reservations/{reservation_id}", headers=auth).status_code == 204


def test_borrow_validation_errors(client, member, api_token):
    auth = api_token(member.email)
    assert client.post("/api/loans", json={"book_id": "abc"}, headers=auth).status_code == 400
    assert client.post("/api/loans", json={"book_id": 12345}, headers=auth).status_code == 404
    assert client.get("/api/books/12345").status_code == 404


def test_members_cannot_manage_books(client, member, make_book, api_token):
    auth = api_token(member.email)
    assert client.post("/api/books", json={}, headers=auth).status_code == 403
    assert client.get("/api/stats", headers=auth).status_code == 403


def test_librarian_book_crud_and_stats(client, librarian, member, api_token):
    auth = api_token(librarian.email)
    payload = {"isbn": "9780441172719", "title": "Dune", "author": "Frank Herbert",
               "genre": "Science Fiction", "copies_total": 1}
    created = client.post("/api/books", json=payload, headers=auth)
    assert created.status_code == 201
    book_id = created.get_json()["book"]["id"]

    assert client.post("/api/books", json=payload, headers=auth).status_code == 409
    updated = client.put(f"/api/books/{book_id}", json={"copies_total": 3}, headers=auth)
    assert updated.get_json()["book"]["copies_total"] == 3

    stats = client.get("/api/stats", headers=auth).get_json()
    assert stats["books"] == 1

    all_loans = client.get("/api/loans?all=1", headers=auth)
    assert all_loans.status_code == 200

    assert client.delete(f"/api/books/{book_id}", headers=auth).status_code == 204
    assert client.get(f"/api/books/{book_id}").status_code == 404


def test_librarian_sees_all_loans(client, librarian, member, make_book, api_token):
    book = make_book()
    client.post("/api/loans", json={"book_id": book.id}, headers=api_token(member.email))
    auth = api_token(librarian.email)
    assert len(client.get("/api/loans", headers=auth).get_json()["loans"]) == 0
    assert len(client.get("/api/loans?all=1", headers=auth).get_json()["loans"]) == 1
    stats = client.get("/api/stats", headers=auth).get_json()
    assert stats["popular"][0]["book_id"] == book.id
    assert stats["recent_loans"][0]["book"]["id"] == book.id
