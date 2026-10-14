#!/usr/bin/env bash
#
# 智慧校园管理与安全平台 —— 云主机一键部署脚本（通用版）
# 适用：
#   - Ubuntu / Debian（apt 系）
#   - CentOS / RHEL / BC-Linux(Kylin) / openEuler / Anolis 等（yum/dnf 系）
# 用法：在仓库根目录执行  sudo bash deploy/deploy.sh [域名或公网IP]
#   （如：sudo bash deploy/deploy.sh 36.137.242.184）
#
# 部署内容：
#   1. 自动检测包管理器并安装系统依赖（python3 / venv / pip / nginx / gcc）
#   2. 创建 Python 虚拟环境并安装 requirements
#   3. 初始化 SQLite 数据库（webapp/campus.db）
#   4. 配置 Gunicorn + systemd 服务（开机自启、崩溃自恢复）
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

# 操作系统信息
echo "[init] 系统信息:"
cat /etc/os-release 2>/dev/null | grep -E "^(NAME|VERSION)=" || true

# ---------- 0. 检测包管理器 ----------
if command -v apt-get >/dev/null 2>&1; then
    PKG_MGR="apt"
    echo "[init] 检测到 apt 系包管理器（Ubuntu/Debian）"
elif command -v dnf >/dev/null 2>&1; then
    PKG_MGR="dnf"
    echo "[init] 检测到 dnf 包管理器（RHEL8+/BC-Linux）"
elif command -v yum >/dev/null 2>&1; then
    PKG_MGR="yum"
    echo "[init] 检测到 yum 包管理器（RHEL7/BC-Linux）"
else
    echo "[ERR] 未识别包管理器，请手工安装 python3/pip/nginx 后重试"
    exit 1
fi

# ---------- 1. 系统依赖 ----------
echo "[1/6] 安装系统依赖..."
if [ "$PKG_MGR" = "apt" ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip \
        nginx \
        build-essential \
        curl git
else
    # yum/dnf 系：BC-Linux / CentOS / RHEL
    INSTALL_CMD=""
    if [ "$PKG_MGR" = "dnf" ]; then
        INSTALL_CMD="dnf install -y"
    else
        INSTALL_CMD="yum install -y"
    fi
    ${INSTALL_CMD} epel-release 2>/dev/null || true
    ${INSTALL_CMD} python3 python3-pip python3-devel \
        nginx \
        gcc gcc-c++ make \
        curl git 2>/dev/null || true
    # 部分系统 python3-venv 是独立包；创建 venv 失败时单独补装
    if ! python3 -m venv --help >/dev/null 2>&1; then
        ${INSTALL_CMD} python3-venv 2>/dev/null || true
    fi
fi

# ---------- 2. Python 虚拟环境 ----------
echo "[2/6] 创建虚拟环境并安装依赖..."
PYTHON_BIN="$(command -v python3 || command -v python)"
if [ ! -d "${VENV_DIR}" ]; then
    ${PYTHON_BIN} -m venv "${VENV_DIR}"
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
systemctl restart "${APP_NAME}" || { echo "!! systemd 启动失败，尝试直接前台运行查看错误:"; ${VENV_DIR}/bin/gunicorn -c "${APP_DIR}/deploy/gunicorn.conf.py" 'webapp.app:app' 2>&1 | head -n 20; exit 1; }

# ---------- 5. Nginx 反向代理 ----------
echo "[5/6] 配置 Nginx 反向代理..."
NGX_CONFDIR="/etc/nginx/conf.d"
if [ -d "/etc/nginx/sites-available" ]; then
    NGX_CONFDIR="/etc/nginx/sites-available"
fi
NGX_FILE="${NGX_CONFDIR}/${APP_NAME}.conf"
cat > "${NGX_FILE}" <<EOF
server {
    listen 80;
    server_name ${DOMAIN_OR_IP} _;

    client_max_body_size 10m;

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

# 启用站点（兼容 sites-enabled / conf.d 两种布局）
if [ -d "/etc/nginx/sites-available" ] && [ -d "/etc/nginx/sites-enabled" ]; then
    if [ -f "/etc/nginx/sites-enabled/default" ]; then
        rm -f "/etc/nginx/sites-enabled/default"
    fi
    ln -sfn "${NGX_FILE}" "/etc/nginx/sites-enabled/${APP_NAME}.conf"
    grep -q "include /etc/nginx/sites-enabled" /etc/nginx/nginx.conf || \
        sed -i 's|include /etc/nginx/conf.d/\*.conf;|include /etc/nginx/conf.d/*.conf;\n    include /etc/nginx/sites-enabled/*.conf;|' /etc/nginx/nginx.conf
fi

# 校验并重载 nginx
nginx -t && systemctl restart nginx || { echo "!! Nginx 配置校验失败，请检查 ${NGX_FILE}"; exit 1; }
systemctl enable nginx >/dev/null 2>&1 || true

# ---------- 6. 结果 ----------
echo "[6/6] 部署完成！"
sleep 3
echo "--------------------------------------------------"
echo " 服务状态:"
systemctl status "${APP_NAME}" --no-pager | head -n 6 || true
echo "--------------------------------------------------"
echo " 访问地址:  http://${DOMAIN_OR_IP}/"
echo " 演示账号（见登录页角色卡片）:"
echo "   学生:      student / stu123"
echo "   辅导员:    counselor / cou123"
echo "   管理人员:  admin / SmartCampus@2026"
echo " 日志:       sudo journalctl -u ${APP_NAME} -f"
echo " 重启:       sudo systemctl restart ${APP_NAME}"
echo "=================================================="
echo " 提示: 若 80 端口在公网无法访问，可能是云平台'暴露面管控'拦截，"
echo "       需在控制台放行 80 或走 OA 工单审批（见 deploy/README.md）。"
