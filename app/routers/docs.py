import re
from html import escape
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import bleach
import markdown as md_lib
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_range_state, require_supervisor
from app.models import AuditLog, DocAlias, DocLink, DocPage, DocVersion, User

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
    "a": ["href", "title", "name", "class"],
    "code": ["class"],
    "pre": ["class"],
}
WIKI_LINK_RE = re.compile(r"\[\[([^\[\]\n|]+)(?:\|([^\[\]\n]+))?\]\]")
DOC_VISIBILITY_LABELS = {
    "all": "All logged-in users",
    "users": "Users and administrators",
    "admins": "Administrators only",
}
DOC_VISIBILITY_VALUES = set(DOC_VISIBILITY_LABELS)
DOC_PAGE_TEMPLATES = {
    "blank": {"label": "Blank", "category": "", "tags": "", "content": ""},
    "device": {
        "label": "Device",
        "category": "Devices",
        "tags": "device, reference",
        "content": """## Purpose

## Location

## Network Details

## Access

## Normal State

## Common Faults

## Recovery Steps

## Related Pages
""",
    },
    "procedure": {
        "label": "Procedure",
        "category": "Operations",
        "tags": "procedure, checklist",
        "content": """## Purpose

## Preconditions

## Steps

1.

## Verification

## Rollback / Stop Criteria

## Related Pages
""",
    },
    "troubleshooting": {
        "label": "Troubleshooting",
        "category": "Troubleshooting",
        "tags": "fault, troubleshooting",
        "content": """## Symptoms

## Likely Causes

## Checks

## Corrective Actions

## Escalation

## Related Pages
""",
    },
    "configuration": {
        "label": "Configuration",
        "category": "Configuration",
        "tags": "configuration",
        "content": """## Scope

## Current Settings

## Change Procedure

## Validation

## Notes

## Related Pages
""",
    },
    "range-rule": {
        "label": "Range Rule",
        "category": "Safety",
        "tags": "rule, safety",
        "content": """## Rule

## Applies To

## Rationale

## Operator Actions

## Exceptions

## Related Pages
""",
    },
}


def _render_markdown(content: str) -> str:
    html = md_lib.markdown(
        content,
        extensions=["tables", "fenced_code", "toc", "nl2br"],
    )
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)


def _normalise_wiki_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip())


def _slugify(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:200]


def _normalise_visibility(value: str) -> str:
    value = (value or "all").strip().lower()
    return value if value in DOC_VISIBILITY_VALUES else "all"


def _visibility_filter(user: User):
    if user.role == "administrator":
        return True
    if user.role == "user":
        return or_(DocPage.visibility == None, DocPage.visibility.in_(["all", "users"]))
    return or_(DocPage.visibility == None, DocPage.visibility == "all")


def _visible_docs_query(db: Session, user: User):
    return db.query(DocPage).filter(DocPage.is_published == True).filter(_visibility_filter(user))


def _can_view_doc(doc: DocPage, user: User) -> bool:
    vis = _normalise_visibility(doc.visibility)
    if user.role == "administrator":
        return True
    if user.role == "user":
        return vis in {"all", "users"}
    return vis == "all"


def _resolve_wiki_page(db: Session, title: str, current_user: User | None = None) -> DocPage | None:
    title = _normalise_wiki_title(title)
    slug = _slugify(title)
    page_query = db.query(DocPage).filter(
        DocPage.is_published == True,
        or_(
            func.lower(DocPage.title) == title.lower(),
            DocPage.slug == slug,
        ),
    )
    if current_user is not None:
        page_query = page_query.filter(_visibility_filter(current_user))
    page = page_query.order_by(DocPage.title).first()
    if page:
        return page
    alias_query = (
        db.query(DocAlias)
        .join(DocPage, DocPage.id == DocAlias.page_id)
        .filter(
            DocPage.is_published == True,
            or_(
                func.lower(DocAlias.alias_title) == title.lower(),
                DocAlias.alias_slug == slug,
            ),
        )
    )
    if current_user is not None:
        alias_query = alias_query.filter(_visibility_filter(current_user))
    alias = alias_query.order_by(DocAlias.alias_title).first()
    return alias.page if alias else None


def _resolve_doc_path(db: Session, slug: str, current_user: User) -> tuple[DocPage | None, DocAlias | None]:
    page = db.query(DocPage).filter(DocPage.slug == slug, DocPage.is_published == True).filter(_visibility_filter(current_user)).first()
    if page:
        return page, None
    alias = (
        db.query(DocAlias)
        .join(DocPage, DocPage.id == DocAlias.page_id)
        .filter(DocAlias.alias_slug == slug, DocPage.is_published == True)
        .filter(_visibility_filter(current_user))
        .first()
    )
    return (alias.page, alias) if alias else (None, None)


