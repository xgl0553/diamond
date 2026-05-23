import datetime as dt
import secrets
from random import randint

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.models import AuthSession, CaptchaChallenge, CrawlBatch, FundHoldingItem, FundRankItem, Permission, RolePermission, User, UserRole
from app.security import hash_password, verify_password
from app.services.crawler import run_crawl

app = FastAPI(title="Fund Holdings Web")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def _create_captcha(db: Session) -> tuple[str, str]:
    a, b = randint(1, 9), randint(1, 9)
    key = secrets.token_hex(8)
    row = CaptchaChallenge(
        challenge_key=key,
        answer=str(a + b),
        expires_at=dt.datetime.utcnow() + dt.timedelta(minutes=5),
    )
    db.add(row)
    db.commit()
    return key, f"{a} + {b} = ?"


def _current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    session = db.query(AuthSession).filter(AuthSession.session_token == token).first()
    if not session or session.expires_at < dt.datetime.utcnow():
        return None
    return db.query(User).filter(User.id == session.user_id, User.is_active.is_(True)).first()


def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    user = _current_user(request, db)
    if not user:
        raise ValueError("not logged in")
    return user


def _has_permission(db: Session, user: User, perm_code: str) -> bool:
    if user.is_superadmin:
        return True
    return (
        db.query(RolePermission)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .filter(UserRole.user_id == user.id, Permission.perm_code == perm_code)
        .first()
        is not None
    )


