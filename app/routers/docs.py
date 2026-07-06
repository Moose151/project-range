import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import bleach
import markdown as md_lib
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_range_state, require_supervisor
from app.models import AuditLog, DocPage, DocVersion, User

router = APIRouter(prefix="/docs")
from app.templating import templates

VERSION_HISTORY_PATH = Path(__file__).resolve().parents[2] / "docs" / "VERSION_HISTORY.md"

ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "pre", "code", "blockquote",
    "ul", "ol", "li",
    "strong", "em", "del", "s",
    "img",
]
ALLOWED_ATTRS = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "img": ["src", "alt", "title", "width", "height"],
    "th": ["align"],
    "td": ["align"],
    "a": ["href", "title", "name"],
    "code": ["class"],
    "pre": ["class"],
}


def _render_markdown(content: str) -> str:
    html = md_lib.markdown(
        content,
        extensions=["tables", "fenced_code", "toc", "nl2br"],
    )
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)


def _slugify(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:200]


def _next_version(db: Session, page_id: int) -> int:
    existing = db.query(DocVersion).filter(DocVersion.page_id == page_id).count()
    return existing + 1


def _doc_categories(db: Session, published_only: bool = False) -> list[str]:
    q = db.query(DocPage.category).filter(DocPage.category != None, DocPage.category != "")
    if published_only:
        q = q.filter(DocPage.is_published == True)
    return [row[0] for row in q.distinct().order_by(DocPage.category).all()]


# ── List / Home ────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def docs_home(
    request: Request,
    q: str = "",
    category: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(DocPage).filter(DocPage.is_published == True)
    categories = _doc_categories(db, published_only=True)
    if category:
        query = query.filter(DocPage.category == category)
    if q:
        q_lower = f"%{q.lower()}%"
        query = query.filter(
            or_(DocPage.title.ilike(q_lower), DocPage.content.ilike(q_lower), DocPage.tags.ilike(q_lower))
        )
    pages = query.order_by(DocPage.title).all()

    pending_count = 0
    if current_user.role == "administrator":
        pending_count = db.query(DocVersion).filter(DocVersion.approval_status == "pending").count()

    return templates.TemplateResponse(request, "docs_home.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "pages": pages,
        "q": q,
        "category": category,
        "categories": categories,
        "pending_count": pending_count,
        "page": "docs",
        "toast": request.query_params.get("toast", ""),
    })


# ── New page (administrator only) ─────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def docs_new_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    return templates.TemplateResponse(request, "docs_edit.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "doc_page": None,
        "mode": "new",
        "categories": _doc_categories(db),
        "page": "docs",
    })


@router.post("/new")
async def docs_create_page(
    request: Request,
    title: str = Form(...),
    content: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    change_summary: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    title = title.strip()
    slug = _slugify(title)

    # Ensure unique slug
    base_slug = slug
    counter = 1
    while db.query(DocPage).filter(DocPage.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    now = datetime.utcnow()
    doc = DocPage(
        title=title,
        slug=slug,
        content=content,
        category=category.strip() or None,
        tags=tags.strip() or None,
        is_published=True,
        created_by_id=current_user.id,
    )
    db.add(doc)
    db.flush()
    db.add(DocVersion(
        page_id=doc.id,
        version_number=1,
        content=content,
        change_summary=change_summary.strip() or "Page created",
        approval_status="approved",
        created_by_id=current_user.id,
        approved_by_id=current_user.id,
        approved_at=now,
    ))
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="doc_create",
        entity_type="DocPage",
        entity_id=doc.id,
        new_value=title,
        comment=change_summary.strip() or None,
    ))
    db.commit()
    return RedirectResponse(f"/docs/{slug}?toast=Page+created", status_code=302)


# ── Proposals / approval queue (administrator only) ───────────────────────────────

@router.get("/proposals", response_class=HTMLResponse)
async def docs_proposals(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    proposals = (
        db.query(DocVersion)
        .filter(DocVersion.approval_status == "pending")
        .order_by(DocVersion.created_at)
        .all()
    )
    # Annotate each proposal so the template can warn about concurrent-edit
    # conflicts (page changed since the edit was drafted).
    for v in proposals:
        v.conflict = _version_has_conflict(v)
        v.current_content = v.page.content
    return templates.TemplateResponse(request, "docs_approval.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "proposals": proposals,
        "page": "docs",
        "toast": request.query_params.get("toast", ""),
    })


@router.get("/version-history", response_class=HTMLResponse)
async def docs_version_history(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = VERSION_HISTORY_PATH.read_text(encoding="utf-8") if VERSION_HISTORY_PATH.exists() else "# Version History\n\nNo version history document found."
    rendered = _render_markdown(content)
    return templates.TemplateResponse(request, "version_history.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "rendered": rendered,
        "page": "version_history",
    })


