"""
教室智能分配模块。

根据课程类型 / 需求（如是否需要电脑）为课程推荐最合适的教室，并结合
教室占用情况避免冲突。供遗传算法初始化时生成合理候选，也可单独使用。

核心逻辑：
    - 需要电脑的课程 -> 优先机房（has_computer 教室）
    - 实验课 -> 优先实验室
    - 大课 -> 优先大容量教室
"""

from .constraints import Course, Room


def recommend_rooms(course: Course, rooms: list[Room], top_k: int = 3) -> list[Room]:
    """
    为单个课程推荐最合适的 top_k 个教室，按匹配度排序。
    """
    def score(r: Room) -> float:
        s = 0.0
        if course.requires_computer and r.has_computer:
            s += 5
        if course.name and ("实验" in course.name) and r.room_type == "lab":
            s += 5
        # 容量匹配：过小扣分，过大浪费
        if r.capacity >= course.class_size:
            s += 3
            if r.capacity <= course.class_size * 1.5:
                s += 2
            else:
                s -= 1
        else:
            s -= 5
        return s

    ranked = sorted(rooms, key=score, reverse=True)
    return ranked[:top_k]


def assign_classrooms(courses: list[Course], rooms: list[Room]) -> list[dict]:
    """
    为所有课程做一次贪心分配（作为遗传算法之外的一种直观兜底方案，
    也用于演示"根据课程类型智能分配最合适的教室"）。

    返回分配结果列表。
    """
    occupied: set[tuple] = set()   # (slot, room) -> 已占用
    result = []
    TIME_SLOTS = ["mon-a", "tue-b", "wed-c", "thu-d", "fri-a"]

    for course in courses:
        # 输出时段必须与"实际占用判断"使用同一个 slot，避免占位与展示不一致
        chosen_room, chosen_slot = None, None
        for slot in TIME_SLOTS:
            for r in recommend_rooms(course, rooms, top_k=len(rooms)):
                if (slot, r.id) not in occupied:
                    chosen_room, chosen_slot = r, slot
                    occupied.add((slot, r.id))
                    break
            if chosen_room:
                break
        if chosen_room is None:  # 所有时段教室都被占（理论兜底）
            chosen_room, chosen_slot = rooms[0], TIME_SLOTS[len(result) % len(TIME_SLOTS)]
        if chosen_room.has_computer:
            note = "机房分配"
        elif chosen_room.room_type == "lab":
            note = "实验室分配"
        else:
            note = "普通教室"
        result.append(
            {
                "course": course.name,
                "teacher": course.teacher,
                "room": chosen_room.name,
                "room_type": chosen_room.room_type,
                "capacity": chosen_room.capacity,
                "time_slot": chosen_slot,
                "note": note,
            }
        )
    return result
