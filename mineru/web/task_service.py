"""
Task orchestration utilities for the MinerU web experience.

The goal is to keep the FastAPI layer thin (SRP) by encapsulating
task lifecycle management, filesystem layout and result summarisation
in this module. This makes it easier to reuse the logic from different
web entrypoints (REST, WebSocket, etc.) while following KISS/YAGNI.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from mineru.cli.common import aio_do_parse, read_fn
from mineru.utils.config_reader import get_device

ENV_LOCK = asyncio.Lock()


class TaskStatus(str, Enum):
    """Lifecycle status for a parse task."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(slots=True)
class TaskParams:
    """Inference configuration captured for reproducibility."""

    backend: str
    parse_method: str
    formula_enable: bool
    table_enable: bool
    return_md: bool
    return_middle_json: bool
    return_model_output: bool
    return_content_list: bool
    return_images: bool
    return_html: bool = False
    return_docx: bool = False
    return_latex: bool = False
    start_page_id: int = 0
    end_page_id: int = 99999
    server_url: Optional[str] = None
    device_mode: Optional[str] = None
    virtual_vram: Optional[int] = None
    model_source: Optional[str] = None
    return_orig_pdf: bool = False


@dataclass(slots=True)
class TaskUpload:
    """Metadata about an uploaded source file."""

    original_name: str
    stored_name: str
    stored_path: Path
    language: str

    @property
    def stem(self) -> str:
        return Path(self.stored_name).stem