def _extract_wiki_links(content: str) -> list[str]:
    titles = []
    seen = set()
    for match in WIKI_LINK_RE.finditer(content or ""):
        title = _normalise_wiki_title(match.group(1))
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
    return titles


def _render_wiki_links(content: str, db: Session, current_user: User | None = None) -> str:
    def replace(match: re.Match) -> str:
        title = _normalise_wiki_title(match.group(1))
        label = _normalise_wiki_title(match.group(2) or title)
        if not title:
            return ""
        target = _resolve_wiki_page(db, title, current_user=current_user)
        if target:
            return f'<a href="/docs/{escape(target.slug, quote=True)}" class="wiki-link">{escape(label)}</a>'
        query = urlencode({"title": title})
        return (
            f'<a href="/docs/new?{query}" class="wiki-link wiki-missing" '
            f'title="Create missing wiki page: {escape(title, quote=True)}">{escape(label)}</a>'
        )

    return WIKI_LINK_RE.sub(replace, content or "")


def _render_doc_content(content: str, db: Session, current_user: User | None = None) -> str:
    return _render_markdown(_render_wiki_links(content, db, current_user=current_user))


def _sync_doc_links(db: Session, page: DocPage) -> None:
    db.query(DocLink).filter(DocLink.from_page_id == page.id).delete()
    for title in _extract_wiki_links(page.content):
        target = _resolve_wiki_page(db, title)
        db.add(DocLink(
            from_page_id=page.id,
            target_title=title,
            target_slug=target.slug if target else _slugify(title),
            target_page_id=target.id if target else None,
            is_missing=target is None,
        ))


def _sync_all_doc_links(db: Session) -> None:
    pages = db.query(DocPage).filter(DocPage.is_published == True).all()
    for page in pages:
        _sync_doc_links(db, page)


def _ensure_doc_link_index(db: Session) -> None:
    if db.query(DocPage).filter(DocPage.is_published == True).count() and db.query(DocLink).count() == 0:
        _sync_all_doc_links(db)
        db.commit()


def _alias_conflict(db: Session, alias_slug: str, alias_id: int | None = None) -> str:
    if db.query(DocPage).filter(DocPage.slug == alias_slug).first():
        return "A documentation page already uses that URL."
    q = db.query(DocAlias).filter(DocAlias.alias_slug == alias_slug)
    if alias_id is not None:
        q = q.filter(DocAlias.id != alias_id)
    if q.first():
        return "Another alias already uses that URL."
    return ""


def _next_version(db: Session, page_id: int) -> int:
    existing = db.query(DocVersion).filter(DocVersion.page_id == page_id).count()
    return existing + 1


def _doc_categories(db: Session, published_only: bool = False, current_user: User | None = None) -> list[str]:
    q = db.query(DocPage.category).filter(DocPage.category != None, DocPage.category != "")
    if published_only:
        q = q.filter(DocPage.is_published == True)
    if current_user is not None:
        q = q.filter(_visibility_filter(current_user))
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
    _ensure_doc_link_index(db)
    query = _visible_docs_query(db, current_user)
    categories = _doc_categories(db, published_only=True, current_user=current_user)
    if category:
        query = query.filter(DocPage.category == category)
    if q:
        q_lower = f"%{q.lower()}%"
        query = query.filter(
            or_(DocPage.title.ilike(q_lower), DocPage.content.ilike(q_lower), DocPage.tags.ilike(q_lower))
        )
    pages = query.order_by(DocPage.title).all()
    all_pages = _visible_docs_query(db, current_user).order_by(DocPage.title).all()
    recent_pages = (
        _visible_docs_query(db, current_user)
        .order_by(func.coalesce(DocPage.updated_at, DocPage.created_at).desc())
        .limit(8)
        .all()
    )
    wanted_links = (
        db.query(DocLink.target_title, DocLink.target_slug, func.count(DocLink.id).label("count"))
        .join(DocPage, DocPage.id == DocLink.from_page_id)
        .filter(DocPage.is_published == True, DocLink.is_missing == True)
        .filter(_visibility_filter(current_user))
        .group_by(DocLink.target_title, DocLink.target_slug)
        .order_by(func.count(DocLink.id).desc(), DocLink.target_title)
        .limit(8)
        .all()
    )
    uncategorized_count = (
        _visible_docs_query(db, current_user)
        .filter(or_(DocPage.category == None, DocPage.category == ""))
        .count()
    )

    pending_count = 0
    if current_user.role == "administrator":
        pending_count = db.query(DocVersion).filter(DocVersion.approval_status == "pending").count()

    return templates.TemplateResponse(request, "docs_home.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "pages": pages,
        "all_pages": all_pages,
        "recent_pages": recent_pages,
        "wanted_links": wanted_links,
        "uncategorized_count": uncategorized_count,
        "q": q,
        "category": category,
        "categories": categories,
        "visibility_labels": DOC_VISIBILITY_LABELS,
        "pending_count": pending_count,
        "page": "docs",
        "toast": request.query_params.get("toast", ""),
    })