@router.get("/deleted", response_class=HTMLResponse)
async def docs_deleted(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    pages = db.query(DocPage).filter(DocPage.is_published == False).order_by(DocPage.updated_at.desc(), DocPage.title).all()
    return templates.TemplateResponse(request, "docs_deleted.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "pages": pages,
        "page": "docs",
        "toast": request.query_params.get("toast", ""),
    })


@router.post("/deleted/{page_id}/restore")
async def docs_restore_deleted(
    page_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    doc = db.query(DocPage).filter(DocPage.id == page_id, DocPage.is_published == False).first()
    if not doc:
        return RedirectResponse("/docs/deleted?toast=Deleted+page+not+found", status_code=302)
    doc.is_published = True
    doc.updated_by_id = current_user.id
    doc.updated_at = datetime.utcnow()
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="doc_restore_deleted",
        entity_type="DocPage",
        entity_id=doc.id,
        previous_value=doc.title,
        comment="Restored documentation page from recycle bin",
    ))
    db.commit()
    return RedirectResponse(f"/docs/{doc.slug}?toast=Documentation+page+restored", status_code=302)


@router.post("/deleted/{page_id}/permanent-delete")
async def docs_permanent_delete(
    page_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    doc = db.query(DocPage).filter(DocPage.id == page_id, DocPage.is_published == False).first()
    if not doc:
        return RedirectResponse("/docs/deleted?toast=Deleted+page+not+found", status_code=302)
    doc_id = doc.id
    title = doc.title
    db.delete(doc)
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="doc_permanent_delete",
        entity_type="DocPage",
        entity_id=doc_id,
        previous_value=title,
        comment="Permanently deleted documentation page",
    ))
    db.commit()
    return RedirectResponse("/docs/deleted?toast=Documentation+page+permanently+deleted", status_code=302)


def _version_has_conflict(version: DocVersion) -> bool:
    """A pending edit conflicts if the live page has changed since the edit was
    drafted — approving it would overwrite those newer changes."""
    if version.base_content is None:
        return False
    return version.base_content != version.page.content


@router.post("/versions/{vid}/approve")
async def docs_approve(
    vid: int,
    confirm_conflict: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    version = db.query(DocVersion).filter(DocVersion.id == vid).first()
    if version and version.approval_status == "pending":
        # Guard against silently overwriting newer changes. If the page moved on
        # since this edit was proposed, require the admin to explicitly confirm.
        if _version_has_conflict(version) and confirm_conflict != "1":
            return RedirectResponse(
                "/docs/proposals?toast=Conflict:+the+page+changed+since+this+edit+was+proposed."
                "+Review+the+differences+and+confirm+before+publishing.",
                status_code=302,
            )
        now = datetime.utcnow()
        version.approval_status = "approved"
        version.approved_by_id = current_user.id
        version.approved_at = now

        # Apply the approved content to the page
        page = version.page
        page.content = version.content
        page.updated_by_id = current_user.id
        page.updated_at = now

        db.add(AuditLog(
            user_id=current_user.id,
            action_type="doc_approve",
            entity_type="DocVersion",
            entity_id=version.id,
            comment=f"Approved edit for page: {page.title}",
        ))
        db.commit()
    return RedirectResponse("/docs/proposals?toast=Edit+approved+and+published", status_code=302)


@router.post("/versions/{vid}/reject")
async def docs_reject(
    vid: int,
    rejection_reason: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    version = db.query(DocVersion).filter(DocVersion.id == vid).first()
    if version and version.approval_status == "pending":
        version.approval_status = "rejected"
        version.approved_by_id = current_user.id
        version.approved_at = datetime.utcnow()
        version.rejection_reason = rejection_reason.strip() or None
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="doc_reject",
            entity_type="DocVersion",
            entity_id=version.id,
            comment=rejection_reason.strip() or None,
        ))
        db.commit()
    return RedirectResponse("/docs/proposals?toast=Edit+rejected", status_code=302)


@router.post("/versions/{vid}/restore")
async def docs_restore_version(
    vid: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    version = db.query(DocVersion).filter(DocVersion.id == vid).first()
    if not version:
        return RedirectResponse("/docs", status_code=302)

    page = version.page
    now = datetime.utcnow()
    next_ver = _next_version(db, page.id)
    db.add(DocVersion(
        page_id=page.id,
        version_number=next_ver,
        content=version.content,
        change_summary=f"Restored from version {version.version_number}",
        approval_status="approved",
        created_by_id=current_user.id,
        approved_by_id=current_user.id,
        approved_at=now,
    ))
    page.content = version.content
    page.updated_by_id = current_user.id
    page.updated_at = now
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="doc_restore",
        entity_type="DocPage",
        entity_id=page.id,
        comment=f"Restored to version {version.version_number}",
    ))
    db.commit()
    return RedirectResponse(f"/docs/{page.slug}?toast=Page+restored+to+version+{version.version_number}", status_code=302)


# ── View page ─────────────────────────────────────────────────────────────────

