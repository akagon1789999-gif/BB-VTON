"""Studio — fabric + model photo -> the person wearing that cloth.

Two uploads and one call to FASHN `tryon-max`, with the prompt composed from
the garment type, the template and the coverage the customer chose. The cut,
drape, embroidery placement, identity and pose survive; only the cloth changes.

Wired into the existing Flask app by server.py:

    import studio
    studio.register(app)

Everything that touches the FASHN key runs here. The key is never sent to the
browser.
"""
from .errors import StudioError, log  # noqa: F401

__all__ = ["register", "StudioError", "log"]


def register(app):
    """Attach the studio blueprint to an existing Flask app."""
    from .routes import create_blueprint

    app.register_blueprint(create_blueprint())
    return app
