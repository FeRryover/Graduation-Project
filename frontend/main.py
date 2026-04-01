import json
import hashlib
import mimetypes
import queue
import re
import shutil
import sys
import threading
import time
import traceback
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from LLMAgent.OSM.getosmTools import RoadNetworkGenerator
from LLMAgent.image_recognition.image_recognition import recognition
from LLMAgent.road_extraction.satellite_predict import predict_road_from_satellite_image
from LLMAgent.simple_modeling.toolfour import BuildSimpleRoadNetwork
from LangChainConnect_new import run_agent_query

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR = BASE_DIR / "download_cache"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="MixSimGPT Frontend", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

TASK_QUEUE: "queue.Queue[str]" = queue.Queue()
TASKS: Dict[str, Dict[str, Any]] = {}
ARTIFACTS: Dict[str, Dict[str, Any]] = {}
TASK_LOCK = threading.Lock()
WORKER_STARTED = False
SERVER_SESSION_ID = uuid.uuid4().hex

MAX_UPLOAD_SIZE = 10 * 1024 * 1024
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def _clear_download_cache() -> None:
    if not DOWNLOAD_DIR.exists():
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        return

    for child in DOWNLOAD_DIR.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except Exception:
            continue


def _queue_position(task_id: str) -> int:
    with TASK_QUEUE.mutex:
        pending = list(TASK_QUEUE.queue)
    try:
        return pending.index(task_id) + 1
    except ValueError:
        return 0


def _is_image_file(path: Path) -> bool:
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}


def _is_cancel_requested(task_id: str) -> bool:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return False
        return bool(task.get("cancel_requested", False))


def _assert_not_canceled(task_id: str) -> None:
    if _is_cancel_requested(task_id):
        raise RuntimeError("__TASK_CANCELED__")


def _cancel_pending_task_in_queue(task_id: str) -> bool:
    with TASK_QUEUE.mutex:
        pending = list(TASK_QUEUE.queue)
        if task_id not in pending:
            return False
        pending.remove(task_id)
        TASK_QUEUE.queue.clear()
        TASK_QUEUE.queue.extend(pending)
    return True


def _resolve_to_path(raw_path: str) -> Optional[Path]:
    if not raw_path:
        return None
    p = Path(raw_path.strip().strip("`").strip('"').strip("'"))
    candidates: list[Path] = []
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(Path.cwd() / p)
        candidates.append(PROJECT_ROOT / p)

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if resolved.exists():
            return resolved
    return None


def _extract_paths_from_text(text: str) -> list[str]:
    if not text:
        return []

    patterns = [
        r"(?:[A-Za-z]:[\\/][^\n\r\t`]+?\.(?:csv|geojson|png|jpg|jpeg|zip|osm))",
        r"(?:\.\.?[\\/][^\n\r\t`]+?\.(?:csv|geojson|png|jpg|jpeg|zip|osm))",
        r"(?:data[\\/][^\n\r\t`]+?\.(?:csv|geojson|png|jpg|jpeg|zip|osm))",
        r"(?:result[\\/][^\n\r\t`]+?\.(?:csv|geojson|png|jpg|jpeg|zip|osm))",
        r"(?:[A-Za-z]:[\\/][^\n\r\t`]+)",
        r"(?:\.\.?[\\/][^\n\r\t`]+)",
        r"(?:data[\\/][^\n\r\t`]+)",
        r"(?:result[\\/][^\n\r\t`]+)",
    ]

    found: list[str] = []
    for pat in patterns:
        for m in re.findall(pat, text):
            candidate = m.strip().strip("。").strip("，").strip(";").strip(",")
            candidate = re.sub(r"(的地址|地址)$", "", candidate)
            if candidate and candidate not in found:
                found.append(candidate)
    return found


