"""Fabric Studio — person + fabric + outfit -> virtual try-on.

Wired into the existing Flask app by server.py:

    from fabric_studio import register
    register(app, admin_required=requires_admin)

Everything else (catalogues, processing, composition, providers, history)
lives inside this package so the existing Virtual Try-On flow is untouched.
"""
from .errors import log  # noqa: F401

__all__ = ["register", "run_startup_tasks"]


def register(app, admin_required):
    """Attach the Fabric Studio blueprint to an existing Flask app."""
    from .routes import create_blueprint

    app.register_blueprint(create_blueprint(admin_required))
    return app


def run_startup_tasks(background=True):
    """Seed catalogues and warm caches without blocking the web server.

    Failures are logged and swallowed: a Fabric Studio problem must never stop
    the existing store and Virtual Try-On from serving.
    """
    import threading

    def task():
        try:
            from . import imaging
            if not imaging.PILLOW_AVAILABLE:
                log.warning(
                    "Fabric Studio disabled: Pillow is not installed. "
                    "Run `pip install -r requirements.txt` to enable it."
                )
                return
            from .migrations import run_migrations
            result = run_migrations()
            log.info("Fabric Studio migrations applied: %s", result.get("applied"))
        except Exception as exc:  # pragma: no cover - startup must not fail
            log.exception("Fabric Studio startup tasks failed: %s", exc)

    if background:
        thread = threading.Thread(target=task, name="fabric-studio-startup", daemon=True)
        thread.start()
        return thread
    task()
    return None
