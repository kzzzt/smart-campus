"""
视觉识别（真实模型版）—— 可插拔、可降级。

用途：对摄像头画面 / 上传照片做目标检测，识别电热毯、电煮锅等高功率电器，
为"IoT 功率 + 智算视觉"双通道提供真实图像证据（替代 detector 里的模拟占位）。

- 后端：Ultralytics YOLO（`pip install ultralytics opencv-python` 后即为真实检测）；
- 未安装依赖 / 无图像时自动降级返回空列表，不影响离线演示；
- 模型可用环境变量 `VISION_MODEL` 指定（默认 yolo11n.pt）。

用法示例：
    python -m src.energy.vision 图片.jpg [图片2.jpg ...]
"""
from __future__ import annotations

import os
import sys

# 与"高功率/违规电器"相关的候选类别（COCO 类名；用自定义模型时可改/扩展）
RISK_CLASSES = {
    "hair drier", "microwave", "toaster", "oven", "kettle",
    "refrigerator", "tv", "laptop",
}

_model = None


def is_available() -> bool:
    """是否已安装 ultralytics（未安装时走降级路径）。"""
    try:
        import ultralytics  # noqa: F401
        return True
    except Exception:
        return False


def _get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO  # 延迟导入，未安装不报错
        _model = YOLO(os.environ.get("VISION_MODEL", "yolo11n.pt"))
    return _model


def detect_image(image_source, conf: float = 0.35) -> list[dict]:
    """对单张图像做目标检测。

    image_source: 文件路径 / bytes / numpy.ndarray
    返回 [{"label","confidence","risk"}, ...]；未安装 ultralytics 或出错时返回 []。
    """
    if not is_available():
        return []
    try:
        model = _get_model()
        results = model.predict(source=image_source, conf=conf, verbose=False)
        dets = []
        for r in results:
            if not r.boxes:
                continue
            for box in r.boxes:
                label = model.names[int(box.cls[0])]
                dets.append({
                    "label": label,
                    "confidence": round(float(box.conf[0]), 2),
                    "risk": label in RISK_CLASSES,
                })
        return dets
    except Exception:
        return []


def _demo(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    if not is_available():
        print("[提示] 未安装 ultralytics，先执行：pip install ultralytics opencv-python 后再运行真实检测。")
        return 1
    for src in argv:
        dets = detect_image(src)
        if not dets:
            print(f"{src}: 未检出目标")
            continue
        print(f"{src}: 检出 {len(dets)} 个目标")
        for d in dets:
            print(f"  - {d['label']}  置信度 {d['confidence']}" + ("  [高风险候选]" if d["risk"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