def _register_artifact(path: Path, label: str) -> Dict[str, Any]:
    artifact_id = uuid.uuid4().hex
    is_image = _is_image_file(path)

    with TASK_LOCK:
        ARTIFACTS[artifact_id] = {
            "path": str(path),
            "name": path.name,
            "label": label,
            "is_image": is_image,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    return {
        "artifact_id": artifact_id,
        "label": label,
        "name": path.name,
        "path": str(path),
        "is_image": is_image,
        "download_url": f"/api/artifacts/{artifact_id}/download",
        "view_url": f"/api/artifacts/{artifact_id}/view" if is_image else None,
    }


def _build_artifacts_from_result(result: Dict[str, Any]) -> list[Dict[str, Any]]:
    artifacts: list[Dict[str, Any]] = []
    seen: set[str] = set()
    seen_fingerprints: set[str] = set()

    def file_fingerprint(path_obj: Path) -> Optional[str]:
        if not path_obj.exists() or not path_obj.is_file():
            return None
        try:
            h = hashlib.sha1()
            with open(path_obj, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    def add_path(path_obj: Path, label: str) -> None:
        if path_obj.is_file():
            fp = file_fingerprint(path_obj)
            if fp and fp in seen_fingerprints:
                return
            if fp:
                seen_fingerprints.add(fp)

        key = str(path_obj)
        if key in seen:
            return
        seen.add(key)
        artifacts.append(_register_artifact(path_obj, label))

    def maybe_extract_csv_from_zip(zip_path: Path, label: str) -> None:
        if zip_path.suffix.lower() != ".zip":
            return

        zip_key = hashlib.sha1(str(zip_path.resolve()).encode("utf-8")).hexdigest()[:12]
        extract_root = DOWNLOAD_DIR / "unzipped_csv" / f"{zip_path.stem}_{zip_key}"
        if extract_root.exists():
            shutil.rmtree(extract_root, ignore_errors=True)
        extract_root.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                csv_members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
                for member in csv_members:
                    zf.extract(member, path=extract_root)
        except Exception:
            return

        for candidate in sorted(extract_root.rglob("*.csv")):
            if candidate.is_file():
                add_path(candidate, f"{label}-{candidate.name}")

    def maybe_add(raw_path: Optional[str], label: str) -> None:
        if not raw_path:
            return
        p = _resolve_to_path(raw_path)
        if p is None:
            return

        if p.is_dir():
            # Prefer exposing common node/link CSV files for direct map rendering.
            csv_names = [
                "node.csv",
                "link.csv",
            ]
            for name in csv_names:
                candidate = p / name
                if candidate.exists() and candidate.is_file():
                    add_path(candidate, f"{label}-{name}")

            for candidate in sorted(p.glob("*.geojson")):
                if candidate.is_file():
                    add_path(candidate, f"{label}-{candidate.name}")

            # Also include timestamped nodes/edges CSV files if present.
            for candidate in sorted(p.glob("*.csv")):
                if candidate.name.lower().startswith(("nodes_", "edges_")):
                    add_path(candidate, f"{label}-{candidate.name}")

            zip_name = p.name
            zip_base = DOWNLOAD_DIR / zip_name
            zip_target = Path(str(zip_base) + ".zip")
            if zip_target.exists():
                zip_target.unlink()
            zip_file = shutil.make_archive(str(zip_base), "zip", root_dir=str(p))
            p = Path(zip_file)
            add_path(p, f"{label}-all")
            maybe_extract_csv_from_zip(p, f"{label}-all")
            return

        add_path(p, label)
        maybe_extract_csv_from_zip(p, label)

    maybe_add(result.get("gmns_zip"), "GMNS 压缩包")
    maybe_add(result.get("geojson"), "GeoJSON 文件")
    maybe_add(result.get("preview_image"), "预览图")
    maybe_add(result.get("input_image"), "输入图片")

    text = str(result.get("message") or "")
    for idx, candidate in enumerate(_extract_paths_from_text(text), start=1):
        maybe_add(candidate, f"结果文件 {idx}")

    return artifacts


def _short_text(text: str, limit: int = 140) -> str:
    return " ".join(str(text or "").split())


def _build_chat_message(task_type: str, result: Dict[str, Any]) -> str:
    success_messages = {
        "simple-network": "路网已生成。",
        "osm-network": "路网已生成。",
        "handdrawn": "识别完成。",
        "satellite": "提取完成。",
    }
    success_text = success_messages.get(str(task_type or "").strip(), "任务成功，结果文件已生成。")

    artifacts = result.get("artifacts") or []
    if isinstance(artifacts, list) and artifacts:
        return success_text

    raw_message = str(result.get("message") or "").strip()
    if not raw_message:
        return "任务已完成，但未检测到可下载文件。"

    lowered = raw_message.lower()
    if raw_message.startswith("错误") or "error" in lowered:
        return f"任务完成，但未生成文件：{_short_text(raw_message)}"

    paths = _extract_paths_from_text(raw_message)
    if paths:
        return success_text

    return f"任务已完成：{_short_text(raw_message)}"


def _task_stages(task_type: str) -> list[str]:
    mapping = {
        "simple-network": ["参数校验", "生成路网", "整理输出文件"],
        "osm-network": ["地址与半径解析", "抓取并转换路网", "整理输出文件"],
        "handdrawn": ["读取输入图片", "图像识别与路网重建", "整理输出文件"],
        "satellite": ["读取输入图片", "卫星道路提取", "整理输出文件"],
        "agent-chat": [
            "理解用户需求",
            "整理输入上下文",
            "构建 Agent 提示",
            "调用 LangChain Agent",
            "解析 Agent 输出",
            "抽取结果文件",
            "整理输出文件",
        ],
    }
    return mapping.get(task_type, ["执行任务", "整理输出文件"])


def _build_task_display_title(task_type: str, payload: Dict[str, Any]) -> str:
    if task_type == "agent-chat":
        text = str(payload.get("message", "")).strip()
        source_name = str(payload.get("source_name", "")).strip()
        if not text and payload.get("image_path"):
            if source_name:
                return f"Agent 对话任务（{source_name}）"
            return "Agent 对话任务（含图片）"
        if not text:
            return "Agent 对话任务"
        return f"Agent：{text}"

    if task_type == "osm-network":
        place = str(payload.get("place", "天安门"))
        radius = payload.get("radius_m", 1000)
        return f"生成{place}附近{radius}m路网"

    if task_type == "simple-network":
        rows = payload.get("rows", "?")
        cols = payload.get("cols", "?")
        precision = payload.get("precision_m")
        if precision is None:
            return f"生成{rows}x{cols}简单路网"
        return f"生成{rows}x{cols}简单路网（精度{precision}m）"

    if task_type == "satellite":
        source_name = str(payload.get("source_name", "")).strip()
        if source_name:
            return f"卫星图道路提取：{source_name}"
        image_path = str(payload.get("image_path", ""))
        image_name = Path(image_path).name if image_path else "图片"
        return f"卫星图道路提取：{image_name}"

    if task_type == "handdrawn":
        source_name = str(payload.get("source_name", "")).strip()
        if source_name:
            return f"手绘图路网识别：{source_name}"
        image_path = str(payload.get("image_path", ""))
        image_name = Path(image_path).name if image_path else "图片"
        return f"手绘图路网识别：{image_name}"

    return task_type


# 以下 4 个本地规则分流辅助函数已暂停使用，原因如下：
# 1. 当前 api_chat 已改为统一创建 agent-chat 任务，再交给 LangChain Agent 处理。
# 2. 主调用链中不再引用这些函数；它们只在彼此之间互相调用，已不影响当前功能。
# 3. 暂时保留注释内容，便于后续如果要恢复“前端本地规则分流”时参考原实现。
#
# def _extract_radius_m(text: str) -> int:
#     m = re.search(r"(\d{1,4}(?:\.\d+)?)\s*(?:米|m|M)\b", text)
#     if m:
#         try:
#             radius = int(float(m.group(1)))
#             if 1 <= radius <= 5000:
#                 return radius
#         except Exception:
#             pass
#     return 1000
#
#
# def _extract_simple_network_args(text: str) -> Optional[Dict[str, Any]]:
#     shape = re.search(r"(\d+)\s*[,，xX*]\s*(\d+)", text)
#     if not shape:
#         return None
#
#     rows = int(shape.group(1))
#     cols = int(shape.group(2))
#     if rows <= 0 or cols <= 0:
#         return None
#
#     precision_m: Optional[float] = None
#     precision_match = re.search(r"(\d+(?:\.\d+)?)\s*米", text)
#     if precision_match:
#         try:
#             precision_m = float(precision_match.group(1))
#         except Exception:
#             precision_m = None
#
#     return {"rows": rows, "cols": cols, "precision_m": precision_m}
#
#
# def _extract_place_text(text: str) -> str:
#     place = re.sub(r"(半径|附近|周边|范围|以内|内)\s*\d+(?:\.\d+)?\s*(?:米|m|M)?", "", text)
#     place = re.sub(r"(生成|抓取|提取|创建|获取|请|帮我|给我|路网|地图|的|以|为中心)", "", place)
#     place = re.sub(r"[^\w\u4e00-\u9fff\s]", " ", place)
#     place = place.replace("，", " ").replace(",", " ")
#     place = " ".join(place.split()).strip()
#     return place or "天安门"
#
#
# def _plan_chat_task(message: str, image_path: Optional[str]) -> Dict[str, Any]:
#     text = (message or "").strip()
#     lower = text.lower()
#
#     if image_path:
#         if any(k in lower for k in ["卫星", "遥感", "satellite", "tiff", "tif"]):
#             return {
#                 "task_type": "satellite",
#                 "payload": {"image_path": image_path},
#                 "assistant": "已识别为卫星图道路提取任务，正在排队执行。",
#             }
#         return {
#             "task_type": "handdrawn",
#             "payload": {"image_path": image_path},
#             "assistant": "已识别为手绘图路网识别任务，正在排队执行。",
#         }
#
#     simple_args = _extract_simple_network_args(text)
#     if simple_args and any(k in text for k in ["规则", "简单", "矩形", "网格", "路网"]):
#         return {
#             "task_type": "simple-network",
#             "payload": simple_args,
#             "assistant": f"已识别为简单路网生成任务（{simple_args['rows']}x{simple_args['cols']}），正在排队执行。",
#         }
#
#     if any(k in lower for k in ["osm", "天安门", "附近", "半径", "place", "地图", "路网"]):
#         radius_m = _extract_radius_m(text)
#         place = _extract_place_text(text)
#         return {
#             "task_type": "osm-network",
#             "payload": {"place": place, "radius_m": radius_m},
#             "assistant": f"已识别为 OSM 路网抓取任务（地点：{place}，半径：{radius_m}m），正在排队执行。",
#         }
#
#     return {
#         "task_type": None,
#         "payload": None,
#         "assistant": "我可以帮你做四类任务：1) 简单路网（如 5,4） 2) OSM 地点路网（如 天安门 半径500米） 3) 上传手绘图识别 4) 上传卫星图提取。",
#     }


def _set_stage(task_id: str, stage: str, progress: Optional[int] = None) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return
        if task.get("current_stage") != stage:
            task["current_stage"] = stage
            if stage not in task["stage_history"]:
                task["stage_history"].append(stage)
        if progress is not None:
            task["progress"] = progress
        task["log_version"] += 1

def _append_log(task_id: str, message: str) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        task["logs"].append(f"[{now}] {message}")
        task["log_version"] += 1


def _update_task(task_id: str, **changes: Any) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return
        task.update(changes)


def _snapshot_task(task_id: str) -> Dict[str, Any]:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return {
            "task_id": task["task_id"],
            "task_type": task["task_type"],
            "display_title": task.get("display_title", task["task_type"]),
            "status": task["status"],
            "cancel_requested": task.get("cancel_requested", False),
            "progress": task["progress"],
            "queue_position": _queue_position(task_id) if task["status"] == "pending" else 0,
            "created_at": task["created_at"],
            "started_at": task.get("started_at"),
            "ended_at": task.get("ended_at"),
            "error": task.get("error"),
            "result": task.get("result"),
            "current_stage": task.get("current_stage"),
            "stage_history": list(task.get("stage_history", [])),
            "stages": list(task.get("stages", [])),
            "log_version": task["log_version"],
        }


def _execute_task(task_id: str) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return
        task_type = task["task_type"]
        payload = dict(task["payload"])

    _update_task(task_id, status="running", progress=5, started_at=datetime.now().isoformat(timespec="seconds"))
    _set_stage(task_id, "开始执行", 5)
    _assert_not_canceled(task_id)

    try:
        if task_type == "simple-network":
            _assert_not_canceled(task_id)
            _set_stage(task_id, "参数校验", 20)
            rows = int(payload["rows"])
            cols = int(payload["cols"])
            precision_m = payload.get("precision_m")
            _append_log(task_id, f"参数 rows={rows}, cols={cols}, precision_m={precision_m}")

            tool = BuildSimpleRoadNetwork()
            _assert_not_canceled(task_id)
            _set_stage(task_id, "生成路网", 60)
            if precision_m is None:
                text = tool.inference(f"{rows},{cols}")
            else:
                text = tool.inference(f"{rows},{cols},{precision_m}")
            result = {"message": text}
            _set_stage(task_id, "整理输出文件", 90)
            _assert_not_canceled(task_id)
            result["artifacts"] = _build_artifacts_from_result(result)
            _update_task(task_id, progress=100, status="completed", result=result)
            _set_stage(task_id, "任务完成", 100)

        elif task_type == "osm-network":
            _assert_not_canceled(task_id)
            _set_stage(task_id, "地址与半径解析", 20)
            place = payload["place"]
            radius_m = int(payload["radius_m"])
            _append_log(task_id, f"参数 place={place}, radius_m={radius_m}")
            _set_stage(task_id, "抓取并转换路网", 60)
            _assert_not_canceled(task_id)
            text = RoadNetworkGenerator.generate_road_network_map(f"{place},{radius_m}")
            result = {"message": text}
            _set_stage(task_id, "整理输出文件", 90)
            _assert_not_canceled(task_id)
            result["artifacts"] = _build_artifacts_from_result(result)
            _update_task(task_id, progress=100, status="completed", result=result)
            _set_stage(task_id, "任务完成", 100)

        elif task_type == "handdrawn":
            _assert_not_canceled(task_id)
            _set_stage(task_id, "读取输入图片", 15)
            image_path = payload["image_path"]
            _append_log(task_id, f"输入图片: {image_path}")
            _set_stage(task_id, "图像识别与路网重建", 55)
            _assert_not_canceled(task_id)
            gmns_zip, preview_image, geojson_path = recognition(image_path)
            result = {
                "message": "Hand-drawn image recognition finished.",
                "gmns_zip": gmns_zip,
                "geojson": geojson_path,
                "preview_image": preview_image,
                "input_image": image_path,
            }
            _set_stage(task_id, "整理输出文件", 90)
            _assert_not_canceled(task_id)
            result["artifacts"] = _build_artifacts_from_result(result)
            _update_task(task_id, progress=100, status="completed", result=result)
            _set_stage(task_id, "任务完成", 100)

        elif task_type == "satellite":
            _assert_not_canceled(task_id)
            _set_stage(task_id, "读取输入图片", 15)
            image_path = payload["image_path"]
            _append_log(task_id, f"输入图片: {image_path}")
            _set_stage(task_id, "卫星道路提取", 55)
            _assert_not_canceled(task_id)
            gmns_zip, preview_image, geojson_path = predict_road_from_satellite_image(image_path)
            result = {
                "message": "Satellite extraction finished.",
                "gmns_zip": gmns_zip,
                "geojson": geojson_path,
                "preview_image": preview_image,
                "input_image": image_path,
            }
            _set_stage(task_id, "整理输出文件", 90)
            _assert_not_canceled(task_id)
            result["artifacts"] = _build_artifacts_from_result(result)
            _update_task(task_id, progress=100, status="completed", result=result)
            _set_stage(task_id, "任务完成", 100)

        elif task_type == "agent-chat":
            stage_marks: list[tuple[str, float]] = []

            def mark_stage(stage: str, progress: int) -> None:
                _set_stage(task_id, stage, progress)
                stage_marks.append((stage, time.perf_counter()))

            _assert_not_canceled(task_id)
            mark_stage("理解用户需求", 20)
            message = str(payload.get("message", "")).strip()
            image_path = str(payload.get("image_path", "")).strip()

            _assert_not_canceled(task_id)
            mark_stage("整理输入上下文", 30)
            agent_prompt = message
            if image_path:
                extra = f"补充信息：若需处理图片，请使用该路径：{image_path}"
                agent_prompt = f"{agent_prompt}\n\n{extra}".strip()

            _assert_not_canceled(task_id)
            mark_stage("构建 Agent 提示", 40)
            _append_log(task_id, "已提交给 LangChain Agent")
            mark_stage("调用 LangChain Agent", 60)
            _assert_not_canceled(task_id)
            agent_output = run_agent_query(agent_prompt)

            _assert_not_canceled(task_id)
            mark_stage("解析 Agent 输出", 75)

            if isinstance(agent_output, dict):
                answer_text = str(agent_output.get("output", ""))
                tool_steps = agent_output.get("tool_steps") or []
            else:
                answer_text = str(agent_output)
                tool_steps = []

            result: Dict[str, Any] = {
                "message": answer_text,
                "agent_tool_steps": tool_steps,
            }
            if image_path:
                result["input_image"] = image_path

            mark_stage("抽取结果文件", 86)
            _assert_not_canceled(task_id)
            result["artifacts"] = _build_artifacts_from_result(result)

            mark_stage("整理输出文件", 94)

            stage_durations = []
            for idx, (stage_name, start_ts) in enumerate(stage_marks):
                if idx + 1 < len(stage_marks):
                    end_ts = stage_marks[idx + 1][1]
                else:
                    end_ts = time.perf_counter()
                duration = max(0.0, end_ts - start_ts)
                stage_durations.append(
                    {
                        "stage": stage_name,
                        "seconds": round(duration, 4),
                    }
                )
            result["stage_durations"] = stage_durations
            result["chat_message"] = _build_chat_message(task_type, result)

            _update_task(task_id, progress=100, status="completed", result=result)
            _set_stage(task_id, "任务完成", 100)
        else:
            raise ValueError(f"Unknown task type: {task_type}")

    except Exception as exc:
        if str(exc) == "__TASK_CANCELED__":
            _update_task(task_id, status="canceled", error=None)
            _set_stage(task_id, "任务已取消")
            return
        _update_task(
            task_id,
            status="failed",
            error=f"{exc}\n{traceback.format_exc()}",
        )
        _set_stage(task_id, "任务失败")
        _append_log(task_id, f"任务失败: {exc}")
    finally:
        with TASK_LOCK:
            task = TASKS.get(task_id)
            if task is not None:
                task["ended_at"] = datetime.now().isoformat(timespec="seconds")


def _worker_loop() -> None:
    while True:
        task_id = TASK_QUEUE.get()
        try:
            _execute_task(task_id)
        finally:
            TASK_QUEUE.task_done()


def _create_task(task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    task_id = uuid.uuid4().hex
    stages = _task_stages(task_type)
    display_title = _build_task_display_title(task_type, payload)
    task = {
        "task_id": task_id,
        "task_type": task_type,
        "display_title": display_title,
        "payload": payload,
        "status": "pending",
        "progress": 0,
        "logs": [],
        "log_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": None,
        "ended_at": None,
        "result": None,
        "error": None,
        "cancel_requested": False,
        "stages": stages,
        "current_stage": "等待队列",
        "stage_history": ["等待队列"],
    }
    with TASK_LOCK:
        TASKS[task_id] = task
    TASK_QUEUE.put(task_id)
    return {
        "ok": True,
        "task_id": task_id,
        "display_title": display_title,
        "status": "pending",
        "queue_position": _queue_position(task_id),
        "current_stage": "等待队列",
    }


async def _resolve_image_input(image_path: Optional[str], image_file: Optional[UploadFile], task_prefix: str) -> str:
    if image_file is not None and image_file.filename:
        ext = Path(image_file.filename).suffix or ".img"
        if ext.lower() not in ALLOWED_IMAGE_EXTS:
            raise HTTPException(status_code=400, detail="上传文件类型不支持，仅允许 png/jpg/jpeg/bmp/webp/tif/tiff")
        safe_name = f"{task_prefix}_{uuid.uuid4().hex}{ext}"
        save_path = UPLOAD_DIR / safe_name
        content = await image_file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail="上传文件过大，最大支持 10MB")
        save_path.write_bytes(content)
        return str(save_path)

    if image_path and image_path.strip():
        return image_path.strip()

    raise HTTPException(status_code=400, detail="请提供图片路径或上传图片文件")


@app.on_event("startup")
def startup_worker() -> None:
    global WORKER_STARTED
    _clear_download_cache()
    if WORKER_STARTED:
        return
    worker = threading.Thread(target=_worker_loop, daemon=True, name="mixsimgpt-task-worker")
    worker.start()
    WORKER_STARTED = True


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    icon_path = BASE_DIR / "static" / "favicon.svg"
    return FileResponse(
        path=str(icon_path),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@app.get("/api/session")
def api_session() -> JSONResponse:
    return JSONResponse({"ok": True, "session_id": SERVER_SESSION_ID})


@app.post("/api/tasks/simple-network")
def api_simple_network(
    rows: int = Form(...),
    cols: int = Form(...),
    precision_m: Optional[float] = Form(default=None),
) -> JSONResponse:
    task = _create_task(
        "simple-network",
        {
            "rows": rows,
            "cols": cols,
            "precision_m": precision_m,
        },
    )
    return JSONResponse(task)


@app.post("/api/tasks/osm-network")
def api_osm_network(
    place: str = Form(...),
    radius_m: int = Form(default=1000),
) -> JSONResponse:
    task = _create_task(
        "osm-network",
        {
            "place": place,
            "radius_m": radius_m,
        },
    )
    return JSONResponse(task)


@app.post("/api/tasks/handdrawn")
async def api_handdrawn(
    image_path: Optional[str] = Form(default=None),
    image_file: Optional[UploadFile] = File(default=None),
) -> JSONResponse:
    source_name = image_file.filename if (image_file is not None and image_file.filename) else None
    resolved_path = await _resolve_image_input(image_path, image_file, "handdrawn")
    if source_name is None:
        source_name = Path(resolved_path).name
    task = _create_task("handdrawn", {"image_path": resolved_path, "source_name": source_name})
    return JSONResponse(task)


@app.post("/api/tasks/satellite")
async def api_satellite(
    image_path: Optional[str] = Form(default=None),
    image_file: Optional[UploadFile] = File(default=None),
) -> JSONResponse:
    source_name = image_file.filename if (image_file is not None and image_file.filename) else None
    resolved_path = await _resolve_image_input(image_path, image_file, "satellite")
    if source_name is None:
        source_name = Path(resolved_path).name
    task = _create_task("satellite", {"image_path": resolved_path, "source_name": source_name})
    return JSONResponse(task)


@app.post("/api/chat")
async def api_chat(
    message: str = Form(default=""),
    image_path: Optional[str] = Form(default=None),
    image_file: Optional[UploadFile] = File(default=None),
) -> JSONResponse:
    resolved_image_path: Optional[str] = None
    source_name: Optional[str] = image_file.filename if (image_file is not None and image_file.filename) else None
    if (image_file is not None and image_file.filename) or (image_path and image_path.strip()):
        resolved_image_path = await _resolve_image_input(image_path, image_file, "chat")
        if source_name is None and resolved_image_path:
            source_name = Path(resolved_image_path).name

    chat_text = (message or "").strip()
    if not chat_text and not resolved_image_path:
        return JSONResponse({"ok": True, "assistant": "请输入文本或上传图片后再发送。", "task": None})

    if resolved_image_path and not chat_text:
        display_name = source_name or (Path(resolved_image_path).name if resolved_image_path else "图片")
        return JSONResponse(
            {
                "ok": True,
                "assistant": (
                    f"已收到图片“{display_name}”，但我还不清楚你的意图。"
                    "请再补充一句，例如："
                    "“这是手绘图，请帮我识别路网”、"
                    "“这是卫星图，请帮我提取道路”，"
                    "或者直接说明你希望我对这张图做什么。"
                ),
                "task": None,
            }
        )

    if not resolved_image_path and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", chat_text):
        return JSONResponse(
            {
                "ok": True,
                "assistant": "仅输入数字无法判断你的意图。请描述你要生成的路网类型、地点范围，或上传需要处理的图片。",
                "task": None,
            }
        )

    task = _create_task(
        "agent-chat",
        {
            "message": chat_text,
            "image_path": resolved_image_path,
            "source_name": source_name,
        },
    )
    return JSONResponse(
        {
            "ok": True,
            "assistant": "已提交到 LangChain Agent，正在执行。",
            "task": task,
        }
    )


@app.get("/api/tasks/{task_id}")
def api_get_task(task_id: str) -> JSONResponse:
    return JSONResponse({"ok": True, "task": _snapshot_task(task_id)})


@app.get("/api/tasks")
def api_list_tasks(limit: int = 50) -> JSONResponse:
    with TASK_LOCK:
        tasks = list(TASKS.values())

    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    items = []
    for task in tasks[: max(1, min(limit, 200))]:
        items.append(
            {
                "task_id": task["task_id"],
                "task_type": task["task_type"],
                "display_title": task.get("display_title", task["task_type"]),
                "status": task["status"],
                "progress": task.get("progress", 0),
                "current_stage": task.get("current_stage"),
                "created_at": task.get("created_at"),
                "started_at": task.get("started_at"),
                "ended_at": task.get("ended_at"),
                "cancel_requested": task.get("cancel_requested", False),
            }
        )
    return JSONResponse({"ok": True, "tasks": items})


@app.post("/api/tasks/{task_id}/cancel")
def api_cancel_task(task_id: str) -> JSONResponse:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        status = task.get("status")

    if status in {"completed", "failed", "canceled"}:
        return JSONResponse({"ok": True, "task_id": task_id, "status": status, "message": "任务已结束，无法取消"})

    if status == "pending":
        removed = _cancel_pending_task_in_queue(task_id)
        if removed:
            _update_task(task_id, status="canceled", cancel_requested=True, ended_at=datetime.now().isoformat(timespec="seconds"))
            _set_stage(task_id, "任务已取消")
            return JSONResponse({"ok": True, "task_id": task_id, "status": "canceled", "message": "已取消排队任务"})

    _update_task(task_id, cancel_requested=True)
    _set_stage(task_id, "取消请求已接收")
    return JSONResponse({"ok": True, "task_id": task_id, "status": "cancel_requested", "message": "已请求取消，任务将在安全节点停止"})


@app.post("/api/tasks/{task_id}/delete")
def api_delete_task(task_id: str) -> JSONResponse:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        status = task.get("status")
        if status in {"pending", "running"}:
            return JSONResponse(
                {
                    "ok": False,
                    "task_id": task_id,
                    "status": status,
                    "error": "任务正在执行或排队中，暂不支持删除记录",
                },
                status_code=400,
            )

        result = task.get("result") or {}
        artifacts = result.get("artifacts") or []
        for item in artifacts:
            aid = item.get("artifact_id")
            if aid and aid in ARTIFACTS:
                ARTIFACTS.pop(aid, None)

        TASKS.pop(task_id, None)

    return JSONResponse({"ok": True, "task_id": task_id, "message": "任务记录已删除"})


@app.post("/api/tasks/clear")
def api_clear_tasks() -> JSONResponse:
    deleted_task_ids: list[str] = []
    skipped_count = 0

    with TASK_LOCK:
        finished_statuses = {"completed", "failed", "canceled"}
        task_ids = list(TASKS.keys())
        for task_id in task_ids:
            task = TASKS.get(task_id)
            if task is None:
                continue

            status = task.get("status")
            if status not in finished_statuses:
                skipped_count += 1
                continue

            result = task.get("result") or {}
            artifacts = result.get("artifacts") or []
            for item in artifacts:
                aid = item.get("artifact_id")
                if aid and aid in ARTIFACTS:
                    ARTIFACTS.pop(aid, None)

            TASKS.pop(task_id, None)
            deleted_task_ids.append(task_id)

    message = f"已删除 {len(deleted_task_ids)} 条历史记录"
    if skipped_count > 0:
        message += f"，保留 {skipped_count} 条运行中或排队中的任务"

    return JSONResponse(
        {
            "ok": True,
            "deleted_count": len(deleted_task_ids),
            "deleted_task_ids": deleted_task_ids,
            "skipped_count": skipped_count,
            "message": message,
        }
    )


@app.get("/api/tasks/{task_id}/events")
def api_task_events(task_id: str) -> StreamingResponse:
    def stream() -> Any:
        last_version = -1
        last_keepalive = time.monotonic()
        while True:
            task = _snapshot_task(task_id)
            if task["log_version"] == last_version:
                now = time.monotonic()
                if now - last_keepalive >= 10:
                    last_keepalive = now
                    yield ": keep-alive\n\n"
                time.sleep(1)
                continue
            payload = {
                "task_id": task["task_id"],
                "display_title": task.get("display_title", task["task_type"]),
                "status": task["status"],
                "progress": task["progress"],
                "queue_position": task["queue_position"],
                "current_stage": task.get("current_stage"),
                "stage_history": task.get("stage_history", []),
                "stages": task.get("stages", []),
                "result": task["result"],
                "error": task["error"],
            }
            last_version = task["log_version"]
            last_keepalive = time.monotonic()
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            if task["status"] in {"completed", "failed"}:
                break
            if task["status"] == "canceled":
                break


    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/artifacts/{artifact_id}/download")
def api_artifact_download(artifact_id: str) -> FileResponse:
    with TASK_LOCK:
        artifact = ARTIFACTS.get(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    path = Path(artifact["path"])
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file is missing")

    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path=str(path), media_type=media_type, filename=artifact["name"])


@app.get("/api/artifacts/{artifact_id}/view")
def api_artifact_view(artifact_id: str) -> FileResponse:
    with TASK_LOCK:
        artifact = ARTIFACTS.get(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    path = Path(artifact["path"])
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file is missing")
    if not _is_image_file(path):
        raise HTTPException(status_code=400, detail="Artifact is not an image")

    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path=str(path), media_type=media_type)


@app.get("/api/tasks/{task_id}/download-all")
def api_task_download_all(task_id: str) -> FileResponse:
    task = _snapshot_task(task_id)
    result = task.get("result") or {}
    artifacts = result.get("artifacts") or []
    if not artifacts:
        raise HTTPException(status_code=404, detail="No artifacts found for this task")

    temp_dir = DOWNLOAD_DIR / f"task_{task_id}_{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for item in artifacts:
        raw_path = item.get("path")
        if not raw_path:
            continue
        p = _resolve_to_path(raw_path)
        if p is None or not p.exists() or not p.is_file():
            continue
        target = temp_dir / p.name
        if target.exists():
            target = temp_dir / f"{target.stem}_{copied}{target.suffix}"
        shutil.copy2(p, target)
        copied += 1

    if copied == 0:
        raise HTTPException(status_code=404, detail="Task artifacts are unavailable")

    # Prefer result task folder name: result/<type>/<task_name>/...
    bundle_base_name = None
    for item in artifacts:
        raw_path = item.get("path")
        if not raw_path:
            continue
        p = _resolve_to_path(raw_path)
        if p is None:
            continue

        parts_lower = [seg.lower() for seg in p.parts]
        if "result" in parts_lower:
            idx = parts_lower.index("result")
            # Expected: result / <category> / <task_name> / ...
            if len(p.parts) >= idx + 3:
                candidate = p.parts[idx + 2]
                candidate = Path(candidate).stem
                if candidate:
                    bundle_base_name = candidate
                    break

    # Fallback to the first valid artifact path when no result path exists.
    if not bundle_base_name:
        for item in artifacts:
            raw_path = item.get("path")
            if not raw_path:
                continue
            p = _resolve_to_path(raw_path)
            if p is None:
                continue
            if p.is_file():
                candidate = p.parent.name if p.parent.name else p.stem
            else:
                candidate = p.name
            candidate = Path(candidate).stem
            if candidate:
                bundle_base_name = candidate
                break

    if not bundle_base_name:
        bundle_base_name = f"task_{task_id[:8]}"

    bundle_base_name = re.sub(r'[\\/:*?"<>|]', "_", bundle_base_name).strip(" .") or f"task_{task_id[:8]}"

    zip_name = f"task_{task_id}_artifacts_{uuid.uuid4().hex[:8]}"
    zip_file = shutil.make_archive(str(DOWNLOAD_DIR / zip_name), "zip", root_dir=str(temp_dir))
    media_type = "application/zip"
    return FileResponse(path=zip_file, media_type=media_type, filename=f"{bundle_base_name}.zip")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("frontend.main:app", host="127.0.0.1", port=8000, reload=False)
