# 智慧校园管理平台 · 云端部署说明
#
# 适用：Ubuntu / Debian（apt 系）、CentOS / RHEL / BC-Linux(麒麟) / openEuler（yum/dnf 系），x86_64 云主机
# 推荐配置：1核1G 即可跑通；实测 2 核 4G / 4 核 16GB 云主机运行无压力（部署脚本按 CPU 核数自适应 worker 数）
#
# ---------------------------------------------------------------------------
# 一、把代码放到云主机
# ---------------------------------------------------------------------------
# 方法 A（推荐）：在云主机上直接 clone 仓库
#     git clone https://github.com/kzzzt/smart-campus.git
#     cd smart-campus
#
# 方法 B：把本地代码打包 scp 上传
#     # 在本地（Windows PowerShell）：
#     scp -r smart-campus ubuntu@<公网IP>:/home/ubuntu/
#
# ---------------------------------------------------------------------------
# 二、一键部署
# ---------------------------------------------------------------------------
#     cd smart-campus
#     sudo bash deploy/deploy.sh
#
# 脚本会自动（自动检测 apt / yum / dnf）：
#   1) 安装 python3 / python3-venv / python3-pip / nginx / gcc 等系统依赖
#   2) 创建 .venv 虚拟环境并 pip install -r requirements.txt
#   3) 初始化 SQLite 数据库 webapp/campus.db（自动建表+种子演示账号）
#   4) 配置 Gunicorn（worker 数按 CPU 自适应，见 gunicorn.conf.py）+
#      systemd 服务（开机自启、崩溃 5 秒自动重启）
#   5) 配置 Nginx 反向代理（80 端口 -> 127.0.0.1:8000），兼容
#      sites-available / conf.d 两种 nginx 布局
#
# 部署完成后访问 http://<云主机公网IP>/  即可。
#
# ---------------------------------------------------------------------------
# 三、安全加固（强烈建议，尤其对外网开放时）
# ---------------------------------------------------------------------------
# 1) 修改默认口令：编辑 deploy/.env 设置 SECRET_KEY（必须！）
#        cp deploy/.env.example deploy/.env
#        nano deploy/.env   # 设置 SECRET_KEY 随机串
#        sudo systemctl restart smartcampus
#    生成随机密钥：openssl rand -hex 32
#
# 2) 更换管理员密码：编辑 webapp/seed_users.py 中 admin 的口令，
#    然后删除 webapp/campus.db 重建（或改 db.py 种子逻辑）。生产建议改为
#    bcrypt/argon2（当前为演示级 SHA-256）。
#
# 3) 启用 HTTPS（推荐 Let's Encrypt）：
#        sudo apt install -y certbot python3-certbot-nginx
#        sudo certbot --nginx -d 你的域名
#
# 4) 防火墙放行 80/443：
#    - Ubuntu/Debian: sudo ufw allow http; sudo ufw allow https; sudo ufw enable
#    - BC-Linux/CentOS/RHEL: sudo firewall-cmd --add-port=80/tcp --permanent
#                             sudo firewall-cmd --add-port=443/tcp --permanent
#                             sudo firewall-cmd --reload
#    （注意：云平台还有一层"安全组/暴露面管控"，需在控制台同时放行）
#
# ---------------------------------------------------------------------------
# 四、运维常用命令
# ---------------------------------------------------------------------------
#     查看运行状态    sudo systemctl status smartcampus
#     查看实时日志    sudo journalctl -u smartcampus -f
#     重启服务        sudo systemctl restart smartcampus
#     停止服务        sudo systemctl stop smartcampus
#     重载 Nginx      sudo nginx -s reload
#
# ---------------------------------------------------------------------------
# 五、如何接入真实大模型 / 真实视觉（可选扩展）
# ---------------------------------------------------------------------------
# 大模型：编辑 deploy/.env 设置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL，重启生效。
#         未配置时自动降级本地规则引擎，无需改代码。
#
# 真实视觉（YOLO）：在 requirements.txt 取消注释 ultralytics/opencv-python，
#         pip 安装后重启；推理在本机 CPU 进行（4核16G 可跑 YOLOv8n）。
#         视觉模型较重，注意内存与推理耗时。
#
# ---------------------------------------------------------------------------
# 六、已知注意事项
# ---------------------------------------------------------------------------
# - SQLite 并发：当前为单文件 SQLite，高并发写会锁库。若规模显著变大
#   （数百并发），建议开启 WAL（PRAGMA journal_mode=WAL）或迁移 MySQL/PostgreSQL。
# - 会话密钥：deploy.sh 首次部署如果用默认 SECRET_KEY，重启会话会失效；
#   生产务必设置 .env，保证稳定。
# - 内网/公网地址：192.168.0.64 是内网地址，云主机需配置相应安全组/公网IP
#   才能从外网访问。
# - 移动云"暴露面管控"：22/80/443 等端口默认不对公网开放（无论安全组如何配置），
#   需在控制台安全组放行，或走 OA 工单审批。若无法放行 80，可临时用高可用端口
#   （如 8080）或依赖 Workbench 网页终端管理。本系统默认 Gunicorn 监听 127.0.0.1:8000
#   仅本机回环，公有云暴露面不影响内网/Workbench 访问。
