import uuid
import os
import re
import asyncio
import click
import glob
import tempfile
import uvicorn
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from typing import Any, Dict, List, Optional, Mapping
from loguru import logger
from base64 import b64encode
from ipaddress import ip_address

from mineru.cli.common import aio_do_parse, read_fn, pdf_suffixes, image_suffixes
from mineru.utils.cli_parser import arg_parse
from mineru.utils.guess_suffix_or_lang import guess_suffix_by_path
from mineru.version import __version__
from mineru.web.task_service import (
    ENV_LOCK,
    TaskManager,
    TaskParams,
    TaskUpload,
    build_env_overrides,
    temporary_environ,
)

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)
_cors_origins = os.getenv("MINERU_CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
if _cors_origins.strip() == "*":
    allow_origins = ["*"]
else:
    allow_origins = [origin.strip() for origin in _cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
task_manager = TaskManager()


def sanitize_filename(filename: str) -> str:
    """
    格式化压缩文件的文件名
    移除路径遍历字符, 保留 Unicode 字母、数字、._- 
    禁止隐藏文件
    """
    sanitized = re.sub(r'[/\\\.]{2,}|[/\\]', '', filename)
    sanitized = re.sub(r'[^\w.-]', '_', sanitized, flags=re.UNICODE)
    if sanitized.startswith('.'):
        sanitized = '_' + sanitized[1:]
    return sanitized or 'unnamed'

def cleanup_file(file_path: str) -> None:
    """清理临时 zip 文件"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logger.warning(f"fail clean file {file_path}: {e}")

def encode_image(image_path: str) -> str:
    """Encode image using base64"""
    with open(image_path, "rb") as f:
        return b64encode(f.read()).decode()


def get_infer_result(file_suffix_identifier: str, pdf_name: str, parse_dir: str) -> Optional[str]:
    """从结果文件中读取推理结果"""
    result_file_path = os.path.join(parse_dir, f"{pdf_name}{file_suffix_identifier}")
    if os.path.exists(result_file_path):
        with open(result_file_path, "r", encoding="utf-8") as fp:
            return fp.read()
    return None


def _normalise_lang_list(lang_list: List[str], count: int) -> List[str]:
    if count == 0:
        return []
    if not lang_list:
        return ["ch"] * count
    if len(lang_list) >= count:
        return lang_list[:count]
    return lang_list + [lang_list[0]] * (count - len(lang_list))


@dataclass
class AdvancedSettings:
    backend: str
    parse_method: str
    model_source: Optional[str]
    device_mode: Optional[str]
    virtual_vram: Optional[int]
    server_url: Optional[str]


def _extract_client_ip(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        return None
    for part in parts:
        try:
            ip_obj = ip_address(part)
            if not (ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved or ip_obj.is_unspecified):
                return part
        except ValueError:
            continue
    return parts[0]


def _first_hop_ip(headers: Mapping[str, str], client_host: Optional[str]) -> str:
    for raw in (
        headers.get("x-forwarded-for"),
        headers.get("cf-connecting-ip"),
        headers.get("true-client-ip"),
        headers.get("x-real-ip"),
    ):
        candidate = _extract_client_ip(raw)
        if candidate:
            return candidate
    candidate = _extract_client_ip(client_host)
    if candidate:
        return candidate
    return "unknown"


def _sanitize_scope(raw: str) -> str:
    scope = raw.strip() or "unknown"
    scope = re.sub(r"[^0-9A-Za-z_.-]", "_", scope)
    return scope[:64]


def _resolve_scope_and_persistence(
    headers: Mapping[str, str],
    client_host: Optional[str],
    session_id: Optional[str],
    user_id: Optional[str],
) -> tuple[str, bool]:
    if user_id:
        return f"user_{_sanitize_scope(user_id)}", True
    if session_id:
        return f"sess_{_sanitize_scope(session_id)}", False
    ip_value = _first_hop_ip(headers, client_host)
    return f"ip_{_sanitize_scope(ip_value)}", False


def _resolve_request_scope(request: Request) -> tuple[str, bool]:
    session_id = request.headers.get("x-mineru-session") or request.query_params.get("session")
    user_id = request.headers.get("x-mineru-user") or request.query_params.get("user")
    return _resolve_scope_and_persistence(
        request.headers,
        request.client.host if request.client else None,
        session_id,
        user_id,
    )


def _resolve_user_scope(request: Request) -> str:
    scope, _ = _resolve_request_scope(request)
    return scope


def _resolve_scope_from_websocket(websocket: WebSocket) -> tuple[str, bool]:
    session_id = websocket.query_params.get("session") or websocket.headers.get("x-mineru-session")
    user_id = websocket.query_params.get("user") or websocket.headers.get("x-mineru-user")
    return _resolve_scope_and_persistence(
        websocket.headers,
        websocket.client.host if websocket.client else None,
        session_id,
        user_id,
    )


def _resolve_virtual_vram(config: Dict[str, Any]) -> Optional[int]:
    value = config.get("virtual_vram")
    if value is None:
        value = config.get("virtual_vram_size")
    if value in ("", None):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_advanced_settings(config: Dict[str, Any]) -> AdvancedSettings:
    backend = str(config.get("backend") or config.get("engine") or "vlm-http-client")
    parse_method = config.get("parse_method")
    if not parse_method:
        parse_method = "auto" if backend == "pipeline" else "vlm"
    model_source = config.get("model_source")
    device_mode = config.get("device_mode") or config.get("device")
    virtual_vram = _resolve_virtual_vram(config)
    server_url = config.get("server_url") or config.get("vlm_server_url")
    if not server_url and backend.endswith("http-client"):
        server_url = "http://127.0.0.1:30000"

    return AdvancedSettings(
        backend=backend,
        parse_method=str(parse_method),
        model_source=str(model_source) if model_source is not None else None,
        device_mode=str(device_mode) if device_mode is not None else None,
        virtual_vram=virtual_vram,
        server_url=str(server_url) if server_url is not None else None,
    )


async def _store_task_uploads(
    task_id: str,
    files: List[UploadFile],
    user_scope: str,
    base_output: Path,
    lang_list: List[str],
) -> List[TaskUpload]:
    uploads_dir = (base_output / "tasks" / user_scope / task_id / "uploads").resolve()
    uploads_dir.mkdir(parents=True, exist_ok=True)

    uploads: List[TaskUpload] = []
    for index, file in enumerate(files):
        original_name = os.path.basename(file.filename) if file.filename else f"document-{index}.pdf"
        base_name = sanitize_filename(original_name)
        stem, suffix = os.path.splitext(base_name)
        stored_name = base_name if suffix else f"{base_name}.pdf"

        target_path = uploads_dir / stored_name
        counter = 1
        while target_path.exists():
            target_path = uploads_dir / f"{stem}_{counter}{suffix}"
            stored_name = target_path.name
            counter += 1

        content = await file.read()
        with open(target_path, "wb") as fp:
            fp.write(content)
        await file.close()

        language = lang_list[index] if index < len(lang_list) else lang_list[0] if lang_list else "ch"

        uploads.append(
            TaskUpload(
                original_name=original_name,
                stored_name=stored_name,
                stored_path=target_path,
                language=language,
            )
        )

    return uploads


@app.get("/tasks")
async def list_tasks(request: Request):
    scope = _resolve_user_scope(request)
    summaries = await task_manager.list_tasks(scope=scope)
    return {"tasks": summaries}


@app.get("/settings")
async def read_settings() -> Dict[str, Any]:
    config = getattr(app.state, "config", {})
    advanced = _resolve_advanced_settings(config)
    return {
        **asdict(advanced),
        "default_language": config.get("language", "ch"),
    }


@app.post("/tasks", status_code=202)
async def create_task(
        request: Request,
        files: List[UploadFile] = File(...),
        output_dir: str = Form("./output"),
        lang_list: List[str] = Form(["ch"]),
        backend_form: str = Form("pipeline"),
        parse_method_form: str = Form("auto"),
        formula_enable: bool = Form(True),
        table_enable: bool = Form(True),
        server_url_form: Optional[str] = Form(None),
        return_md: bool = Form(True),
        return_middle_json: bool = Form(False),
        return_model_output: bool = Form(False),
        return_content_list: bool = Form(False),
        return_images: bool = Form(False),
        return_orig_pdf: bool = Form(True),
        return_html: bool = Form(False),
        return_docx: bool = Form(False),
        return_latex: bool = Form(False),
        start_page_id: int = Form(0),
        end_page_id: int = Form(99999),
        device_mode_form: Optional[str] = Form(None),
        virtual_vram_form: Optional[int] = Form(None),
        model_source_form: Optional[str] = Form(None),
) -> Dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="no files provided")

    config = getattr(app.state, "config", {})
    advanced = _resolve_advanced_settings(config)
    task_config = dict(config)
    task_config.pop("server_url", None)
    if advanced.device_mode:
        task_config["device_mode"] = advanced.device_mode
    if advanced.virtual_vram is not None:
        task_config["virtual_vram"] = advanced.virtual_vram
    if advanced.model_source:
        task_config["model_source"] = advanced.model_source

    task_id = uuid.uuid4().hex
    base_output = Path(output_dir)
    base_output.mkdir(parents=True, exist_ok=True)

    user_scope, is_persistent = _resolve_request_scope(request)
    normalised_lang_list = _normalise_lang_list(lang_list, len(files))
    uploads = await _store_task_uploads(task_id, files, user_scope, base_output, normalised_lang_list)
    task_config.setdefault("user_scope", user_scope)

    params = TaskParams(
        backend=advanced.backend,
        parse_method=advanced.parse_method,
        formula_enable=formula_enable,
        table_enable=table_enable,
        return_md=return_md,
        return_middle_json=return_middle_json,
        return_model_output=return_model_output,
        return_content_list=return_content_list,
        return_images=return_images,
        return_orig_pdf=return_orig_pdf,
        return_html=return_html,
        return_docx=return_docx,
        return_latex=return_latex,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
        server_url=advanced.server_url,
        device_mode=advanced.device_mode,
        virtual_vram=advanced.virtual_vram,
        model_source=advanced.model_source,
    )

    await task_manager.create_task(
        task_id=task_id,
        uploads=uploads,
        user_scope=user_scope,
        params=params,
        base_output=base_output,
        config=task_config,
        persistent=is_persistent,
    )
    payload = await task_manager.get_task_payload(task_id, include_content=False, scope=user_scope)
    return payload


@app.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: str, include_content: bool = True):
    scope = _resolve_user_scope(request)
    try:
        payload = await task_manager.get_task_payload(task_id, include_content=include_content, scope=scope)
    except KeyError:
        raise HTTPException(status_code=404, detail="task not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="forbidden")
    return payload


ALLOWED_ORIGINS = allow_origins

def apply_cors_headers(response, request: Request):
    origin = request.headers.get("origin")
    if origin and ("*" in ALLOWED_ORIGINS or origin in ALLOWED_ORIGINS):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Expose-Headers"] = (
            "Accept-Ranges, Content-Length, Content-Range, Content-Disposition"
        )
    return response


@app.api_route("/tasks/{task_id}/artifacts/{artifact_path:path}", methods=["GET", "HEAD"])
async def download_artifact(request: Request, task_id: str, artifact_path: str):
    scope = _resolve_user_scope(request)
    try:
        resolved = await task_manager.resolve_artifact(task_id, artifact_path, scope=scope)
    except KeyError:
        raise HTTPException(status_code=404, detail="task not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid artifact path")
    except PermissionError:
        raise HTTPException(status_code=403, detail="forbidden")

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="file not found")
    response = FileResponse(resolved)
    return apply_cors_headers(response, request)


@app.get("/tasks/{task_id}/artifact-bytes")
async def download_artifact_bytes(
        request: Request,
        task_id: str,
        path: str = Query(..., description="Artifact relative path within task workdir"),
):
    scope = _resolve_user_scope(request)
    try:
        resolved = await task_manager.resolve_artifact(task_id, path, scope=scope)
    except KeyError:
        raise HTTPException(status_code=404, detail="task not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid artifact path")
    except PermissionError:
        raise HTTPException(status_code=403, detail="forbidden")

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="file not found")

    def iter_file():
        with resolved.open("rb") as handle:
            while True:
                chunk = handle.read(8192)
                if not chunk:
                    break
                yield chunk

    response = StreamingResponse(iter_file(), media_type="application/octet-stream")
    response.headers["Content-Disposition"] = 'inline; filename="artifact-preview"'
    return apply_cors_headers(response, request)


@app.websocket("/ws/tasks/{task_id}")
async def task_stream(websocket: WebSocket, task_id: str):
    await websocket.accept()
    scope, _ = _resolve_scope_from_websocket(websocket)
    try:
        snapshot = await task_manager.get_task_payload(task_id, include_content=True, scope=scope)
    except KeyError:
        await websocket.close(code=4404)
        return
    except PermissionError:
        await websocket.close(code=4403)
        return

    await websocket.send_json({"event": "snapshot", "task": snapshot})

    try:
        queue = await task_manager.add_listener(task_id, scope=scope)
    except KeyError:
        await websocket.close(code=4404)
        return
    except PermissionError:
        await websocket.close(code=4403)
        return

    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - safety net
        logger.warning(f"websocket send failed for task {task_id}: {exc}")
    finally:
        await task_manager.remove_listener(task_id, queue)


@app.post("/tasks/{task_id}/retry", status_code=202)
async def retry_task(request: Request, task_id: str):
    scope = _resolve_user_scope(request)
    try:
        await task_manager.retry_task(task_id, scope=scope)
        payload = await task_manager.get_task_payload(task_id, include_content=False, scope=scope)
        return payload
    except KeyError:
        raise HTTPException(status_code=404, detail="task not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError:
        raise HTTPException(status_code=403, detail="forbidden")


@app.post(path="/file_parse",)
async def parse_pdf(
        files: List[UploadFile] = File(...),
        output_dir: str = Form("./output"),
        lang_list: List[str] = Form(["ch"]),
        backend: str = Form("pipeline"),
        parse_method: str = Form("auto"),
        formula_enable: bool = Form(True),
        table_enable: bool = Form(True),
        server_url: Optional[str] = Form(None),
        return_md: bool = Form(True),
        return_middle_json: bool = Form(False),
        return_model_output: bool = Form(False),
        return_content_list: bool = Form(False),
        return_images: bool = Form(False),
        return_orig_pdf: bool = Form(True),
        return_html: bool = Form(False),
        return_docx: bool = Form(False),
        return_latex: bool = Form(False),
        response_format_zip: bool = Form(False),
        start_page_id: int = Form(0),
        end_page_id: int = Form(99999),
        device_mode: Optional[str] = Form(None),
        virtual_vram: Optional[int] = Form(None),
        model_source: Optional[str] = Form(None),
):

    # 获取命令行配置参数
    config = getattr(app.state, "config", {})
    call_config = dict(config)
    if device_mode is not None:
        call_config["device_mode"] = device_mode
    if virtual_vram is not None:
        call_config["virtual_vram"] = virtual_vram
    if model_source is not None:
        call_config["model_source"] = model_source

    try:
        # 创建唯一的输出目录
        unique_dir = os.path.join(output_dir, str(uuid.uuid4()))
        os.makedirs(unique_dir, exist_ok=True)

        # 处理上传的PDF文件
        pdf_file_names = []
        pdf_bytes_list = []

        for file in files:
            content = await file.read()
            file_path = Path(file.filename)

            # 创建临时文件
            temp_path = Path(unique_dir) / file_path.name
            with open(temp_path, "wb") as f:
                f.write(content)

            # 如果是图像文件或PDF，使用read_fn处理
            file_suffix = guess_suffix_by_path(temp_path)
            if file_suffix in pdf_suffixes + image_suffixes:
                try:
                    pdf_bytes = read_fn(temp_path)
                    pdf_bytes_list.append(pdf_bytes)
                    pdf_file_names.append(file_path.stem)
                    os.remove(temp_path)  # 删除临时文件
                except Exception as e:
                    return JSONResponse(
                        status_code=400,
                        content={"error": f"Failed to load file: {str(e)}"}
                    )
            else:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Unsupported file type: {file_suffix}"}
                )


        # 设置语言列表，确保与文件数量一致
        actual_lang_list = lang_list
        if len(actual_lang_list) != len(pdf_file_names):
            # 如果语言列表长度不匹配，使用第一个语言或默认"ch"
            actual_lang_list = [actual_lang_list[0] if actual_lang_list else "ch"] * len(pdf_file_names)

        # 调用异步处理函数
        env_params = TaskParams(
            backend=backend,
            parse_method=parse_method,
            formula_enable=formula_enable,
            table_enable=table_enable,
            return_md=return_md,
            return_middle_json=return_middle_json,
            return_model_output=return_model_output,
            return_content_list=return_content_list,
            return_images=return_images,
            return_orig_pdf=return_orig_pdf,
            return_html=return_html,
            return_docx=return_docx,
            return_latex=return_latex,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
            server_url=server_url,
            device_mode=device_mode,
            virtual_vram=virtual_vram,
            model_source=model_source,
        )
        env_overrides = build_env_overrides(env_params, call_config)
        parse_kwargs = dict(
            output_dir=unique_dir,
            pdf_file_names=pdf_file_names,
            pdf_bytes_list=pdf_bytes_list,
            p_lang_list=actual_lang_list,
            backend=backend,
            parse_method=parse_method,
            formula_enable=formula_enable,
            table_enable=table_enable,
            server_url=server_url,
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_dump_md=return_md,
            f_dump_middle_json=return_middle_json,
            f_dump_model_output=return_model_output,
            f_dump_orig_pdf=return_orig_pdf,
            f_dump_content_list=return_content_list,
            f_dump_html=return_html,
            f_dump_docx=return_docx,
            f_dump_latex=return_latex,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
        )
        parse_kwargs.update(call_config)

        if env_overrides:
            async with ENV_LOCK:
                with temporary_environ(env_overrides):
                    await aio_do_parse(**parse_kwargs)
        else:
            await aio_do_parse(**parse_kwargs)

        # 根据 response_format_zip 决定返回类型
        if response_format_zip:
            zip_fd, zip_path = tempfile.mkstemp(suffix=".zip", prefix="mineru_results_")
            os.close(zip_fd) 
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for pdf_name in pdf_file_names:
                    safe_pdf_name = sanitize_filename(pdf_name)
                    if backend.startswith("pipeline"):
                        parse_dir = os.path.join(unique_dir, pdf_name, parse_method)
                    else:
                        parse_dir = os.path.join(unique_dir, pdf_name, "vlm")

                    if not os.path.exists(parse_dir):
                        continue

                    # 写入文本类结果
                    if return_md:
                        path = os.path.join(parse_dir, f"{pdf_name}.md")
                        if os.path.exists(path):
                            zf.write(path, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}.md"))

                    if return_middle_json:
                        path = os.path.join(parse_dir, f"{pdf_name}_middle.json")
                        if os.path.exists(path):
                            zf.write(path, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}_middle.json"))

                    if return_model_output:
                        if backend.startswith("pipeline"):
                            path = os.path.join(parse_dir, f"{pdf_name}_model.json")
                        else:
                            path = os.path.join(parse_dir, f"{pdf_name}_model_output.txt")
                        if os.path.exists(path): 
                            zf.write(path, arcname=os.path.join(safe_pdf_name, os.path.basename(path)))

                    if return_content_list:
                        path = os.path.join(parse_dir, f"{pdf_name}_content_list.json")
                        if os.path.exists(path):
                            zf.write(path, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}_content_list.json"))

                    if return_html:
                        path = os.path.join(parse_dir, f"{pdf_name}.html")
                        if os.path.exists(path):
                            zf.write(path, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}.html"))

                    if return_docx:
                        path = os.path.join(parse_dir, f"{pdf_name}.docx")
                        if os.path.exists(path):
                            zf.write(path, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}.docx"))

                    if return_latex:
                        path = os.path.join(parse_dir, f"{pdf_name}_latex.zip")
                        if os.path.exists(path):
                            zf.write(path, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}_latex.zip"))

                    # 写入图片
                    if return_images:
                        images_dir = os.path.join(parse_dir, "images")
                        image_paths = glob.glob(os.path.join(glob.escape(images_dir), "*.jpg"))
                        for image_path in image_paths:
                            zf.write(image_path, arcname=os.path.join(safe_pdf_name, "images", os.path.basename(image_path)))

            return FileResponse(
                path=zip_path,
                media_type="application/zip",
                filename="results.zip",
                background=BackgroundTask(cleanup_file, zip_path)
            )
        else:
            # 构建 JSON 结果
            result_dict = {}
            for pdf_name in pdf_file_names:
                result_dict[pdf_name] = {}
                data = result_dict[pdf_name]

                if backend.startswith("pipeline"):
                    parse_dir = os.path.join(unique_dir, pdf_name, parse_method)
                else:
                    parse_dir = os.path.join(unique_dir, pdf_name, "vlm")

                if os.path.exists(parse_dir):
                    if return_md:
                        data["md_content"] = get_infer_result(".md", pdf_name, parse_dir)
                    if return_middle_json:
                        data["middle_json"] = get_infer_result("_middle.json", pdf_name, parse_dir)
                    if return_model_output:
                        if backend.startswith("pipeline"):
                            data["model_output"] = get_infer_result("_model.json", pdf_name, parse_dir)
                        else:
                            data["model_output"] = get_infer_result("_model_output.txt", pdf_name, parse_dir)
                    if return_content_list:
                        data["content_list"] = get_infer_result("_content_list.json", pdf_name, parse_dir)
                    if return_images:
                        images_dir = os.path.join(parse_dir, "images")
                        safe_pattern = os.path.join(glob.escape(images_dir), "*.jpg")
                        image_paths = glob.glob(safe_pattern)
                        data["images"] = {
                            os.path.basename(
                                image_path
                            ): f"data:image/jpeg;base64,{encode_image(image_path)}"
                            for image_path in image_paths
                        }

            return JSONResponse(
                status_code=200,
                content={
                    "backend": backend,
                    "version": __version__,
                    "results": result_dict
                }
            )
    except Exception as e:
        logger.exception(e)
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to process file: {str(e)}"}
        )


@click.command(context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.pass_context
@click.option('--host', default='127.0.0.1', help='Server host (default: 127.0.0.1)')
@click.option('--port', default=8000, type=int, help='Server port (default: 8000)')
@click.option('--reload', is_flag=True, help='Enable auto-reload (development mode)')
def main(ctx, host, port, reload, **kwargs):

    kwargs.update(arg_parse(ctx))

    # 将配置参数存储到应用状态中
    app.state.config = kwargs

    """启动MinerU FastAPI服务器的命令行入口"""
    print(f"Start MinerU FastAPI Service: http://{host}:{port}")
    print("The API documentation can be accessed at the following address:")
    print(f"- Swagger UI: http://{host}:{port}/docs")
    print(f"- ReDoc: http://{host}:{port}/redoc")

    uvicorn.run(
        "mineru.cli.fast_api:app",
        host=host,
        port=port,
        reload=reload
    )


if __name__ == "__main__":
    main()
