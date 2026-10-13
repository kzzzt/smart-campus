#!/usr/bin/env bash
#
# 智慧校园管理与安全平台 —— 云主机一键部署脚本
# 适用：Ubuntu 22.04/24.04 / Debian 11/12（apt 系），x86_64
# 用法：在仓库根目录执行  sudo bash deploy/deploy.sh
#
# 部署内容：
#   1. 安装系统依赖（python3-venv / nginx / build-essential）
#   2. 创建 Python 虚拟环境并安装 requirements
#   3. 初始化 SQLite 数据库（webapp/campus.db）
#   4. 配置 Gunicorn（4 worker，匹配 4 核）+ systemd 服务（开机自启、崩溃自恢复）
#   5. 配置 Nginx 反向代理（80 端口 -> Gunicorn 127.0.0.1:8000）
#   6. 打印部署结果与演示账号
#
set -euo pipefail

APP_NAME="smartcampus"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${APP_DIR}/.venv"
GUNICORN_PORT=8000
DOMAIN_OR_IP="${1:-127.0.0.1}"   # 可传：部署后访问的域名或公网IP，用于 Nginx server_name

echo "=================================================="
echo " 智慧校园管理平台 部署脚本"
echo " 应用目录: ${APP_DIR}"
echo " 访问地址: http://${DOMAIN_OR_IP}/"
echo "=================================================="

# ---------- 1. 系统依赖 ----------
echo "[1/6] 安装系统依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    nginx \
    build-essential \
    curl

# ---------- 2. Python 虚拟环境 ----------
echo "[2/6] 创建虚拟环境并安装依赖..."
if [ ! -d "${VENV_DIR}" ]; then
    python3 -m venv "${VENV_DIR}"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
pip install --upgrade pip -q
pip install -r "${APP_DIR}/requirements.txt" -q

# ---------- 3. 初始化数据库 ----------
echo "[3/6] 初始化数据库..."
cd "${APP_DIR}"
${VENV_DIR}/bin/python -c "from webapp import db; db.init_db(); print('数据库初始化完成: webapp/campus.db')"

# ---------- 4. Gunicorn + systemd ----------
echo "[4/6] 配置 Gunicorn 与 systemd 服务..."
# 服务文件（服务内直接引用 gunicorn 的绝对路径，避免 PATH 问题）
SVC_FILE="/etc/systemd/system/${APP_NAME}.service"
cat > "${SVC_FILE}" <<EOF
[Unit]
Description=Smart Campus Management Platform (Gunicorn)
After=network.target

[Service]
User=root
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/deploy/.env
ExecStart=${VENV_DIR}/bin/gunicorn -c ${APP_DIR}/deploy/gunicorn.conf.py 'webapp.app:app'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${APP_NAME}" >/dev/null 2>&1 || true
systemctl restart "${APP_NAME}"

# ---------- 5. Nginx 反向代理 ----------
echo "[5/6] 配置 Nginx 反向代理..."
NGX_FILE="/etc/nginx/sites-available/${APP_NAME}"
cat > "${NGX_FILE}" <<EOF
server {
    listen 80;
    server_name ${DOMAIN_OR_IP};

    client_max_body_size 10m;

    # 静态/通用文件由 Nginx 直出（如有 static 目录可启用）
    # location /static/ { alias ${APP_DIR}/webapp/static/; }

    location / {
        proxy_pass http://127.0.0.1:${GUNICORN_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
EOF

# 启用站点（Debian/Ubuntu 布局）
if [ -f "/etc/nginx/sites-enabled/default" ]; then
    rm -f "/etc/nginx/sites-enabled/default"
fi
ln -sfn "${NGX_FILE}" "/etc/nginx/sites-enabled/${APP_NAME}"
# 校验 nginx 配置
nginx -t && systemctl reload nginx || { echo "!! Nginx 配置校验失败，请检查 ${NGX_FILE}"; exit 1; }

# ---------- 6. 结果 ----------
echo "[6/6] 部署完成！"
sleep 3
echo "--------------------------------------------------"
echo " 服务状态:"
systemctl status "${APP_NAME}" --no-pager | head -n 6 || true
echo "--------------------------------------------------"
echo " 访问地址:  http://${DOMAIN_OR_IP}/"
echo " 演示账号（见登录页角色卡片）:"
echo "   学生  admin 账号: student / stu123"
echo "   辅导员: counselor / cou123"
echo "   管理人员: admin / SmartCampus@2026"
echo " 日志:     sudo journalctl -u ${APP_NAME} -f"
echo " 重启:     sudo systemctl restart ${APP_NAME}"
echo "=================================================="
