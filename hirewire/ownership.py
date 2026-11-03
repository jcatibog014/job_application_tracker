"""Every page only sees the logged-in person's own rows.

Someone else's id in a URL gives 404, the same as an id that doesn't exist,
so nobody can even find out which ids are in use.
"""
from flask import abort, g
from sqlalchemy import select

from . import db
from .models import Application


def mine(model):
    """A SELECT of the logged-in user's rows of a model that has user_id."""
    return select(model).where(model.user_id == g.user.id)


def get_mine(model, row_id, *options):
    """One of the user's own rows by id, or 404."""
    row = db.session().scalar(mine(model).where(model.id == row_id).options(*options))
    if row is None:
        abort(404)
    return row


def get_child(model, row_id, *options):
    """A row that belongs to one of the user's applications (a note, an interview...), or 404."""
    row = db.session().scalar(
        select(model).join(Application, model.application_id == Application.id)
        .where(model.id == row_id, Application.user_id == g.user.id).options(*options))
    if row is None:
        abort(404)
    return row
