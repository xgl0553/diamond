"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2026-05-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

perm_type = sa.Enum("page", "action", name="perm_type")
direction_type = sa.Enum("asc", "desc", name="direction_type")
batch_status = sa.Enum("running", "success", "failed", name="batch_status")


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("username"),
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role_code", sa.String(length=64), nullable=False),
        sa.Column("role_name", sa.String(length=128), nullable=False),
        sa.UniqueConstraint("role_code"),
    )

    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("perm_code", sa.String(length=128), nullable=False),
        sa.Column("perm_name", sa.String(length=128), nullable=False),
        sa.Column("perm_type", perm_type, nullable=False),
        sa.UniqueConstraint("perm_code"),
    )

    op.create_table(
        "crawl_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_name", sa.String(length=32), nullable=False),
        sa.Column("direction", direction_type, nullable=False),
        sa.Column("status", batch_status, nullable=False, server_default="running"),
        sa.Column("source_start_date", sa.Date(), nullable=False),
        sa.Column("source_end_date", sa.Date(), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("batch_name", "direction", name="uk_batch_name_direction"),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), primary_key=True),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), primary_key=True),
        sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id"), primary_key=True),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_token", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_token"),
    )

    op.create_table(
        "captcha_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("challenge_key", sa.String(length=64), nullable=False),
        sa.Column("answer", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("challenge_key"),
    )

    op.create_table(
        "fund_rank_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("crawl_batches.id"), nullable=False),
        sa.Column("rank_no", sa.Integer(), nullable=False),
        sa.Column("fund_code", sa.String(length=16), nullable=False),
        sa.Column("fund_name", sa.String(length=128), nullable=False),
        sa.Column("fund_name_spell", sa.String(length=128), nullable=True),
        sa.Column("nav_date", sa.Date(), nullable=True),
        sa.Column("unit_nav", sa.Numeric(18, 6), nullable=True),
        sa.Column("ytd_return", sa.Numeric(10, 4), nullable=True),
    )

    op.create_table(
        "fund_holding_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("crawl_batches.id"), nullable=False),
        sa.Column("fund_code", sa.String(length=16), nullable=False),
        sa.Column("fund_name", sa.String(length=128), nullable=False),
        sa.Column("holding_rank_no", sa.Integer(), nullable=False),
        sa.Column("stock_code", sa.String(length=16), nullable=False),
        sa.Column("stock_name", sa.String(length=128), nullable=False),
        sa.Column("shares_10k", sa.Numeric(18, 4), nullable=True),
        sa.Column("market_value_10k", sa.Numeric(18, 4), nullable=True),
        sa.Column("previous_shares_10k", sa.Numeric(18, 4), nullable=True),
        sa.Column("previous_market_value_10k", sa.Numeric(18, 4), nullable=True),
        sa.Column("change_status", sa.String(length=32), nullable=False, server_default="无上期对比"),
    )


def downgrade():
    op.drop_table("fund_holding_items")
    op.drop_table("fund_rank_items")
    op.drop_table("captcha_challenges")
    op.drop_table("auth_sessions")
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("crawl_batches")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("users")
