"""Demo data so every environment starts with a usable catalogue."""
import os
from datetime import timedelta

from .extensions import db
from .models import Book, Loan, User, utcnow

# (first 12 ISBN-13 digits, title, author, genre, year, copies, description)
BOOKS = [
    ("978014143951", "Pride and Prejudice", "Jane Austen", "Classics", 1813, 3,
     "A witty study of manners, marriage and misjudgement in Regency England."),
    ("978045152493", "Nineteen Eighty-Four", "George Orwell", "Classics", 1949, 2,
     "A chilling portrait of surveillance, propaganda and the fragility of truth."),
    ("978006112008", "To Kill a Mockingbird", "Harper Lee", "Classics", 1960, 2,
     "A child's view of justice and prejudice in a small Alabama town."),
    ("978074327356", "The Great Gatsby", "F. Scott Fitzgerald", "Classics", 1925, 1,
     "Wealth, longing and illusion on Long Island in the Jazz Age."),
    ("978054792822", "The Hobbit", "J. R. R. Tolkien", "Fantasy", 1937, 2,
     "Bilbo Baggins is swept into a quest for a dragon's treasure."),
    ("978055357340", "A Game of Thrones", "George R. R. Martin", "Fantasy", 1996, 1,
     "Noble houses fight for the Iron Throne as winter approaches."),
    ("978076532635", "Mistborn: The Final Empire", "Brandon Sanderson", "Fantasy", 2006, 2,
     "A street thief joins a rebellion powered by metal-based magic."),
    ("978044117271", "Dune", "Frank Herbert", "Science Fiction", 1965, 2,
     "Politics, ecology and prophecy on the desert planet Arrakis."),
    ("978059313520", "Project Hail Mary", "Andy Weir", "Science Fiction", 2021, 2,
     "A lone astronaut must save Earth with science and an unlikely friend."),
    ("978076531178", "The Three-Body Problem", "Liu Cixin", "Science Fiction", 2008, 1,
     "First contact unfolds against the backdrop of China's Cultural Revolution."),
    ("978030747427", "Sapiens", "Yuval Noah Harari", "History", 2011, 2,
     "A brief history of humankind from foragers to the present."),
    ("978039335432", "Guns, Germs, and Steel", "Jared Diamond", "History", 1997, 1,
     "Why some societies came to dominate others."),
    ("978013235088", "Clean Code", "Robert C. Martin", "Technology", 2008, 2,
     "Principles and practices for writing readable, maintainable software."),
    ("978020161622", "The Pragmatic Programmer", "Andrew Hunt & David Thomas", "Technology", 1999, 2,
     "Timeless advice for becoming a more effective developer."),
    ("978032160191", "Continuous Delivery", "Jez Humble & David Farley", "Technology", 2010, 1,
     "Reliable software releases through build, test and deployment automation."),
    ("978194278878", "The DevOps Handbook", "Gene Kim et al.", "Technology", 2016, 1,
     "How to create world-class agility, reliability and security in technology organisations."),
    ("978149192912", "Site Reliability Engineering", "Betsy Beyer et al.", "Technology", 2016, 1,
     "How Google runs production systems."),
    ("978073521129", "Atomic Habits", "James Clear", "Self-help", 2018, 3,
     "Tiny changes that compound into remarkable results."),
    ("978037453355", "Thinking, Fast and Slow", "Daniel Kahneman", "Psychology", 2011, 1,
     "The two systems that drive the way we think."),
    ("978152478513", "Educated", "Tara Westover", "Memoir", 2018, 1,
     "A woman raised off-grid in Idaho finds her way to a Cambridge PhD."),
    ("978006231500", "The Alchemist", "Paulo Coelho", "Fiction", 1988, 2,
     "A shepherd boy's journey in search of treasure and purpose."),
    ("978030727778", "The Road", "Cormac McCarthy", "Fiction", 2006, 1,
     "A father and son walk through a ruined America."),
    ("978059315565", "Tomorrow, and Tomorrow, and Tomorrow", "Gabrielle Zevin", "Fiction", 2022, 1,
     "Two friends build video games and a lifelong creative partnership."),
    ("978000819307", "Klara and the Sun", "Kazuo Ishiguro", "Fiction", 2021, 1,
     "An Artificial Friend observes the family she is bought to serve."),
]


def isbn13(first12: str) -> str:
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(first12))
    return first12 + str((10 - total % 10) % 10)


def _user(name, email, password, role):
    user = User.query.filter_by(email=email).first()
    if user is None:
        user = User(name=name, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
    return user


def seed_database(only_if_empty=False):
    if only_if_empty and Book.query.first() is not None:
        return False

    librarian = _user(
        "Lena Librarian", "librarian@shelf.local",
        os.environ.get("SEED_LIBRARIAN_PASSWORD", "Librarian123"), User.ROLE_LIBRARIAN,
    )
    member = _user(
        "Max Member", "member@shelf.local",
        os.environ.get("SEED_MEMBER_PASSWORD", "Member1234"), User.ROLE_MEMBER,
    )
    reader = _user(
        "Riley Reader", "reader@shelf.local",
        os.environ.get("SEED_MEMBER_PASSWORD", "Member1234"), User.ROLE_MEMBER,
    )

    books = {}
    for prefix, title, author, genre, year, copies, description in BOOKS:
        isbn = isbn13(prefix)
        book = Book.query.filter_by(isbn=isbn).first()
        if book is None:
            book = Book(isbn=isbn, title=title, author=author, genre=genre, year=year,
                        copies_total=copies, description=description)
            db.session.add(book)
        books[title] = book
    db.session.flush()

    now = utcnow()
    if Loan.query.first() is None:
        # A little history so the dashboard and metrics have something to show.
        db.session.add_all([
            Loan(user=reader, book=books["Dune"], borrowed_at=now - timedelta(days=20),
                 due_at=now - timedelta(days=6)),
            Loan(user=reader, book=books["Clean Code"], borrowed_at=now - timedelta(days=3),
                 due_at=now + timedelta(days=11)),
            Loan(user=member, book=books["The Hobbit"], borrowed_at=now - timedelta(days=30),
                 due_at=now - timedelta(days=16), returned_at=now - timedelta(days=15), fee=0.50),
            Loan(user=librarian, book=books["Sapiens"], borrowed_at=now - timedelta(days=40),
                 due_at=now - timedelta(days=26), returned_at=now - timedelta(days=28)),
        ])
    db.session.commit()
    return True