def _summary_for_current_page(db: Session, batch_id: int, fund_codes: list[str]):
    if not fund_codes:
        return []
    return (
        db.query(
            FundHoldingItem.stock_code,
            FundHoldingItem.stock_name,
            func.sum(FundHoldingItem.market_value_10k).label("market_value_total"),
            func.sum(FundHoldingItem.shares_10k).label("shares_total"),
        )
        .filter(FundHoldingItem.batch_id == batch_id, FundHoldingItem.fund_code.in_(fund_codes))
        .group_by(FundHoldingItem.stock_code, FundHoldingItem.stock_name)
        .order_by(func.sum(FundHoldingItem.market_value_10k).desc())
        .all()
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    key, challenge = _create_captcha(db)
    return templates.TemplateResponse("login.html", {"request": request, "captcha_key": key, "challenge": challenge, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    captcha_key: str = Form(...),
    captcha_answer: str = Form(...),
    db: Session = Depends(get_db),
):
    challenge = db.query(CaptchaChallenge).filter(CaptchaChallenge.challenge_key == captcha_key).first()
    if not challenge or challenge.expires_at < dt.datetime.utcnow() or challenge.answer != captcha_answer.strip():
        new_key, question = _create_captcha(db)
        return templates.TemplateResponse("login.html", {"request": request, "captcha_key": new_key, "challenge": question, "error": "验证码错误或过期"})
    if challenge.used:
        new_key, question = _create_captcha(db)
        return templates.TemplateResponse("login.html", {"request": request, "captcha_key": new_key, "challenge": question, "error": "验证码已使用"})
    challenge.used = True
    db.commit()

    user = db.query(User).filter(User.username == username, User.is_active.is_(True)).first()
    if user and user.locked_until and user.locked_until > dt.datetime.utcnow():
        new_key, question = _create_captcha(db)
        return templates.TemplateResponse("login.html", {"request": request, "captcha_key": new_key, "challenge": question, "error": "账号已锁定，请稍后再试"})
    if not user or not verify_password(password, user.password_hash):
        if user:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= 3:
                user.locked_until = dt.datetime.utcnow() + dt.timedelta(minutes=30)
                user.failed_login_count = 0
            db.commit()
        new_key, question = _create_captcha(db)
        return templates.TemplateResponse("login.html", {"request": request, "captcha_key": new_key, "challenge": question, "error": "用户名或密码错误"})

    user.failed_login_count = 0
    user.locked_until = None
    db.commit()
    token = secrets.token_urlsafe(32)
    session = AuthSession(user_id=user.id, session_token=token, expires_at=dt.datetime.utcnow() + dt.timedelta(minutes=30))
    db.add(session)
    db.commit()

    resp = RedirectResponse(url="/rankings/desc", status_code=302)
    resp.set_cookie(settings.session_cookie_name, token, httponly=True, samesite="lax")
    return resp


@app.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        db.query(AuthSession).filter(AuthSession.session_token == token).delete()
        db.commit()
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(settings.session_cookie_name)
    return resp


def _require_admin(request: Request, db: Session) -> User | None:
    user = _current_user(request, db)
    if not user:
        return None
    if user.is_superadmin:
        return user
    if _has_permission(db, user, "page:admin:users"):
        return user
    return None


@app.get("/admin/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db), message: str | None = None):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=302)
    users = db.query(User).order_by(User.id.asc()).all()
    return templates.TemplateResponse("users.html", {"request": request, "users": users, "message": message})


@app.post("/admin/users/create")
def users_create(request: Request, username: str = Form(...), password: str = Form(...), is_superadmin: str | None = Form(None), db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=302)
    if db.query(User).filter(User.username == username).first():
        return RedirectResponse(url="/admin/users?message=用户名已存在", status_code=302)
    db.add(User(username=username, password_hash=hash_password(password), is_superadmin=bool(is_superadmin), is_active=True))
    db.commit()
    return RedirectResponse(url="/admin/users?message=用户创建成功", status_code=302)


@app.post("/admin/users/{user_id}/toggle")
def users_toggle(request: Request, user_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=302)
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.is_active = not user.is_active
        db.commit()
    return RedirectResponse(url="/admin/users?message=用户状态已更新", status_code=302)


@app.post("/admin/users/{user_id}/reset-password")
def users_reset_password(request: Request, user_id: int, new_password: str = Form(...), db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=302)
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.password_hash = hash_password(new_password)
        db.commit()
    return RedirectResponse(url="/admin/users?message=密码已重置", status_code=302)


@app.get("/admin/roles", response_class=HTMLResponse)
def roles_page(request: Request, db: Session = Depends(get_db), message: str | None = None):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=302)
    roles = db.query(Role).order_by(Role.id.asc()).all()
    perms = db.query(Permission).order_by(Permission.id.asc()).all()
    mappings = {(rp.role_id, rp.permission_id) for rp in db.query(RolePermission).all()}
    return templates.TemplateResponse("roles.html", {"request": request, "roles": roles, "perms": perms, "mappings": mappings, "message": message})

@app.post("/admin/roles/create")
def role_create(request: Request, role_code: str = Form(...), role_name: str = Form(...), db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=302)
    if not db.query(Role).filter(Role.role_code == role_code).first():
        db.add(Role(role_code=role_code, role_name=role_name))
        db.commit()
    return RedirectResponse(url="/admin/roles?message=角色已创建", status_code=302)

@app.post("/admin/roles/{role_id}/toggle-perm")
def role_toggle_perm(request: Request, role_id: int, permission_id: int = Form(...), db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=302)
    rp = db.query(RolePermission).filter(RolePermission.role_id == role_id, RolePermission.permission_id == permission_id).first()
    if rp:
        db.delete(rp)
    else:
        db.add(RolePermission(role_id=role_id, permission_id=permission_id))
    db.commit()
    return RedirectResponse(url="/admin/roles?message=权限已更新", status_code=302)


@app.post("/account/change-password")
def change_password(request: Request, old_password: str = Form(...), new_password: str = Form(...), db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not verify_password(old_password, user.password_hash):
        return RedirectResponse(url="/admin/users?message=旧密码错误", status_code=302)
    user.password_hash = hash_password(new_password)
    db.commit()
    return RedirectResponse(url="/admin/users?message=密码修改成功", status_code=302)


@app.get("/")
def home():
    return RedirectResponse(url="/rankings/desc")


@app.get("/crawl", response_class=HTMLResponse)
def crawl_page(request: Request, db: Session = Depends(get_db)):
    if not _current_user(request, db):
        return RedirectResponse(url="/login", status_code=302)
    if not _has_permission(db, _current_user(request, db), "page:crawl"):
        return RedirectResponse(url="/rankings/desc", status_code=302)
    return templates.TemplateResponse("crawl.html", {"request": request, "message": None})


@app.post("/crawl", response_class=HTMLResponse)
def crawl_submit(request: Request, batch_name: str = Form(...), direction: str = Form(...), db: Session = Depends(get_db)):
    if not _current_user(request, db):
        return RedirectResponse(url="/login", status_code=302)
    user = _current_user(request, db)
    if not _has_permission(db, user, "action:crawl:trigger"):
        return RedirectResponse(url="/rankings/desc", status_code=302)
    exists = db.query(CrawlBatch).filter(CrawlBatch.batch_name == batch_name, CrawlBatch.direction == direction).first()
    if exists:
        return templates.TemplateResponse("crawl.html", {"request": request, "message": "该批次该方向数据已采集"})
    batch = CrawlBatch(
        batch_name=batch_name,
        direction=direction,
        status="success",
        source_start_date=dt.date(dt.date.today().year, 1, 1),
        source_end_date=dt.date.today(),
        message="手工触发采集（参数固定：all、top100、持仓前10）",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    batch.status = "running"
    db.commit()
    try:
        run_crawl(db, batch, top_n=100)
    except Exception as exc:
        batch.status = "failed"
        batch.message = f"采集失败: {exc}"
        db.commit()
        return templates.TemplateResponse("crawl.html", {"request": request, "message": batch.message})
    return templates.TemplateResponse("crawl.html", {"request": request, "message": "采集完成"})


@app.get("/rankings/{direction}", response_class=HTMLResponse)
def ranking_page(direction: str, request: Request, batch_name: str | None = None, page_size: int = 10, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    perm = "page:rank:desc" if direction == "desc" else "page:rank:asc"
    if not _has_permission(db, user, perm):
        return RedirectResponse(url="/crawl", status_code=302)

    page_size = page_size if page_size in {10, 20, 50, 100} else 10
    batches = db.query(CrawlBatch).filter(CrawlBatch.direction == direction).order_by(CrawlBatch.created_at.desc()).all()
    current_batch = next((b for b in batches if b.batch_name == batch_name), None) if batch_name else None
    if not current_batch and batches:
        current_batch = batches[0]

    previous_batch = None
    if current_batch:
        previous_batch = (
            db.query(CrawlBatch)
            .filter(CrawlBatch.direction == direction, CrawlBatch.created_at < current_batch.created_at)
            .order_by(CrawlBatch.created_at.desc())
            .first()
        )

    rank_rows = []
    holdings_summary = []
    compare_summary = []
    if current_batch:
        rank_rows = (
            db.query(FundRankItem)
            .filter(FundRankItem.batch_id == current_batch.id)
            .order_by(FundRankItem.rank_no.asc())
            .limit(page_size)
            .all()
        )
        fund_codes = [r.fund_code for r in rank_rows]
        holdings_summary = _summary_for_current_page(db, current_batch.id, fund_codes)
        if previous_batch:
            compare_summary = (
                db.query(
                    FundHoldingItem.stock_code,
                    FundHoldingItem.stock_name,
                    func.sum(FundHoldingItem.market_value_10k).label("market_value_total"),
                    func.sum(FundHoldingItem.previous_market_value_10k).label("previous_market_value_total"),
                    func.sum(FundHoldingItem.shares_10k).label("shares_total"),
                    func.sum(FundHoldingItem.previous_shares_10k).label("previous_shares_total"),
                )
                .filter(FundHoldingItem.batch_id == current_batch.id, FundHoldingItem.fund_code.in_(fund_codes))
                .group_by(FundHoldingItem.stock_code, FundHoldingItem.stock_name)
                .order_by(func.sum(FundHoldingItem.market_value_10k).desc())
                .all()
            )

    return templates.TemplateResponse(
        "rankings.html",
        {
            "request": request,
            "direction": direction,
            "batches": batches,
            "current_batch": current_batch,
            "rank_rows": rank_rows,
            "holdings_summary": holdings_summary,
            "compare_summary": compare_summary,
            "previous_batch": previous_batch,
            "page_size": page_size,
            "page_size_options": [10, 20, 50, 100],
        },
    )
