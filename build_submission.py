#!/usr/bin/env python3
"""
一键生成符合大赛规范命名的提交压缩包。

用法：
    python build_submission.py [输出文件名.zip]

打包 src/ webapp/ tests/ docs/ 及顶层运行文件，
自动排除 __pycache__ / *.pyc / .git / *.db / *.zip / .pytest_cache。
压缩包内以「团队名-队长-手机号-作品名」文件夹包裹，与大赛提交命名一致。
① 替换下面 PHONE 为 11 位真实手机号（务必核对）；
② 直接运行即生成最新压缩包，避免手工打包导致版本过期/自嵌套。
"""
import os
import re
import sys
import zipfile

REPO = os.path.dirname(os.path.abspath(__file__))

TEAM = "ai双子星"
CAPTAIN = "康智童"
PHONE = "139933736281"   # ⚠️ 以用户确认为准（12 位）
WORK = "智慧校园管理与安全平台"

# 打包清单：源码 + 顶层运行文件（不打包 zip 本身，避免自嵌套）
ENTRIES = ["src", "webapp", "tests", "docs",
           "README.md", "requirements.txt", "run_demo.py", "run_web.py"]

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".git", ".venv", "venv"}


def ok(name: str) -> bool:
    if name in EXCLUDE_DIRS:
        return False
    if name.endswith((".pyc", ".db", ".zip")):
        return False
    if name in (".secret_key", "campus.db"):
        return False
    return True


def main() -> None:
    if re.fullmatch(r"1\d{10,11}", PHONE) is None:
        print(f"[警告] 手机号数字位数异常（当前：{PHONE}），请核对 build_submission.py 顶部！")

    folder = f"{TEAM}-{CAPTAIN}-{PHONE}-{WORK}"
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, folder + ".zip")

    files: list[str] = []
    for ent in ENTRIES:
        p = os.path.join(REPO, ent)
        if os.path.isfile(p):
            files.append(p)
        elif os.path.isdir(p):
            for root, dirs, fs in os.walk(p):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for f in fs:
                    files.append(os.path.join(root, f))

    files = [f for f in files if ok(os.path.basename(f))]
    files.sort()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            rel = os.path.relpath(f, REPO)
            z.write(f, os.path.join(folder, rel))

    print(f"已生成: {out}  ({len(files)} 个文件)")
    print(f"校验: 应无 .git/__pycache__/*.db/*.zip 混入。")


if __name__ == "__main__":
    main()
