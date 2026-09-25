from datetime import timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import Book, Loan, utcnow
from app.services import circulation

pytestmark = pytest.mark.integration


def test_home_lists_books_and_filters(client, make_book):
    make_book(title="Dune", genre="Science Fiction")
    make_book(title="Emma", genre="Classics")
    page = client.get("/").get_data(as_text=True)
    assert "Dune" in page and "Emma" in page and "2 books" in page

    partial = client.get("/?q=dune&partial=1").get_data(as_text=True)
    assert "Dune" in partial and "Emma" not in partial and "<html" not in partial

    assert "Emma" not in client.get("/?genre=Science+Fiction").get_data(as_text=True)
    assert "No books match" in client.get("/?q=zzzz").get_data(as_text=True)


def test_book_detail_for_anonymous_and_404(client, make_book):
    book = make_book(title="Dune", copies=2)
    page = client.get(f"/books/{book.id}").get_data(as_text=True)
    assert "Sign in to borrow" in page and "2 available" in page
    res = client.get("/books/999")
    assert res.status_code == 404 and "couldn" in res.get_data(as_text=True)


def test_register_login_logout(client):
    res = client.post("/register", data={"name": "Web User", "email": "web@example.com",
                                         "password": "Password123", "confirm": "Password123"},
                      follow_redirects=True)
    assert "Your account is ready" in res.get_data(as_text=True)
    assert client.get("/register").status_code == 302  # already signed in

    res = client.post("/logout", follow_redirects=True)
    assert "signed out" in res.get_data(as_text=True)

    dup = client.post("/register", data={"name": "Web User", "email": "web@example.com",
                                         "password": "Password123", "confirm": "Password123"})
    assert "already exists" in dup.get_data(as_text=True)


def test_login_failure_and_safe_redirect(client, member, login):
    res = client.post("/login", data={"email": member.email, "password": "wrong"})
    assert "Invalid email or password" in res.get_data(as_text=True)

    res = client.post("/login?next=//evil.example.com", data={"email": member.email,
                                                              "password": "Password123"})
    assert res.headers["Location"] == "/"
    assert client.get("/login").status_code == 302


def test_login_redirects_to_next(client, member):
    res = client.post("/login?next=/loans", data={"email": member.email, "password": "Password123"})
    assert res.headers["Location"] == "/loans"


def test_protected_pages_require_login(client):
    res = client.get("/loans")
    assert res.status_code == 302 and "/login" in res.headers["Location"]


def test_borrow_renew_return_via_website(client, member, make_book, login):
    book = make_book(title="Dune", copies=1)
    login(member.email)

    res = client.post(f"/books/{book.id}/borrow", follow_redirects=True)
    page = res.get_data(as_text=True)
    assert "You borrowed" in page and "Dune" in page and "1 of" in page

    loan = Loan.query.one()
    assert "Renewed" in client.post(f"/loans/{loan.id}/renew", follow_redirects=True).get_data(as_text=True)
    assert "already been renewed" in client.post(
        f"/loans/{loan.id}/renew", follow_redirects=True).get_data(as_text=True)

    detail = client.get(f"/books/{book.id}").get_data(as_text=True)
    assert "Return" in detail

    res = client.post(f"/loans/{loan.id}/return", data={"next": f"/books/{book.id}"},
                      follow_redirects=True)
    assert "Returned" in res.get_data(as_text=True)

    history = client.get("/loans").get_data(as_text=True)
    assert "History" in history and "Nothing on loan" in history


def test_reserve_and_cancel_via_website(client, member, make_user, make_book, login, policy):
    book = make_book(title="Popular", copies=1)
    circulation.borrow(make_user(), book, policy)
    login(member.email)

    page = client.get(f"/books/{book.id}").get_data(as_text=True)
    assert "Reserve" in page
    res = client.post(f"/books/{book.id}/reserve", follow_redirects=True)
    assert "joined the queue" in res.get_data(as_text=True)
    assert "#1 in the queue" in res.get_data(as_text=True)

    again = client.post(f"/books/{book.id}/reserve", follow_redirects=True)
    assert "already reserved" in again.get_data(as_text=True)

    loans_page = client.get("/loans").get_data(as_text=True)
    assert "Reservations" in loans_page

    from app.models import Reservation
    reservation = Reservation.query.one()
    res = client.post(f"/reservations/{reservation.id}/cancel", follow_redirects=True)
    assert "Reservation cancelled" in res.get_data(as_text=True)


