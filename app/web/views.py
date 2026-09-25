"""Server-rendered website."""
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from ..metrics import record
from ..models import Loan, Reservation, User
from ..services import LibraryError, accounts, catalogue, circulation
from ..services.rules import LoanPolicy
from .forms import ActionForm, BookForm, LoginForm, RegisterForm

main = Blueprint("main", __name__)
auth = Blueprint("auth", __name__)
admin = Blueprint("admin", __name__, url_prefix="/admin")


def _policy():
    return LoanPolicy.from_config(current_app.config)


def _safe_next(target):
    """Only allow redirects to local paths."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.index")


def librarian_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_librarian:
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


def _run(action, success_message, metric=None):
    """Run a service call from a POST button, flashing the outcome."""
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        action()
    except LibraryError as err:
        flash(str(err), "error")
        return False
    if metric:
        record("loan_events", metric)
    flash(success_message, "success")
    return True


# --- Catalogue ------------------------------------------------------------------------------


@main.get("/")
def index():
    q = request.args.get("q", "")
    genre = request.args.get("genre", "")
    available = request.args.get("available") == "1"
    books = catalogue.search(q, genre, available)
    template = "_book_grid.html" if request.args.get("partial") == "1" else "index.html"
    return render_template(
        template, books=books, q=q, genre=genre, available=available, genres=catalogue.genres()
    )


@main.get("/books/<int:book_id>")
def book_detail(book_id):
    try:
        book = circulation.get_book(book_id)
    except LibraryError:
        abort(404)
    my_loan = my_reservation = None
    if current_user.is_authenticated:
        my_loan = book.loans.filter(
            Loan.user_id == current_user.id, Loan.returned_at.is_(None)
        ).first()
        my_reservation = book.reservations.filter(
            Reservation.user_id == current_user.id,
            Reservation.status.in_([Reservation.WAITING, Reservation.READY]),
        ).first()
    return render_template(
        "book.html", book=book, my_loan=my_loan, my_reservation=my_reservation, form=ActionForm()
    )


@main.get("/status")
def status():
    return render_template("status.html")


# --- Member actions -------------------------------------------------------------------------


@main.post("/books/<int:book_id>/borrow")
@login_required
def borrow(book_id):
    book = circulation.get_book(book_id)
    ok = _run(
        lambda: circulation.borrow(current_user, book, _policy()),
        f"You borrowed “{book.title}”. Enjoy!",
        "borrow",
    )
    return redirect(url_for("main.my_loans") if ok else url_for("main.book_detail", book_id=book_id))


@main.post("/books/<int:book_id>/reserve")
@login_required
def reserve(book_id):
    book = circulation.get_book(book_id)
    _run(
        lambda: circulation.reserve(current_user, book),
        f"You joined the queue for “{book.title}”.",
        "reserve",
    )
    return redirect(url_for("main.book_detail", book_id=book_id))


@main.post("/loans/<int:loan_id>/return")
@login_required
def return_loan(loan_id):
    loan = circulation.get_loan(loan_id)
    _run(
        lambda: circulation.return_loan(loan, current_user, _policy()),
        f"Returned “{loan.book.title}”.",
        "return",
    )
    return redirect(_safe_next(request.form.get("next") or url_for("main.my_loans")))


@main.post("/loans/<int:loan_id>/renew")
@login_required
def renew(loan_id):
    loan = circulation.get_loan(loan_id)
    _run(
        lambda: circulation.renew(loan, current_user, _policy()),
        f"Renewed “{loan.book.title}”.",
        "renew",
    )
    return redirect(url_for("main.my_loans"))


@main.post("/reservations/<int:reservation_id>/cancel")
@login_required
def cancel_reservation(reservation_id):
    reservation = circulation.get_reservation(reservation_id)
    _run(
        lambda: circulation.cancel_reservation(reservation, current_user),
        "Reservation cancelled.",
    )
    return redirect(url_for("main.my_loans"))


@main.get("/loans")
@login_required
def my_loans():
    active = circulation.active_loans(current_user)
    history = (
        current_user.loans.filter(Loan.returned_at.isnot(None))
        .order_by(Loan.returned_at.desc())
        .limit(20)
        .all()
    )
    reservations = (
        current_user.reservations.filter(
            Reservation.status.in_([Reservation.WAITING, Reservation.READY])
        )
        .order_by(Reservation.id)
        .all()
    )
    return render_template(
        "loans.html", active=active, history=history, reservations=reservations, form=ActionForm()
    )


# --- Authentication -------------------------------------------------------------------------


@auth.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = accounts.authenticate(form.email.data, form.password.data)
        if user:
            login_user(user)
            record("logins", "success")
            flash(f"Welcome back, {user.name.split()[0]}.", "success")
            return redirect(_safe_next(request.args.get("next")))
        record("logins", "failure")
        flash("Invalid email or password.", "error")
    return render_template("login.html", form=form)


@auth.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = RegisterForm()
    if form.validate_on_submit():
        try:
            user = accounts.register(form.name.data, form.email.data, form.password.data)
        except LibraryError as err:
            flash(str(err), "error")
        else:
            login_user(user)
            flash("Your account is ready. Happy reading!", "success")
            return redirect(url_for("main.index"))
    return render_template("register.html", form=form)


@auth.post("/logout")
@login_required
def logout():
    form = ActionForm()
    if form.validate_on_submit():
        logout_user()
        flash("You have been signed out.", "info")
    return redirect(url_for("main.index"))


# --- Librarian ------------------------------------------------------------------------------


@admin.get("/")
@librarian_required
def dashboard():
    return render_template(
        "admin/dashboard.html",
        stats=circulation.dashboard_stats(),
        overdue=circulation.overdue_loans(),
        form=ActionForm(),
    )


@admin.get("/books")
@librarian_required
def books():
    return render_template(
        "admin/books.html", books=catalogue.search(request.args.get("q", ""), limit=500),
        q=request.args.get("q", ""), form=ActionForm(),
    )


@admin.route("/books/new", methods=["GET", "POST"])
@librarian_required
def new_book():
    form = BookForm()
    if form.validate_on_submit():
        try:
            book = catalogue.create_book(form.data)
        except LibraryError as err:
            flash(str(err), "error")
        else:
            flash(f"Added “{book.title}”.", "success")
            return redirect(url_for("admin.books"))
    return render_template("admin/book_form.html", form=form, book=None)


@admin.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
@librarian_required
def edit_book(book_id):
    book = circulation.get_book(book_id)
    form = BookForm(obj=book)
    if form.validate_on_submit():
        try:
            catalogue.update_book(book, form.data)
        except LibraryError as err:
            flash(str(err), "error")
        else:
            flash(f"Saved “{book.title}”.", "success")
            return redirect(url_for("admin.books"))
    return render_template("admin/book_form.html", form=form, book=book)


@admin.post("/books/<int:book_id>/delete")
@librarian_required
def delete_book(book_id):
    book = circulation.get_book(book_id)
    title = book.title
    _run(lambda: catalogue.delete_book(book), f"Deleted “{title}”.")
    return redirect(url_for("admin.books"))


@admin.get("/members")
@librarian_required
def members():
    users = User.query.order_by(User.role.desc(), User.name).all()
    return render_template("admin/members.html", users=users, Loan=Loan)
