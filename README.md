# 天天基金基金持仓分析系统（FastAPI）

基于 FastAPI + Jinja2 + MySQL 8.x 的基金持仓分析系统。

## 核心能力
- 登录认证：账号密码 + 算术验证码 + Cookie Session
- 默认管理员通过一次性初始化脚本创建（无注册入口）
- 手工采集入口：独立页面 `/crawl`，触发参数固定（all、top100、持仓前10）
- 采集批次（`xxxx年x季度`）与方向（`asc`/`desc`）唯一，重复触发提示“已采集”
- 正序、倒序独立页面展示
- 页面默认10行，支持10/20/50/100
- 在基金排行前展示“当前分页基金”的持仓股汇总（按持仓市值合计）
- 支持同方向上一批次对比（按创建时间倒序选择上一期）

## 启动
```bash
pip install -r requirements.txt
python scripts_init_admin.py
uvicorn app.main:app --reload
```

打开：
- 登录页：`/login`
- 手工采集：`/crawl`
- 倒序页：`/rankings/desc`
- 正序页：`/rankings/asc`

- 用户管理：`/admin/users`（创建用户、启停用户、重置密码）
- 本人改密：在用户管理页提交旧密码/新密码

- 角色管理：`/admin/roles`（创建角色、授予/移除页面权限）
- 登录失败3次锁定30分钟；会话有效期30分钟；验证码一次性使用
- 数据库使用 Alembic 迁移，需手动创建库后执行迁移