@dataclass(slots=True)
class TaskRecord:
    """Runtime state for a task."""

    task_id: str
    uploads: List[TaskUpload]
    params: TaskParams
    work_dir: Path
    artifacts_dir: Path
    logs_dir: Path
    status: TaskStatus = TaskStatus.QUEUED
    error: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=200))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise minimal fields for JSON responses."""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "backend": self.params.backend,
            "parse_method": self.params.parse_method,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "error": self.error,
        }


class TaskManager:
    """Coordinates task creation, execution and result summarisation."""

    def __init__(self) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()
        self._env_lock = ENV_LOCK
        self._listeners: Dict[str, List[asyncio.Queue[Dict[str, Any]]]] = defaultdict(list)

    async def create_task(
        self,
        task_id: str,
        uploads: List[TaskUpload],
        params: TaskParams,
        base_output: Path,
        config: Optional[Dict[str, Any]] = None,
    ) -> TaskRecord:
        """Register a new task and schedule execution."""
        config = config or {}
        work_dir = (base_output / "tasks" / task_id).resolve()
        artifacts_dir = work_dir / "artifacts"
        logs_dir = work_dir / "logs"

        artifacts_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        record = TaskRecord(
            task_id=task_id,
            uploads=uploads,
            params=params,
            work_dir=work_dir,
            artifacts_dir=artifacts_dir,
            logs_dir=logs_dir,
            config=config,
        )

        async with self._lock:
            self._tasks[task_id] = record
            self._log(record, f"task queued with {len(uploads)} file(s)")
            self._broadcast(
                task_id,
                {
                    "event": "status",
                    "task_id": task_id,
                    "status": record.status.value,
                    "timestamp": record.updated_at.isoformat(),
                },
            )

        loop = asyncio.get_running_loop()
        loop.create_task(self._run_task(record))

        return record

    async def retry_task(self, task_id: str) -> TaskRecord:
        async with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise KeyError(task_id)
            if record.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                raise RuntimeError("task is currently running or queued")

            record.status = TaskStatus.QUEUED
            record.error = None
            record.logs.clear()
            record.touch()

            self._log(record, "task requeued for retry")
            self._broadcast(
                task_id,
                {
                    "event": "status",
                    "task_id": task_id,
                    "status": record.status.value,
                    "timestamp": record.updated_at.isoformat(),
                },
            )

        loop = asyncio.get_running_loop()
        loop.create_task(self._run_task(record))
        return record

    async def _run_task(self, record: TaskRecord) -> None:
        """Execute the parse workflow in the background."""
        try:
            await self._update_status(record.task_id, TaskStatus.RUNNING, log_msg="task started")

            pdf_file_names = [upload.stem for upload in record.uploads]
            pdf_bytes_list = [read_fn(upload.stored_path) for upload in record.uploads]

            params = record.params
            lang_list = [upload.language for upload in record.uploads]
            if not lang_list:
                lang_list = ["ch"] * len(pdf_file_names)

            env_overrides = build_env_overrides(params, record.config)

            if env_overrides:
                async with self._env_lock:
                    with temporary_environ(env_overrides):
                        await aio_do_parse(
                            output_dir=str(record.artifacts_dir),
                            pdf_file_names=pdf_file_names,
                            pdf_bytes_list=pdf_bytes_list,
                            p_lang_list=lang_list,
                            backend=params.backend,
                            parse_method=params.parse_method,
                            formula_enable=params.formula_enable,
                            table_enable=params.table_enable,
                            server_url=params.server_url,
                            f_draw_layout_bbox=False,
                            f_draw_span_bbox=False,
                            f_dump_md=params.return_md,
                            f_dump_middle_json=params.return_middle_json,
                            f_dump_model_output=params.return_model_output,
                            f_dump_orig_pdf=params.return_orig_pdf,
                            f_dump_content_list=params.return_content_list,
                            f_dump_html=params.return_html,
                            f_dump_docx=params.return_docx,
                            f_dump_latex=params.return_latex,
                            start_page_id=params.start_page_id,
                            end_page_id=params.end_page_id,
                            **record.config,
                        )
            else:
                await aio_do_parse(
                    output_dir=str(record.artifacts_dir),
                    pdf_file_names=pdf_file_names,
                    pdf_bytes_list=pdf_bytes_list,
                    p_lang_list=lang_list,
                    backend=params.backend,
                    parse_method=params.parse_method,
                    formula_enable=params.formula_enable,
                    table_enable=params.table_enable,
                    server_url=params.server_url,
                    f_draw_layout_bbox=False,
                    f_draw_span_bbox=False,
                    f_dump_md=params.return_md,
                    f_dump_middle_json=params.return_middle_json,
                    f_dump_model_output=params.return_model_output,
                    f_dump_orig_pdf=params.return_orig_pdf,
                    f_dump_content_list=params.return_content_list,
                    f_dump_html=params.return_html,
                    f_dump_docx=params.return_docx,
                    f_dump_latex=params.return_latex,
                    start_page_id=params.start_page_id,
                    end_page_id=params.end_page_id,
                    **record.config,
                )

            await self._update_status(record.task_id, TaskStatus.SUCCESS, log_msg="task finished")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("task %s failed", record.task_id)
            await self._handle_failure(record.task_id, str(exc))

    async def _update_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        log_msg: Optional[str] = None,
    ) -> None:
        async with self._lock:
            record = self._tasks[task_id]
            record.status = status
            record.touch()
            if log_msg:
                self._log(record, log_msg)
            self._broadcast(
                task_id,
                {
                    "event": "status",
                    "task_id": task_id,
                    "status": status.value,
                    "timestamp": record.updated_at.isoformat(),
                },
            )

    async def _handle_failure(self, task_id: str, message: str) -> None:
        async with self._lock:
            record = self._tasks[task_id]
            record.status = TaskStatus.FAILED
            record.error = message
            record.touch()
            self._log(record, f"task failed: {message}")
            self._broadcast(
                task_id,
                {
                    "event": "error",
                    "task_id": task_id,
                    "message": message,
                    "timestamp": record.updated_at.isoformat(),
                },
            )

    def _log(self, record: TaskRecord, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        line = f"[{timestamp}] {message}"
        record.logs.append(line)
        log_path = record.logs_dir / "task.log"
        with log_path.open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")
        self._broadcast(
            record.task_id,
            {
                "event": "log",
                "task_id": record.task_id,
                "line": line,
            },
        )

    async def get_task(self, task_id: str) -> TaskRecord:
        async with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise KeyError(task_id)
            return record

    async def list_tasks(self) -> List[Dict[str, Any]]:
        """Return lightweight summaries for all tasks."""
        async with self._lock:
            return [record.to_dict() for record in self._tasks.values()]

    async def get_task_payload(
        self,
        task_id: str,
        *,
        include_content: bool = True,
    ) -> Dict[str, Any]:
        """Build a response payload with summaries and previews."""
        record = await self.get_task(task_id)

        result = record.to_dict()
        result["params"] = asdict(record.params)
        result["logs"] = list(record.logs)
        result["documents"] = self._collect_documents(
            record,
            include_content=include_content,
        )
        return result

    def _collect_documents(
        self,
        record: TaskRecord,
        *,
        include_content: bool,
    ) -> List[Dict[str, Any]]:
        documents: List[Dict[str, Any]] = []
        params = record.params
        for upload in record.uploads:
            parse_dir = (
                Path(record.artifacts_dir, upload.stem, params.parse_method)
                if params.backend.startswith("pipeline")
                else Path(record.artifacts_dir, upload.stem, "vlm")
            )
            doc_payload: Dict[str, Any] = {
                "name": upload.original_name,
                "directory": str(parse_dir.relative_to(record.work_dir)),
                "files": [],
            }

            if params.return_md:
                file_name = f"{upload.stem}.md"
                doc_payload["files"].append(
                    self._build_file_meta(record, parse_dir / file_name, "markdown")
                )
                if include_content:
                    doc_payload["markdown"] = self._read_text(parse_dir / file_name)

            if params.return_middle_json:
                file_name = f"{upload.stem}_middle.json"
                doc_payload["files"].append(
                    self._build_file_meta(record, parse_dir / file_name, "middle_json")
                )
                if include_content:
                    doc_payload["middle_json"] = self._read_json(parse_dir / file_name)

            if params.return_model_output:
                model_suffix = "_model.json" if params.backend.startswith("pipeline") else "_model_output.txt"
                file_name = f"{upload.stem}{model_suffix}"
                doc_payload["files"].append(
                    self._build_file_meta(record, parse_dir / file_name, "model_output")
                )
                if include_content:
                    doc_payload["model_output"] = self._read_text(parse_dir / file_name)

            if params.return_content_list:
                file_name = f"{upload.stem}_content_list.json"
                doc_payload["files"].append(
                    self._build_file_meta(record, parse_dir / file_name, "content_list")
                )
                if include_content:
                    doc_payload["content_list"] = self._read_json(parse_dir / file_name)

            if params.return_html:
                file_name = f"{upload.stem}.html"
                doc_payload["files"].append(
                    self._build_file_meta(record, parse_dir / file_name, "html")
                )
                if include_content:
                    doc_payload["html"] = self._read_text(parse_dir / file_name)

            if params.return_docx:
                file_name = f"{upload.stem}.docx"
                doc_payload["files"].append(
                    self._build_file_meta(record, parse_dir / file_name, "docx")
                )

            if params.return_latex:
                file_name = f"{upload.stem}_latex.zip"
                doc_payload["files"].append(
                    self._build_file_meta(record, parse_dir / file_name, "latex_package")
                )

            layout_pdf = parse_dir / f"{upload.stem}_layout.pdf"
            if layout_pdf.exists():
                doc_payload["files"].append(
                    self._build_file_meta(record, layout_pdf, "layout_pdf")
                )

            origin_pdf = parse_dir / f"{upload.stem}_origin.pdf"
            if origin_pdf.exists():
                doc_payload["files"].append(
                    self._build_file_meta(record, origin_pdf, "origin_pdf")
                )

            if params.return_images:
                images_dir = parse_dir / "images"
                image_entries = []
                if images_dir.exists():
                    for image_path in sorted(images_dir.glob("*.jpg")):
                        image_entries.append(
                            self._build_file_meta(record, image_path, "image")
                        )
                doc_payload["images"] = image_entries

            documents.append(doc_payload)
        return documents

    def _build_file_meta(
        self,
        record: TaskRecord,
        path: Path,
        kind: str,
    ) -> Dict[str, Any]:
        rel_path = path.relative_to(record.work_dir)
        return {
            "type": kind,
            "name": path.name,
            "path": str(rel_path).replace("\\", "/"),
            "exists": path.exists(),
        }

    @staticmethod
    def _read_text(path: Path) -> Optional[str]:
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except Exception:  # pragma: no cover - fallback in case of encoding issues
            logger.warning("failed to read text file %s", path)
            return None

    @staticmethod
    def _read_json(path: Path) -> Optional[Any]:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:  # pragma: no cover - fallback when JSON invalid
            logger.warning("failed to parse json file %s", path)
            return None

    async def resolve_artifact(self, task_id: str, relative_path: str) -> Path:
        """Return an absolute path to an artifact ensuring sandbox safety."""
        record = await self.get_task(task_id)
        candidate = (record.work_dir / relative_path).resolve()
        if not str(candidate).startswith(str(record.work_dir.resolve())):
            raise ValueError("invalid artifact path")
        return candidate

    async def add_listener(self, task_id: str) -> asyncio.Queue[Dict[str, Any]]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=200)
        async with self._lock:
            if task_id not in self._tasks:
                raise KeyError(task_id)
            self._listeners[task_id].append(queue)
        return queue

    async def remove_listener(self, task_id: str, queue: asyncio.Queue[Dict[str, Any]]) -> None:
        async with self._lock:
            listeners = self._listeners.get(task_id)
            if not listeners:
                return
            if queue in listeners:
                listeners.remove(queue)
            if not listeners:
                self._listeners.pop(task_id, None)

    def _broadcast(self, task_id: str, message: Dict[str, Any]) -> None:
        listeners = self._listeners.get(task_id)
        if not listeners:
            return

        stale: List[asyncio.Queue[Dict[str, Any]]] = []
        for queue in list(listeners):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    logger.warning("listener queue still full for task %s", task_id)
            except RuntimeError:
                stale.append(queue)

        if stale:
            for queue in stale:
                if queue in listeners:
                    listeners.remove(queue)
            if not listeners:
                self._listeners.pop(task_id, None)


@contextmanager
def temporary_environ(overrides: Dict[str, str]):
    if not overrides:
        yield
        return
    original: Dict[str, Optional[str]] = {}
    try:
        for key, value in overrides.items():
            original[key] = os.environ.get(key)
            os.environ[key] = value
        yield
    finally:
        for key, previous in original.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def build_env_overrides(params: TaskParams, config: Dict[str, Any]) -> Dict[str, str]:
    overrides: Dict[str, str] = {}

    device_mode = params.device_mode
    if device_mode is None:
        device_mode = config.get("device_mode") or config.get("device")
    if device_mode:
        device_value = get_device() if str(device_mode).lower() == "auto" else str(device_mode)
        overrides["MINERU_DEVICE_MODE"] = device_value

    virtual_vram = params.virtual_vram
    if virtual_vram is None:
        virtual_vram = config.get("virtual_vram")
    if virtual_vram is None:
        virtual_vram = config.get("virtual_vram_size")
    if virtual_vram is not None:
        overrides["MINERU_VIRTUAL_VRAM_SIZE"] = str(virtual_vram)

    model_source = params.model_source
    if model_source is None:
        model_source = config.get("model_source")
    if model_source:
        overrides["MINERU_MODEL_SOURCE"] = str(model_source)

    return overrides


__all__ = [
    "TaskManager",
    "TaskParams",
    "TaskRecord",
    "TaskStatus",
    "TaskUpload",
    "ENV_LOCK",
    "temporary_environ",
    "build_env_overrides",
]
