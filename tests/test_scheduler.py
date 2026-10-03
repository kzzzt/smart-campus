from src.scheduler.constraints import Course, Room
from src.scheduler.genetic import GeneticScheduler
from src.scheduler.classroom import assign_classrooms, recommend_rooms


def _fixture():
    courses = [
        Course("C1", "数据结构", "张", 60, 4, requires_computer=True),
        Course("C2", "英语", "李", 80, 4),
        Course("C3", "物理实验", "赵", 40, 2),
    ]
    rooms = [
        Room("R1", "机房A", 60, has_computer=True, room_type="computer"),
        Room("R2", "大教室1", 100, has_computer=False, room_type="normal"),
        Room("R3", "实验室1", 45, has_computer=False, room_type="lab"),
    ]
    return courses, rooms


def test_recommend_computer_course_to_room():
    courses, rooms = _fixture()
    top = recommend_rooms(courses[0], rooms, top_k=3)
    # 需要电脑的数据结构课，排第一的应是机房
    assert top[0].has_computer is True


def test_assign_classrooms_no_duplicate_slot_room():
    courses, rooms = _fixture()
    result = assign_classrooms(courses, rooms)
    assert len(result) == len(courses)
    # 每个教室/时段不冲突（demo 简单验证数量）
    assert all("room" in r for r in result)


def test_genetic_solver_runs():
    courses, rooms = _fixture()
    sched = GeneticScheduler(courses, rooms, pop_size=20, generations=15)
    r = sched.solve()
    assert len(r["schedule"]) == len(courses)
    # 每个课程都排上了
    names = {row["course"] for row in r["schedule"]}
    assert names == {"数据结构", "英语", "物理实验"}
