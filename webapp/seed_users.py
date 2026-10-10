"""
RBAC 默认账户种子数据。

三种角色：
    - student   学生：仅 AI 客服可交互，能耗/排课只读
    - counselor 辅导员：AI 客服 + 排课，功能不受限（只见自己的工单/课程）
    - admin     管理人员：全部接口，最高权限，可维护修改

密码以 SHA-256 哈希存储（演示级；生产请换 bcrypt/argon2 + salt）。
"""
import hashlib


def _hash(pwd: str) -> str:
    return hashlib.sha256(pwd.encode("utf-8")).hexdigest()


def _u(username, password, role, display_name, student_id=None, handler=None):
    return dict(
        username=username,
        password_hash=_hash(password),
        role=role,
        display_name=display_name,
        student_id=student_id,
        handler=handler,
    )


SEED_USERS = [
    # ---- 学生（student_id = 学号，登录后可查自己工单） ----
    _u("student", "stu123", "student", "学生小李", student_id="20230001"),
    _u("s20230001", "stu123", "student", "学生小李", student_id="20230001"),
    # ---- 辅导员（handler = 工单中 INTENT_TO_HANDLER 的职责名） ----
    _u("counselor", "cou123", "counselor", "综合事务辅导员", handler="综合事务辅导员"),
    _u("c_leave", "cou123", "counselor", "学籍与请假业务辅导员", handler="学籍与请假业务辅导员"),
    _u("c_award", "cou123", "counselor", "奖助学金评审辅导员", handler="奖助学金评审辅导员"),
    _u("c_status", "cou123", "counselor", "学籍异动业务辅导员", handler="学籍异动业务辅导员"),
    # ---- 楼栋生活辅导员（handler = 模拟器宿舍负责人，收本楼能耗告警） ----
    _u("f1", "cou123", "counselor", "1号楼生活辅导员", handler="1号楼生活辅导员"),
    _u("f2", "cou123", "counselor", "2号楼生活辅导员", handler="2号楼生活辅导员"),
    # ---- 教师视角辅导员（handler = 排课中的授课教师名，实现"只见自己课程"） ----
    _u("t_zhang", "cou123", "counselor", "张老师", handler="张老师"),
    _u("t_li", "cou123", "counselor", "李老师", handler="李老师"),
    # ---- 管理人员（最高权限，可维护修改） ----
    _u("admin", "SmartCampus@2026", "admin", "系统管理员"),
    _u("manager", "SmartCampus@2026", "admin", "系统管理员"),
]