@router.post("/{slug}/delete")
async def docs_delete_page(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    doc = db.query(DocPage).filter(DocPage.slug == slug, DocPage.is_published == True).first()
    if not doc:
        return RedirectResponse("/docs?toast=Documentation+page+not+found", status_code=302)

    doc.is_published = False
    doc.updated_by_id = current_user.id
    doc.updated_at = datetime.utcnow()
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="doc_delete",
        entity_type="DocPage",
        entity_id=doc.id,
        previous_value=doc.title,
        comment="Documentation page moved to recycle bin",
    ))
    db.commit()
    return RedirectResponse("/docs?toast=Documentation+page+deleted", status_code=302)


@router.get("/{slug}", response_class=HTMLResponse)
async def docs_view(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(DocPage).filter(DocPage.slug == slug, DocPage.is_published == True).first()
    if not doc:
        return templates.TemplateResponse(request, "error.html", {
            "code": 404,
            "message": "Documentation page not found.",
        }, status_code=404)

    rendered = _render_markdown(doc.content)
    related_docs = []
    if doc.category:
        related_docs = (
            db.query(DocPage)
            .filter(DocPage.is_published == True, DocPage.id != doc.id, DocPage.category == doc.category)
            .order_by(DocPage.title)
            .limit(5)
            .all()
        )
    return templates.TemplateResponse(request, "docs_page.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "doc_page": doc,
        "related_docs": related_docs,
        "rendered": rendered,
        "page": "docs",
        "toast": request.query_params.get("toast", ""),
    })


# ── Print view ────────────────────────────────────────────────────────────────

@router.get("/{slug}/print", response_class=HTMLResponse)
async def docs_print(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(DocPage).filter(DocPage.slug == slug, DocPage.is_published == True).first()
    if not doc:
        return RedirectResponse("/docs", status_code=302)
    rendered = _render_markdown(doc.content)
    return templates.TemplateResponse(request, "docs_print.html", {
        "doc_page": doc,
        "rendered": rendered,
    })


# ── Edit / Propose ────────────────────────────────────────────────────────────

@router.get("/{slug}/edit", response_class=HTMLResponse)
async def docs_edit_page(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(DocPage).filter(DocPage.slug == slug, DocPage.is_published == True).first()
    if not doc:
        return RedirectResponse("/docs", status_code=302)
    mode = "edit" if current_user.role == "administrator" else "propose"
    return templates.TemplateResponse(request, "docs_edit.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "doc_page": doc,
        "mode": mode,
        "categories": _doc_categories(db),
        "page": "docs",
    })


@router.post("/{slug}/edit")
async def docs_submit_edit(
    slug: str,
    request: Request,
    title: str = Form(""),
    content: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    change_summary: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(DocPage).filter(DocPage.slug == slug, DocPage.is_published == True).first()
    if not doc:
        return RedirectResponse("/docs", status_code=302)

    now = datetime.utcnow()
    next_ver = _next_version(db, doc.id)
    base_content = doc.content  # content this edit was drafted against

    if current_user.role == "administrator":
        # Direct publish
        if title.strip():
            doc.title = title.strip()
        doc.category = category.strip() or None
        doc.tags = tags.strip() or None
        doc.content = content
        doc.updated_by_id = current_user.id
        doc.updated_at = now
        db.add(DocVersion(
            page_id=doc.id,
            version_number=next_ver,
            content=content,
            base_content=base_content,
            change_summary=change_summary.strip() or "Direct edit",
            approval_status="approved",
            created_by_id=current_user.id,
            approved_by_id=current_user.id,
            approved_at=now,
        ))
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="doc_edit",
            entity_type="DocPage",
            entity_id=doc.id,
            comment=change_summary.strip() or None,
        ))
        db.commit()
        return RedirectResponse(f"/docs/{slug}?toast=Page+updated", status_code=302)
    else:
        # User — goes to approval queue
        db.add(DocVersion(
            page_id=doc.id,
            version_number=next_ver,
            content=content,
            base_content=base_content,
            change_summary=change_summary.strip() or "Proposed edit",
            approval_status="pending",
            created_by_id=current_user.id,
        ))
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="doc_propose",
            entity_type="DocPage",
            entity_id=doc.id,
            comment=change_summary.strip() or None,
        ))
        db.commit()
        return RedirectResponse(f"/docs/{slug}?toast=Edit+submitted+for+administrator+approval", status_code=302)


# ── Version history (administrator only) ────────────────────────────────────────

@router.get("/{slug}/history", response_class=HTMLResponse)
async def docs_history(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    doc = db.query(DocPage).filter(DocPage.slug == slug).first()
    if not doc:
        return RedirectResponse("/docs", status_code=302)
    versions = (
        db.query(DocVersion)
        .filter(DocVersion.page_id == doc.id)
        .order_by(DocVersion.version_number.desc())
        .all()
    )
    return templates.TemplateResponse(request, "docs_history.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "doc_page": doc,
        "versions": versions,
        "page": "docs",
        "toast": request.query_params.get("toast", ""),
    })
