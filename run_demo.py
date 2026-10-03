"""
一键运行演示脚本：串联三大子系统，输出可视化演示结果。

    python run_demo.py

子系统一：AI 教务智能客服（自动应答 + 工单流转）
子系统二：校园能耗与安全智能预警（IoT + 违规检测 + 用电高峰预测）
子系统三：智能排课与教室调度（遗传算法 + 大模型约束理解 + 教室智能分配）
"""

import sys
from datetime import datetime

# 确保可导入 src 包
sys.path.insert(0, ".")

# Windows 控制台可能为 GBK 编码，无法输出部分 Unicode 字符（如 ✅）
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.ai_service.bot import CampusAIBot
from src.energy.simulator import PowerySimulator
from src.energy.detector import detect, rule_detect
from src.energy.forecast import forecast_peak
from src.scheduler.constraints import Course, Room
from src.scheduler.genetic import GeneticScheduler
from src.scheduler.classroom import assign_classrooms


def demo_ai_service() -> dict:
    """子系统一演示：客服自动应答 + 复杂问题工单流转。"""
    print("=" * 60)
    print("【子系统一】AI 教务智能客服（7×24h）")
    print("=" * 60)

    bot = CampusAIBot()

    cases = [
        ("20230001", "请问奖学金评定需要什么条件？"),
        ("20230002", "我想请三天病假，需要哪些材料？"),
        ("20230003", "请问转专业的手续怎么办理？"),
        ("20230004", "我的寝室插座坏了，能不能帮我看一下学校财产报修联系谁？"),
    ]

    results = []
    for sid, q in cases:
        r = bot.handle(q, student_id=sid)
        results.append(r)
        print(f"\n[学生 {sid}] {q}")
        print(f"  意图: {r['intent']}  置信度: {r['confidence']}")
        if r["needs_human"]:
            print(f"  自动生成工单 -> 流转给: {r['ticket']['handler']} (状态: {r['ticket']['status']})")
            print(f"  回复: {r['answer']}")
        else:
            print(f"  自动回复: {r['answer']}")
    print(f"\n工单总数: {len(bot.tickets.tickets)} 张")
    return {"results": results, "tickets": bot.tickets.tickets}


def demo_energy() -> dict:
    """子系统二演示：能耗数据 + 违规检测 + 用电高峰预测。"""
    print("\n" + "=" * 60)
    print("【子系统二】校园能耗与安全智能预警系统")
    print("=" * 60)

    sim = PowerySimulator(room_count=8, seed=2024)
    day = datetime(2024, 5, 22)
    records = sim.generate_day(day)

    # 违规电器检测（规则通道）
    alarms = rule_detect(records)
    print(f"\n已模拟 {8} 个房间的一天用电数据，规则通道检测出 {len(alarms)} 个疑似违规电器房间:")
    for a in alarms:
        print(f"  - {a['room']} 功率 {a['power_w']}W: {a['reason']}")

    # 综合检测（含视觉接口）
    full = detect(records, use_vision=False)
    print(f"\n综合检测结论: {full['summary']}")

    # 用电高峰预测
    # 输入为累计的历史负荷（简化：取前几个房间数据聚合）
    history = records
    pred = forecast_peak(history, forecast_hours=24, peak_threshold_w=5000)
    print(f"\n用电高峰预测 (未来 24h): 检测到 {pred['peak_count']} 个高峰")
    for p in pred["peak_slots"][:3]:
        print(f"  - {p['ts'].strftime('%m-%d %H:00')} 功率 {p['power_w']}W")
    print(f"  建议: {pred['suggestion']}")
    return {"alarms": alarms, "prediction": pred}


def demo_scheduler() -> dict:
    """子系统三演示：遗传算法排课 + 教室智能分配。"""
    print("\n" + "=" * 60)
    print("【子系统三】智能排课与教室调度系统")
    print("=" * 60)

    # 构造示例课程（含"需电脑的课"、实验课、大课等）
    courses = [
        Course("C1", "数据结构", "张老师", 60, 4, requires_computer=True),
        Course("C2", "大学英语", "李老师", 80, 4),
        Course("C3", "高等数学", "王老师", 90, 4),
        Course("C4", "计算机实验", "赵老师", 40, 2, requires_computer=True),
        Course("C5", "物理实验", "孙老师", 45, 2),
        Course("C6", "线性代数", "周老师", 70, 4),
    ]
    rooms = [
        Room("R1", "机房A", 60, has_computer=True, room_type="computer"),
        Room("R2", "机房B", 50, has_computer=True, room_type="computer"),
        Room("R3", "实验室1", 45, has_computer=False, room_type="lab"),
        Room("R4", "大教室1", 100, has_computer=False, room_type="normal"),
        Room("R5", "大教室2", 120, has_computer=False, room_type="normal"),
        Room("R6", "普通教室1", 60, has_computer=False, room_type="normal"),
    ]

    print("\n--- 教室智能分配（根据课程类型推荐最合适教室）---")
    assignment = assign_classrooms(courses, rooms)
    for a in assignment:
        print(f"  {a['course']}({a['teacher']}) -> {a['room']} [{a['room_type']}] {a['note']}")

    # 遗传算法求解
    print("\n--- 遗传算法求解排课（求解无冲突方案）---")
    sched = GeneticScheduler(courses, rooms, pop_size=30, generations=40)
    result = sched.solve(verbose=False)
    print(f"  最终适应度: {result['fitness']}")
    print("  排课结果：")
    for row in result["schedule"]:
        print(
            f"    {row['time_slot']:10s} {row['course']}({row['teacher']}) "
            f"-> {row['room']} [{row['room_type']}]"
        )
    return {"assignment": assignment, "schedule": result}


def main():
    print("智慧校园管理与安全平台 —— 三系统串联演示")
    print(f"运行时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    demo_ai_service()
    demo_energy()
    demo_scheduler()
    print("\n" + "=" * 60)
    print("演示完成 ✅")


if __name__ == "__main__":
    main()
