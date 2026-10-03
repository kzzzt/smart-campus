"""
排课约束定义模块。

把排课需求（包括由大模型"约束条件理解"解析出的自然语言需求）统一编码为
结构化约束，供遗传算法求解。例如把"这周多开两节实验课、不能和XX冲突、"
"需要电脑的课排机房"等翻译成约束对象。
"""

from dataclasses import dataclass, field


@dataclass
class Course:
    """一门课程。"""
    id: str
    name: str
    teacher: str
    class_size: int
    hours_per_week: int       # 每周需要排几个时段
    requires_computer: bool = False   # 是否需要机房（电脑）
    preferred_time: str = ""          # 可选：偏好时段（如"上午"）
    conflicts_with: list = field(default_factory=list)  # 不允许同时段的课程/教师


@dataclass
class Room:
    """一间教室。"""
    id: str
    name: str
    capacity: int
    has_computer: bool = False   # 是否为机房
    room_type: str = "normal"    # normal / lab / computer


@dataclass
class Constraint:
    """一个排课约束（由 LLM 解析自然语言后生成，或人工配置）。"""
    kind: str        # hard / soft
    description: str


# 时段定义：每周一~周五，每天分为 N 个时段（示例用 4 个时段）
TIME_SLOTS = ["mon-a", "mon-b", "mon-c", "mon-d",
              "tue-a", "tue-b", "tue-c", "tue-d",
              "wed-a", "wed-b", "wed-c", "wed-d",
              "thu-a", "thu-b", "thu-c", "thu-d",
              "fri-a", "fri-b", "fri-c", "fri-d"]
