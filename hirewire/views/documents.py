"""Documents: résumé and cover letter versions, and which applications used them."""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from .. import db, documents
from ..auth import login_required, not_for_demo
from ..models import DOCUMENT_KINDS, Application, Document
from ..ownership import get_mine, mine

bp = Blueprint("documents", __name__, url_prefix="/documents")


def kinds():
    return list(DOCUMENT_KINDS.items())


@bp.get("/")
@login_required
def index():
    s = db.session()
    files = s.scalars(mine(Document).order_by(Document.kind, Document.name, Document.created_at.desc())).all()
    used = dict(s.execute(
        select(Document.id, func.count(Application.id))
        .join(Application, or_(Application.resume_id == Document.id, Application.cover_letter_id == Document.id))
        .where(Document.user_id == g.user.id).group_by(Document.id)).all())
    groups = [(label, [doc for doc in files if doc.kind == kind]) for kind, label in DOCUMENT_KINDS.items()]
    return render_template("documents/list.html", groups=[group for group in groups if group[1]], used=used,
                           size_words=documents.size_words)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    errors, values = {}, {"kind": request.args.get("kind", "resume")}
    if request.method == "POST":
        not_for_demo("The demo can't add files. Try the sample files instead.")
        values, errors = documents.read_form(request.form)
        file, problem = documents.read_file(request.files.get("file"))
        if problem:
            errors["file"] = problem
        if not errors:
            s = db.session()
            s.add(Document(user_id=g.user.id, **values, **file))
            s.commit()
            flash("The file has been added.")
            return redirect(url_for("documents.index"))
    return render_template("documents/form.html", values=values, errors=errors, document=None, kinds=kinds()), \
        400 if errors else 200


@bp.route("/<int:document_id>/edit", methods=["GET", "POST"])
@login_required
def edit(document_id):
    document = get_mine(Document, document_id)
    errors = {}
    values = {"name": document.name, "version_label": document.version_label, "kind": document.kind}
    if request.method == "POST":
        values, errors = documents.read_form(request.form)
        if not errors:
            for name, value in values.items():
                setattr(document, name, value)
            db.session().commit()
            flash("Your changes have been saved.")
            return redirect(url_for("documents.index"))
    return render_template("documents/form.html", values=values, errors=errors, document=document, kinds=kinds()), \
        400 if errors else 200


@bp.get("/<int:document_id>/file")
@login_required
def download(document_id):
    document = get_mine(Document, document_id)
    data = db.session().scalar(select(Document.data).where(Document.id == document.id))
    return data, 200, {
        "Content-Type": document.mime,
        # attachment: the browser saves it rather than opening it inside this site.
        "Content-Disposition": f'attachment; filename="{document.filename}"',
        "Cache-Control": "private, no-store",
    }


@bp.post("/<int:document_id>/delete")
@login_required
def delete(document_id):
    document = get_mine(Document, document_id)
    s = db.session()
    s.delete(document)  # applications that used it keep everything else (ON DELETE SET NULL)
    s.commit()
    flash("The file has been deleted.")
    return redirect(url_for("documents.index"))
