"""WSGI entry for production servers (e.g. gunicorn ``wsgi:application``)."""

from hypatia import create_app

application = create_app()
app = application  # alias: ``gunicorn wsgi:app`` matches README examples