def test_ready_reservation_shows_borrow_now(client, member, make_user, make_book, login, policy):
    book = make_book(copies=1)
    holder = make_user()
    loan = circulation.borrow(holder, book, policy)
    circulation.reserve(member, book)
    circulation.return_loan(loan, holder, policy)
    login(member.email)
    page = client.get(f"/books/{book.id}").get_data(as_text=True)
    assert "Held for you" in page and "Borrow now" in page
    assert "Ready to borrow" in client.get("/loans").get_data(as_text=True)


def test_error_flash_when_borrowing_unavailable(client, member, make_user, make_book, login, policy):
    book = make_book(copies=1)
    circulation.borrow(make_user(), book, policy)
    login(member.email)
    res = client.post(f"/books/{book.id}/borrow", follow_redirects=True)
    assert "No copies are available" in res.get_data(as_text=True)


def test_overdue_and_fee_display(client, member, make_book, login, policy):
    book = make_book(title="Late", copies=1)
    circulation.borrow(member, book, policy, now=utcnow() - timedelta(days=20))
    login(member.email)
    assert "Overdue since" in client.get("/loans").get_data(as_text=True)
    loan = Loan.query.one()
    client.post(f"/loans/{loan.id}/return")
    assert "Late fee" in client.get("/loans").get_data(as_text=True)


def test_members_get_403_on_admin(client, member, login):
    login(member.email)
    res = client.get("/admin/")
    assert res.status_code == 403 and "access" in res.get_data(as_text=True)


def test_librarian_dashboard_and_members(client, librarian, member, make_book, login, policy):
    book = make_book(title="Dune", copies=1)
    circulation.borrow(member, book, policy, now=utcnow() - timedelta(days=30))
    login(librarian.email)
    dash = client.get("/admin/").get_data(as_text=True)
    assert "Library overview" in dash and "Dune" in dash and "Check in" in dash
    members = client.get("/admin/members").get_data(as_text=True)
    assert member.email in members
    loan = Loan.query.one()
    res = client.post(f"/loans/{loan.id}/return", data={"next": "/admin/"}, follow_redirects=True)
    assert "Nothing overdue" in res.get_data(as_text=True)


def test_librarian_manages_books(client, librarian, login):
    login(librarian.email)
    assert "Add a book" in client.get("/admin/books/new").get_data(as_text=True)

    form = {"isbn": "9780441172719", "title": "Dune", "author": "Frank Herbert",
            "genre": "Science Fiction", "year": "1965", "copies_total": "2", "description": "Spice."}
    res = client.post("/admin/books/new", data=form, follow_redirects=True)
    assert "Added" in res.get_data(as_text=True)

    dup = client.post("/admin/books/new", data=form)
    assert "already exists" in dup.get_data(as_text=True)

    book = Book.query.one()
    assert "Edit" in client.get(f"/admin/books/{book.id}/edit").get_data(as_text=True)
    res = client.post(f"/admin/books/{book.id}/edit", data=dict(form, title="Dune Messiah"),
                      follow_redirects=True)
    assert "Saved" in res.get_data(as_text=True)
    bad = client.post(f"/admin/books/{book.id}/edit", data=dict(form, isbn="123"))
    assert "ISBN is not valid" in bad.get_data(as_text=True)

    assert "Dune Messiah" in client.get("/admin/books?q=messiah").get_data(as_text=True)
    res = client.post(f"/admin/books/{book.id}/delete", follow_redirects=True)
    assert "Deleted" in res.get_data(as_text=True)
    assert db.session.get(Book, book.id) is None


def test_status_page_and_footer(client):
    page = client.get("/status").get_data(as_text=True)
    assert "System status" in page and "testing" in page


def test_csrf_enforced_when_enabled():
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = True
    with app.app_context():
        db.create_all()
        client = app.test_client()
        res = client.post("/login", data={"email": "x@example.com", "password": "Password123"})
        assert res.status_code == 400
        db.drop_all()
