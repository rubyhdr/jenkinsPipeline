"""Shelf: a small library management system (Flask application factory)."""
import logging
import time

import click
from flask import Flask, jsonify, render_template, request
from sqlalchemy import text

from .config import get_config
from .extensions import csrf, db, login_manager
from .models import User

# Placeholder that create_app refuses to run with outside development (see SECURITY_FINDINGS.md).
DEFAULT_SECRET = "dev-only-secret-change-me"  # nosec B105


def create_app(env=None):
    app = Flask(__name__)
    app.config.from_object(get_config(env))

    if app.config["APP_ENV"] in ("staging", "production") and app.config["SECRET_KEY"] == DEFAULT_SECRET:
        raise RuntimeError("SECRET_KEY must be set for staging and production.")

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)

    from .api import bp as api_bp
    from .web import admin, auth, main

    app.register_blueprint(main)
    app.register_blueprint(auth)
    app.register_blueprint(admin)
    app.register_blueprint(api_bp)

    if app.config["METRICS_ENABLED"]:
        from .metrics import init_metrics

        init_metrics(app)

    _register_ops_routes(app)
    _register_error_handlers(app)
    _register_cli(app)

    @app.context_processor
    def inject_globals():
        return {
            "app_version": app.config["APP_VERSION"],
            "app_env": app.config["APP_ENV"],
            "git_commit": app.config["GIT_COMMIT"],
        }

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data:; frame-ancestors 'none'",
        )
        return response

    return app


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def _register_ops_routes(app):
    @app.get("/health")
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            database = "ok"
        except Exception:  # pragma: no cover - exercised by the rollback demo
            app.logger.exception("Health check database probe failed")
            database = "unavailable"
        body = {
            "status": "ok" if database == "ok" else "degraded",
            "database": database,
            "version": app.config["APP_VERSION"],
            "commit": app.config["GIT_COMMIT"],
            "env": app.config["APP_ENV"],
        }
        return jsonify(body), 200 if database == "ok" else 503

    @app.get("/api/status")
    def api_status():
        return jsonify(
            name=app.config["APP_NAME"],
            version=app.config["APP_VERSION"],
            commit=app.config["GIT_COMMIT"],
            env=app.config["APP_ENV"],
        )

    if app.config["CHAOS_ENABLED"]:
        @app.get("/_chaos/error")
        def chaos_error():
            """Demo-only: return a 500 so the error-rate alert can be exercised."""
            app.logger.error("Chaos endpoint triggered a simulated failure")
            return jsonify(error="Simulated failure"), 500

        @app.get("/_chaos/slow")
        def chaos_slow():
            """Demo-only: respond slowly so the latency alert can be exercised."""
            seconds = min(float(request.args.get("seconds", "1.5")), 5.0)
            time.sleep(seconds)
            return jsonify(slept=seconds)


def _register_error_handlers(app):
    from .services import LibraryError, NotFoundError

    def _wants_json():
        return request.path.startswith("/api/")

    @app.errorhandler(NotFoundError)
    @app.errorhandler(404)
    def not_found(err):
        if _wants_json():
            return jsonify(error="Not found."), 404
        return render_template("error.html", code=404, message="We couldn't find that page."), 404

    @app.errorhandler(403)
    def forbidden(err):
        if _wants_json():
            return jsonify(error="Forbidden."), 403
        return render_template("error.html", code=403, message="You don't have access to that."), 403

    @app.errorhandler(LibraryError)
    def library_error(err):
        if _wants_json():
            return jsonify(error=str(err)), err.status_code
        return render_template("error.html", code=err.status_code, message=str(err)), err.status_code

    @app.errorhandler(500)
    def server_error(err):  # pragma: no cover
        if _wants_json():
            return jsonify(error="Internal server error."), 500
        return render_template("error.html", code=500, message="Something went wrong."), 500


def _register_cli(app):
    @app.cli.command("init-db")
    @click.option("--retries", default=30, help="Attempts while waiting for the database.")
    def init_db(retries):
        """Create tables, waiting for the database to accept connections."""
        for attempt in range(1, retries + 1):
            try:
                db.create_all()
                click.echo("Database ready.")
                return
            except Exception as exc:  # database container still starting
                click.echo(f"Database not ready (attempt {attempt}/{retries}): {exc.__class__.__name__}")
                time.sleep(2)
        raise click.ClickException("Database never became available.")

    @app.cli.command("seed")
    @click.option("--if-empty", is_flag=True, help="Only seed when there are no books yet.")
    def seed(if_empty):
        """Load demo books, members and loans."""
        from .seed import seed_database

        created = seed_database(only_if_empty=if_empty)
        click.echo("Seeded demo data." if created else "Database already has data; skipped seeding.")
