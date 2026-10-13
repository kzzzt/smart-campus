"""
Gunicorn 生产配置 —— 匹配 4 vCPU / 16 GB 云主机（c5.xlarge.4）。

启动方式（deploy.sh 中使用）：
    gunicorn -c deploy/gunicorn.conf.py 'webapp.app:app'

要点：
  - worker 数 = 2×CPU + 1 ≈ 9，但本项目为轻量同步型，4 worker 已足够并发，留足余量；
  - worker_class 默认 sync（简单可靠，本应用无长连接/SSE 需求）；
  - graceful 重启，避免服务中断。
"""

import multiprocessing
import os

# 绑定 Gunicorn 到本机回环，由 Nginx 反向代理对外
bind = "127.0.0.1:8000"

# worker 数：按 CPU 核数自适应，最多 4 个（轻量应用足够）
workers = min(4, max(1, multiprocessing.cpu_count()))
# 每 worker 线程数（同步型进程内多线程处理轻量 IO）
threads = 2

# 超时与连接
timeout = 30               # worker 沉默超时（秒），GA 求解毫秒级足够
keepalive = 5
graceful_timeout = 20

# 并发与队列
worker_class = "sync"      # 同步型，最稳定
max_requests = 1000        # 每个 worker 处理 1000 请求后重启，释放潜在内存泄漏
max_requests_jitter = 100
preload_app = False

# 日志
accesslog = "-"            # 输出到 stdout，随 systemd journal 记录
errorlog = "-"
loglevel = "info"
capture_output = True

# 进程
daemon = False
pidfile = None

# 绑定环境变量（从 deploy/.env 或系统环境读取 SECRET_KEY 等）
# SECRET_KEY / LLM_API_KEY 由 systemd EnvironmentFile 注入

def post_fork(server, worker):
    """每个 worker 启动后初始化数据库（幂等，重复执行无害）。"""
    try:
        from webapp import db
        db.init_db()
    except Exception:
        pass
