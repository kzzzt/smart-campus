"""
Web 应用启动脚本。

    python run_web.py

启动后会初始化数据库并运行 Flask 服务器，默认地址 http://127.0.0.1:5000
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from webapp import db
from webapp.app import app


if __name__ == "__main__":
    db.init_db()
    print("=" * 56)
    print("智慧校园管理与安全平台 - Web 版")
    print("请用浏览器打开: http://127.0.0.1:5000")
    print("按 Ctrl+C 停止服务")
    print("=" * 56)
    app.run(host="127.0.0.1", port=5000, debug=False)  # 提交/演示用关闭 debug，避免调试器暴露与自动重载重置全局状态
