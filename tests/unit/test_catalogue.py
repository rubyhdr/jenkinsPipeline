import pytest

from app.models import Reservation
from app.services import ConflictError, LibraryError, catalogue, circulation

pytestmark = pytest.mark.unit

VALID = {"isbn": "978-0-14-143951-8", "title": "Pride and Prejudice", "author": "Jane Austen",
         "genre": "Classics", "year": "1813", "copies_total": "2"}


def test_create_book_normalises_fields(app):
    book = catalogue.create_book(dict(VALID, title="  Pride and Prejudice  "))
    assert book.isbn == "9780141439518"
    assert book.title == "Pride and Prejudice"
    assert book.year == 1813 and book.copies_total == 2


@pytest.mark.parametrize("override, message", [
    ({"isbn": "123"}, "ISBN"),
    ({"title": ""}, "Title"),
    ({"copies_total": "lots"}, "whole number"),
    ({"copies_total": 500}, "between"),
    ({"year": "soon"}, "Year"),
])
def test_create_book_validation(app, override, message):
    with pytest.raises(LibraryError, match=message):
        catalogue.create_book(dict(VALID, **override))


def test_create_book_requires_fields(app):
    with pytest.raises(LibraryError, match="Missing"):
        catalogue.create_book({"title": "No ISBN"})


def test_duplicate_isbn_rejected(app):
    catalogue.create_book(VALID)
    with pytest.raises(ConflictError):
        catalogue.create_book(VALID)


def test_search_matches_title_author_isbn_and_genre(make_book):
    make_book(title="Dune", author="Frank Herbert", genre="Science Fiction")
    make_book(title="Emma", author="Jane Austen", genre="Classics")
    assert [b.title for b in catalogue.search("dune")] == ["Dune"]
    assert [b.title for b in catalogue.search("austen")] == ["Emma"]
    assert [b.title for b in catalogue.search("", genre="Classics")] == ["Emma"]
    isbn = catalogue.search("dune")[0].isbn
    assert [b.title for b in catalogue.search(isbn)] == ["Dune"]
    assert catalogue.genres() == ["Classics", "Science Fiction"]


def test_search_available_only(member, make_book, policy):
    busy = make_book(title="Busy", copies=1)
    make_book(title="Free", copies=1)
    circulation.borrow(member, busy, policy)
    assert [b.title for b in catalogue.search(available_only=True)] == ["Free"]


def test_update_cannot_drop_copies_below_loans(member, make_book, policy):
    book = make_book(copies=2)
    circulation.borrow(member, book, policy)
    with pytest.raises(ConflictError):
        catalogue.update_book(book, {"copies_total": 0})


def test_update_duplicate_isbn_rejected(make_book):
    first = make_book(title="First")
    second = make_book(title="Second")
    with pytest.raises(ConflictError):
        catalogue.update_book(second, {"isbn": first.isbn})


def test_adding_copies_serves_the_reservation_queue(member, make_user, make_book, policy):
    book = make_book(copies=1)
    circulation.borrow(make_user(), book, policy)
    reservation = circulation.reserve(member, book)
    catalogue.update_book(book, {"copies_total": 2, "title": "Renamed"})
    assert book.title == "Renamed"
    assert reservation.status == Reservation.READY


def test_delete_book(member, make_book, policy):
    book = make_book()
    loan = circulation.borrow(member, book, policy)
    with pytest.raises(ConflictError):
        catalogue.delete_book(book)
    circulation.return_loan(loan, member, policy)
    catalogue.delete_book(book)
    assert catalogue.search() == []
