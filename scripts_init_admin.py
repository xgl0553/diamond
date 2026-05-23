from app.database import SessionLocal
from app.models import Permission, Role, RolePermission, User, UserRole
from app.security import hash_password


def main() -> None:
    username = "admin"
    password = "Admin@123456"
    db = SessionLocal()
    try:
        exists = db.query(User).filter(User.username == username).first()
        if exists:
            print("admin already exists")
            return
        user = User(username=username, password_hash=hash_password(password), is_superadmin=True, is_active=True)
        db.add(user)
        perms = [
            ("page:rank:desc", "倒序页面"),
            ("page:rank:asc", "正序页面"),
            ("page:crawl", "采集页面"),
            ("action:crawl:trigger", "触发采集"),
            ("page:admin:users", "用户管理页面"),
        ]
        for code, name in perms:
            if not db.query(Permission).filter(Permission.perm_code == code).first():
                db.add(Permission(perm_code=code, perm_name=name, perm_type="page" if code.startswith("page") else "action"))
        db.flush()
        role = db.query(Role).filter(Role.role_code == "admin").first()
        if not role:
            role = Role(role_code="admin", role_name="管理员")
            db.add(role)
            db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        for perm in db.query(Permission).all():
            if not db.query(RolePermission).filter(RolePermission.role_id == role.id, RolePermission.permission_id == perm.id).first():
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.commit()
        print("init admin success: admin / Admin@123456")
    finally:
        db.close()


if __name__ == "__main__":
    main()