# ── New page (administrator only) ─────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def docs_new_page(
    request: Request,
    title: str = "",
    page_template: str = "blank",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    selected_template = DOC_PAGE_TEMPLATES.get(page_template, DOC_PAGE_TEMPLATES["blank"])
    return templates.TemplateResponse(request, "docs_edit.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "doc_page": None,
        "draft_title": title.strip(),
        "draft_content": selected_template["content"],
        "draft_category": selected_template["category"],
        "draft_tags": selected_template["tags"],
        "page_templates": DOC_PAGE_TEMPLATES,
        "selected_template": page_template if page_template in DOC_PAGE_TEMPLATES else "blank",
        "mode": "new",
        "categories": _doc_categories(db),
        "visibility_labels": DOC_VISIBILITY_LABELS,
        "page": "docs",
    })


@router.post("/new")
async def docs_create_page(
    request: Request,
    title: str = Form(...),
    content: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    visibility: str = Form("all"),
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
        visibility=_normalise_visibility(visibility),
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
    _sync_doc_links(db, doc)
    _sync_all_doc_links(db)
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


@router.get("/wanted", response_class=HTMLResponse)
async def docs_wanted(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_doc_link_index(db)
    wanted_links = (
        db.query(DocLink.target_title, DocLink.target_slug, func.count(DocLink.id).label("count"))
        .join(DocPage, DocPage.id == DocLink.from_page_id)
        .filter(DocPage.is_published == True, DocLink.is_missing == True)
        .filter(_visibility_filter(current_user))
        .group_by(DocLink.target_title, DocLink.target_slug)
        .order_by(func.count(DocLink.id).desc(), DocLink.target_title)
        .all()
    )
    sources = {
        row.target_title: (
            db.query(DocPage)
            .join(DocLink, DocLink.from_page_id == DocPage.id)
            .filter(DocPage.is_published == True, DocLink.is_missing == True, DocLink.target_title == row.target_title)
            .filter(_visibility_filter(current_user))
            .order_by(DocPage.title)
            .all()
        )
        for row in wanted_links
    }
    return templates.TemplateResponse(request, "docs_wanted.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "wanted_links": wanted_links,
        "sources": sources,
        "page": "docs",
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
    _sync_doc_links(db, doc)
    _sync_all_doc_links(db)
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
    _sync_all_doc_links(db)
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
        _sync_doc_links(db, page)
        _sync_all_doc_links(db)

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
    _sync_doc_links(db, page)
    _sync_all_doc_links(db)
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

@router.post("/{slug}/aliases")
async def docs_add_alias(
    slug: str,
    alias_title: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    doc = db.query(DocPage).filter(DocPage.slug == slug, DocPage.is_published == True).first()
    if not doc:
        return RedirectResponse("/docs?toast=Documentation+page+not+found", status_code=302)

    alias_title = _normalise_wiki_title(alias_title)
    alias_slug = _slugify(alias_title)
    if not alias_title or not alias_slug:
        return RedirectResponse(f"/docs/{doc.slug}?toast=Alias+title+is+required", status_code=302)
    conflict = _alias_conflict(db, alias_slug)
    if conflict:
        return RedirectResponse(f"/docs/{doc.slug}?toast={urlencode({'': conflict})[1:]}", status_code=302)

    alias = DocAlias(
        page_id=doc.id,
        alias_title=alias_title,
        alias_slug=alias_slug,
        created_by_id=current_user.id,
    )
    db.add(alias)
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="doc_alias_create",
        entity_type="DocPage",
        entity_id=doc.id,
        new_value=alias_title,
        comment=f"Added documentation alias for {doc.title}",
    ))
    _sync_all_doc_links(db)
    db.commit()
    return RedirectResponse(f"/docs/{doc.slug}?toast=Alias+added", status_code=302)


@router.post("/{slug}/aliases/{alias_id}/delete")
async def docs_delete_alias(
    slug: str,
    alias_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    doc = db.query(DocPage).filter(DocPage.slug == slug).first()
    alias = db.query(DocAlias).filter(DocAlias.id == alias_id, DocAlias.page_id == (doc.id if doc else 0)).first()
    if not doc or not alias:
        return RedirectResponse("/docs?toast=Alias+not+found", status_code=302)
    alias_title = alias.alias_title
    db.delete(alias)
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="doc_alias_delete",
        entity_type="DocPage",
        entity_id=doc.id,
        previous_value=alias_title,
        comment=f"Removed documentation alias for {doc.title}",
    ))
    _sync_all_doc_links(db)
    db.commit()
    return RedirectResponse(f"/docs/{doc.slug}?toast=Alias+removed", status_code=302)

@router.post("/{slug}/delete")
async def docs_delete_page(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    _ensure_doc_link_index(db)
    doc = db.query(DocPage).filter(DocPage.slug == slug, DocPage.is_published == True).first()
    if not doc:
        return RedirectResponse("/docs?toast=Documentation+page+not+found", status_code=302)

    doc.is_published = False
    doc.updated_by_id = current_user.id
    doc.updated_at = datetime.utcnow()
    _sync_all_doc_links(db)
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
    _ensure_doc_link_index(db)
    doc, alias = _resolve_doc_path(db, slug, current_user)
    if not doc:
        return templates.TemplateResponse(request, "error.html", {
            "code": 404,
            "message": "Documentation page not found.",
        }, status_code=404)
    if alias:
        return RedirectResponse(f"/docs/{doc.slug}", status_code=302)

    rendered = _render_doc_content(doc.content, db, current_user=current_user)
    backlinks = (
        db.query(DocPage)
        .join(DocLink, DocLink.from_page_id == DocPage.id)
        .filter(DocPage.is_published == True, DocLink.target_page_id == doc.id, DocPage.id != doc.id)
        .filter(_visibility_filter(current_user))
        .order_by(DocPage.title)
        .all()
    )
    outgoing_links = (
        db.query(DocLink)
        .filter(DocLink.from_page_id == doc.id)
        .order_by(DocLink.is_missing.desc(), DocLink.target_title)
        .all()
    )
    related_docs = []
    if doc.category:
        related_docs = (
            db.query(DocPage)
            .filter(DocPage.is_published == True, DocPage.id != doc.id, DocPage.category == doc.category)
            .filter(_visibility_filter(current_user))
            .order_by(DocPage.title)
            .limit(5)
            .all()
        )
    return templates.TemplateResponse(request, "docs_page.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "doc_page": doc,
        "related_docs": related_docs,
        "backlinks": backlinks,
        "outgoing_links": outgoing_links,
        "aliases": doc.aliases,
        "visibility_labels": DOC_VISIBILITY_LABELS,
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
    doc, alias = _resolve_doc_path(db, slug, current_user)
    if not doc:
        return RedirectResponse("/docs", status_code=302)
    if alias:
        return RedirectResponse(f"/docs/{doc.slug}/print", status_code=302)
    rendered = _render_doc_content(doc.content, db, current_user=current_user)
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
    doc, alias = _resolve_doc_path(db, slug, current_user)
    if not doc:
        return RedirectResponse("/docs", status_code=302)
    if alias:
        return RedirectResponse(f"/docs/{doc.slug}/edit", status_code=302)
    mode = "edit" if current_user.role == "administrator" else "propose"
    return templates.TemplateResponse(request, "docs_edit.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "doc_page": doc,
        "mode": mode,
        "categories": _doc_categories(db),
        "visibility_labels": DOC_VISIBILITY_LABELS,
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
    visibility: str = Form("all"),
    change_summary: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc, alias = _resolve_doc_path(db, slug, current_user)
    if not doc:
        return RedirectResponse("/docs", status_code=302)
    if alias:
        return RedirectResponse(f"/docs/{doc.slug}/edit", status_code=302)

    now = datetime.utcnow()
    next_ver = _next_version(db, doc.id)
    base_content = doc.content  # content this edit was drafted against

    if current_user.role == "administrator":
        # Direct publish
        if title.strip():
            doc.title = title.strip()
        doc.category = category.strip() or None
        doc.tags = tags.strip() or None
        doc.visibility = _normalise_visibility(visibility)
        doc.content = content
        doc.updated_by_id = current_user.id
        doc.updated_at = now
        _sync_doc_links(db, doc)
        _sync_all_doc_links(db)
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
    doc, alias = _resolve_doc_path(db, slug, current_user)
    if not doc:
        return RedirectResponse("/docs", status_code=302)
    if alias:
        return RedirectResponse(f"/docs/{doc.slug}/history", status_code=302)
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
