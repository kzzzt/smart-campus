"""
遗传算法求解排课调度。

把"课程 -> 时段 -> 教室"的映射编码为一条染色体，用遗传算法（选择/交叉/变异）
在满足约束的前提下搜索一个尽量无冲突、且教室分配合理的排课方案。

编码方式：
    一个基因 = (course_id, time_slot, room_id)
    一条染色体 = 每门课按其学时 hours_per_week 展开为多个基因，代表该课本周的多个上课时段。

适应度函数评估：
    - 硬约束：同一课程同一时段重复、同一教师冲突、教室同一时段冲突、
      教室容量不足、机房需求不满足 -> 大额罚分
    - 软约束：教室类型匹配、容量匹配 -> 奖励
"""

import random
from typing import Optional

from .constraints import Course, Room, TIME_SLOTS


class GeneticScheduler:
    """基于遗传算法的排课求解器。"""

    def __init__(
        self,
        courses: list[Course],
        rooms: list[Room],
        pop_size: int = 40,
        generations: int = 60,
        seed: int = 7,
    ):
        self.courses = courses
        self.rooms = rooms
        self.pop_size = pop_size
        self.generations = generations
        random.seed(seed)

    # ---------------- 适应度 ----------------
    def fitness(self, chromosome: list[tuple]) -> float:
        """
        chromosome: 每门课按其 hours_per_week 展开为多个 (course_id, time_slot, room_id) 基因。
        越大越好（罚分越少）。
        """
        score = 0.0
        slot_room: dict = {}      # (slot, room) -> course_id
        teacher_slot: dict = {}   # (slot, teacher) -> course_id
        course_slots: dict = {}   # course_id -> list[slot]
        room_by_id = {r.id: r for r in self.rooms}
        course_by_id = {c.id: c for c in self.courses}

        for cid, slot, rid in chromosome:
            course = course_by_id[cid]
            room = room_by_id[rid]

            slots = course_slots.setdefault(cid, [])
            if slot in slots:                     # 同一课程同一时段重复(一场课不能同时开两场)
                score -= 100
            slots.append(slot)
            if (slot, rid) in slot_room:          # 同一教室同一时段冲突
                score -= 100
                continue
            slot_room[(slot, rid)] = cid
            if (slot, course.teacher) in teacher_slot:    # 同一教师冲突
                score -= 100
                continue
            teacher_slot[(slot, course.teacher)] = cid
            if room.capacity < course.class_size:         # 教室容量不足
                score -= 80
            if course.requires_computer and not room.has_computer:  # 需电脑却非机房
                score -= 60
            for other in course.conflicts_with:           # 冲突课程列表
                if slot in course_slots.get(other, []):
                    score -= 100

            # 软约束奖励
            if course.requires_computer and room.has_computer:
                score += 30
            if room.capacity >= course.class_size and room.capacity <= course.class_size * 1.5:
                score += 10  # 教室容量匹配度好

            score += 10  # 每成功安排一个课时的基础分

        score += 30 * len(course_slots)  # 每门课都能排上的整体奖励
        return score

    def count_conflicts(self, chromosome: list[tuple]) -> int:
        """
        统计硬约束冲突数（教师冲突 / 教室同一时段冲突 / 容量不足 / 机房需求不满足），
        用于向用户直观报告求解质量（0 = 完全无冲突）。
        """
        conflicts = 0
        room_slot: set = set()
        teacher_slot: dict = {}
        course_slots: dict = {}
        room_by_id = {r.id: r for r in self.rooms}
        course_by_id = {c.id: c for c in self.courses}
        for cid, slot, rid in chromosome:
            course = course_by_id[cid]
            room = room_by_id[rid]
            if slot in course_slots.setdefault(cid, []):
                conflicts += 1
            course_slots[cid].append(slot)
            if (slot, rid) in room_slot:
                conflicts += 1
            else:
                room_slot.add((slot, rid))
            if (slot, course.teacher) in teacher_slot:
                conflicts += 1
            else:
                teacher_slot[(slot, course.teacher)] = cid
            if room.capacity < course.class_size:
                conflicts += 1
            if course.requires_computer and not room.has_computer:
                conflicts += 1
        return conflicts

    # ---------------- 个体生成 ----------------
    def _random_chromosome(self) -> list[tuple]:
        """每门课按 hours_per_week 生成多个基因；同课优先取不同的时段。"""
        chromo = []
        for c in self.courses:
            try:
                slots = random.sample(TIME_SLOTS, c.hours_per_week)
            except ValueError:  # 学时数超过时段总数：允许重复，由适应度惩罚
                slots = [random.choice(TIME_SLOTS) for _ in range(c.hours_per_week)]
            chromo.extend((c.id, s, random.choice(self.rooms).id) for s in slots)
        return chromo

    def _crossover(self, a, b) -> tuple:
        if len(a) <= 1:  # 单基因无需交叉，避免 randint(1, 0) 崩溃
            return a[:], b[:]
        cut = random.randint(1, len(a) - 1)
        return a[:cut] + b[cut:], b[:cut] + a[cut:]

    def _mutate(self, chromo, rate: float = 0.1):
        for i in range(len(chromo)):
            if random.random() < rate:
                cid, _slot, _rid = chromo[i]
                # 变异时尽量避开该课程已占用的时段，降低"同课同时段重复"
                other_slots = {s for j, (cc, s, _) in enumerate(chromo) if j != i and cc == cid}
                cands = [s for s in TIME_SLOTS if s not in other_slots] or list(TIME_SLOTS)
                chromo[i] = (cid, random.choice(cands), random.choice(self.rooms).id)
        return chromo

    # ---------------- 主流程 ----------------
    def solve(self, verbose: bool = False) -> dict:
        pop = [self._random_chromosome() for _ in range(self.pop_size)]

        for gen in range(self.generations):
            scored = sorted(
                ((self.fitness(ind), ind) for ind in pop),
                key=lambda x: x[0], reverse=True,
            )
            # 保留精英，其余由选择/交叉/变异产生；至少保留 1 个，避免小种群时 elites 为空
            elite_count = max(1, self.pop_size // 5)
            elites = [ind for _, ind in scored[:elite_count]]
            new_pop = list(elites)
            while len(new_pop) < self.pop_size:
                p1 = random.choice(elites if random.random() < 0.7 else pop)
                p2 = random.choice(pop)
                c1, c2 = self._crossover(p1, p2)
                new_pop.append(self._mutate(c1))
                if len(new_pop) < self.pop_size:
                    new_pop.append(self._mutate(c2))
            pop = new_pop
            if verbose:
                print(f"gen {gen}: best fitness = {scored[0][0]}")

        best = max(pop, key=self.fitness)
        return {
            "schedule": self._build_schedule(best),
            "fitness": self.fitness(best),
            "conflicts": self.count_conflicts(best),
        }

    def _build_schedule(self, chromo) -> list[dict]:
        course_by_id = {c.id: c for c in self.courses}
        room_by_id = {r.id: r for r in self.rooms}
        rows = []
        for cid, slot, rid in chromo:
            c = course_by_id[cid]
            r = room_by_id[rid]
            rows.append(
                {
                    "course": c.name,
                    "teacher": c.teacher,
                    "time_slot": slot,
                    "room": r.name,
                    "room_type": r.room_type,
                }
            )
        return rows
