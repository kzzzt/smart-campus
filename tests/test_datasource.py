"""数据源接入测试：CSV 读取规整为与 simulator 兼容的记录结构。"""
import os
import tempfile

from src.energy.datasource import read_csv


def _write_sample():
    fd, path = tempfile.mkstemp(
        suffix=".csv",
        dir=os.path.dirname(os.path.abspath(__file__)),  # 用工作区内可写目录，避开沙箱临时区
    )
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("ts,power_w\n2024-01-01 08:00:00,1200\n2024-01-01 09:00:00,500\n")
    return path


def test_read_csv_basic():
    path = _write_sample()
    try:
        recs = read_csv(path, room="1号宿舍楼-101", hours=2)
        assert len(recs) == 2
        assert recs[0]["power_w"] == 1200.0
        assert recs[0]["room"] == "1号宿舍楼-101"
        assert recs[0]["handler"] == "1号楼生活辅导员"
        assert recs[0]["building"] == "1号宿舍楼"
    finally:
        os.unlink(path)


def test_read_csv_missing_file_raises():
    import pytest
    with pytest.raises(FileNotFoundError):
        read_csv("no_such_file.csv")
