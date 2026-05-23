from sqlalchemy import Boolean, Column, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_superadmin = Column(Boolean, default=False, nullable=False)
    failed_login_count = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    role_code = Column(String(64), unique=True, nullable=False)
    role_name = Column(String(128), nullable=False)


class Permission(Base):
    __tablename__ = "permissions"
    id = Column(Integer, primary_key=True)
    perm_code = Column(String(128), unique=True, nullable=False)
    perm_name = Column(String(128), nullable=False)
    perm_type = Column(Enum("page", "action", name="perm_type"), nullable=False)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)
    permission_id = Column(Integer, ForeignKey("permissions.id"), primary_key=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_token = Column(String(128), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class CaptchaChallenge(Base):
    __tablename__ = "captcha_challenges"
    id = Column(Integer, primary_key=True)
    challenge_key = Column(String(64), unique=True, nullable=False)
    answer = Column(String(16), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class CrawlBatch(Base):
    __tablename__ = "crawl_batches"
    __table_args__ = (UniqueConstraint("batch_name", "direction", name="uk_batch_name_direction"),)
    id = Column(Integer, primary_key=True)
    batch_name = Column(String(32), nullable=False)
    direction = Column(Enum("asc", "desc", name="direction_type"), nullable=False)
    status = Column(Enum("running", "success", "failed", name="batch_status"), default="running", nullable=False)
    source_start_date = Column(Date, nullable=False)
    source_end_date = Column(Date, nullable=False)
    message = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class FundRankItem(Base):
    __tablename__ = "fund_rank_items"
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("crawl_batches.id"), nullable=False)
    rank_no = Column(Integer, nullable=False)
    fund_code = Column(String(16), nullable=False)
    fund_name = Column(String(128), nullable=False)
    fund_name_spell = Column(String(128), nullable=True)
    nav_date = Column(Date, nullable=True)
    unit_nav = Column(Numeric(18, 6), nullable=True)
    ytd_return = Column(Numeric(10, 4), nullable=True)


class FundHoldingItem(Base):
    __tablename__ = "fund_holding_items"
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("crawl_batches.id"), nullable=False)
    fund_code = Column(String(16), nullable=False)
    fund_name = Column(String(128), nullable=False)
    holding_rank_no = Column(Integer, nullable=False)
    stock_code = Column(String(16), nullable=False)
    stock_name = Column(String(128), nullable=False)
    shares_10k = Column(Numeric(18, 4), nullable=True)
    market_value_10k = Column(Numeric(18, 4), nullable=True)
    previous_shares_10k = Column(Numeric(18, 4), nullable=True)
    previous_market_value_10k = Column(Numeric(18, 4), nullable=True)
    change_status = Column(String(32), nullable=False, default="无上期对比")
