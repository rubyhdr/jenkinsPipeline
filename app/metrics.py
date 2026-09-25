"""Prometheus metrics: HTTP metrics from prometheus-flask-exporter plus library business metrics."""
from flask import current_app
from prometheus_client import CollectorRegistry, Counter, Gauge
from prometheus_client import ProcessCollector, PlatformCollector
from prometheus_flask_exporter import PrometheusMetrics


def init_metrics(app):
    # A registry per app instance keeps test apps from clashing over global metric names.
    registry = CollectorRegistry(auto_describe=True)
    ProcessCollector(registry=registry)
    PlatformCollector(registry=registry)

    exporter = PrometheusMetrics(
        app,
        registry=registry,
        group_by="endpoint",
        excluded_paths=["/metrics", "/health", "/static"],
        default_labels={"env": app.config["APP_ENV"]},
    )
    exporter.info(
        "shelf_app_info",
        "Shelf application version information",
        version=app.config["APP_VERSION"],
        commit=app.config["GIT_COMMIT"],
        env=app.config["APP_ENV"],
    )

    loan_events = Counter(
        "library_loan_events_total",
        "Circulation events by action (borrow, return, renew, reserve)",
        ["action"],
        registry=registry,
    )
    logins = Counter(
        "library_logins_total", "Sign-in attempts by outcome", ["outcome"], registry=registry
    )

    def _query(fn):
        def wrapped():
            with app.app_context():
                try:
                    return fn()
                except Exception:  # database unavailable: report -1 instead of failing the scrape
                    return -1
        return wrapped

    from .models import Book, Loan, Reservation, User, utcnow

    Gauge("library_active_loans", "Books currently on loan", registry=registry).set_function(
        _query(lambda: Loan.query.filter(Loan.returned_at.is_(None)).count())
    )
    Gauge("library_overdue_loans", "Loans past their due date", registry=registry).set_function(
        _query(
            lambda: Loan.query.filter(Loan.returned_at.is_(None), Loan.due_at < utcnow()).count()
        )
    )
    Gauge(
        "library_waiting_reservations", "Reservations waiting in a queue", registry=registry
    ).set_function(
        _query(lambda: Reservation.query.filter_by(status=Reservation.WAITING).count())
    )
    Gauge("library_books", "Titles in the catalogue", registry=registry).set_function(
        _query(lambda: Book.query.count())
    )
    Gauge("library_members", "Registered members", registry=registry).set_function(
        _query(lambda: User.query.filter_by(role=User.ROLE_MEMBER).count())
    )

    app.extensions["shelf_metrics"] = {
        "registry": registry,
        "loan_events": loan_events,
        "logins": logins,
    }
    return exporter


def record(metric: str, label: str):
    metrics = current_app.extensions.get("shelf_metrics")
    if metrics:
        metrics[metric].labels(label).inc()
