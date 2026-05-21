#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DolphinScheduler API 启动脚本
支持：基础启动、自定义参数、单任务执行等场景

作者：陈江川
日期：2026-03-17
版本：v1.1
"""

import io
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import auto_load_env  # noqa: F401
from config.config import DS_CONFIG


def _normalize_base_url(base_url: Optional[str]) -> str:
    return (base_url or DS_CONFIG["base_url"]).rstrip("/")


def _normalize_code(value: Any) -> str:
    return str(value or "").strip()


class DolphinSchedulerClient:
    """DolphinScheduler API 客户端"""

    def __init__(self, base_url: str = None, token: str = None):
        self.base_url = _normalize_base_url(base_url)
        self.token = token or os.environ.get("DS_TOKEN", DS_CONFIG.get("token", ""))
        self.headers = {"token": self.token}
        self.default_config = {
            "environment_code": DS_CONFIG.get("environment_code", "154818922491872"),
            "tenant_code": DS_CONFIG.get("tenant_code", "dolphinscheduler"),
            "worker_group": "default",
            "failure_strategy": "CONTINUE",
            "warning_type": "NONE",
            "priority": "MEDIUM",
            "run_mode": "RUN_MODE_SERIAL",
            "exec_type": "START_PROCESS",
            "dry_run": "0",
            "task_depend_type": "TASK_POST",
            "api_mode": DS_CONFIG.get("api_mode", "auto"),
            "start_endpoint": DS_CONFIG.get("start_endpoint", "auto"),
            "start_code_field": DS_CONFIG.get("start_code_field", "auto"),
            "definition_endpoint_style": DS_CONFIG.get("definition_endpoint_style", "auto"),
            "instance_endpoint_style": DS_CONFIG.get("instance_endpoint_style", "auto"),
        }

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        json_body: bool = False,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        headers = dict(self.headers)
        payload = None
        if data is not None:
            if json_body:
                payload = json.dumps(data).encode("utf-8")
                headers["Content-Type"] = "application/json"
            else:
                encoded = {}
                for key, value in data.items():
                    if value is None:
                        continue
                    encoded[key] = value
                payload = urlencode(encoded).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc)) from exc

        stripped = text.lstrip()
        if not stripped:
            raise RuntimeError("empty response")
        if stripped[0] not in "[{":
            snippet = " ".join(stripped[:120].split())
            raise RuntimeError(f"non-json response: {snippet}")

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            snippet = " ".join(stripped[:120].split())
            raise RuntimeError(f"invalid json response: {snippet}") from exc

    def _definition_detail_endpoints(self, project_code: str, workflow_code: str) -> List[str]:
        preferred = self.default_config["definition_endpoint_style"]
        if preferred == "workflow-definition":
            return [
                f"/projects/{project_code}/workflow-definition/{workflow_code}",
                f"/projects/{project_code}/process-definition/{workflow_code}",
                f"/v2/workflows/{workflow_code}",
            ]
        if preferred == "process-definition":
            return [
                f"/projects/{project_code}/process-definition/{workflow_code}",
                f"/projects/{project_code}/workflow-definition/{workflow_code}",
                f"/v2/workflows/{workflow_code}",
            ]
        return [
            f"/projects/{project_code}/workflow-definition/{workflow_code}",
            f"/projects/{project_code}/process-definition/{workflow_code}",
            f"/v2/workflows/{workflow_code}",
        ]

    def _definition_list_endpoints(self, project_code: str, page_no: int, page_size: int) -> List[str]:
        preferred = self.default_config["definition_endpoint_style"]
        workflow_page = f"/projects/{project_code}/workflow-definition?pageNo={page_no}&pageSize={page_size}"
        process_page = f"/projects/{project_code}/process-definition?pageNo={page_no}&pageSize={page_size}"
        workflow_query = f"/projects/{project_code}/workflow-definition/query-workflow-definition-list"
        process_query = f"/projects/{project_code}/process-definition/query-process-definition-list"
        v2_query = f"/v2/workflows?pageNo={page_no}&pageSize={page_size}"

        if preferred == "workflow-definition":
            return [workflow_page, workflow_query, process_page, process_query, v2_query]
        if preferred == "process-definition":
            return [process_page, process_query, workflow_page, workflow_query, v2_query]
        return [workflow_page, process_page, workflow_query, process_query, v2_query]

    def _instance_list_paths(self, project_code: str, state_type: Optional[str], page_no: int, page_size: int) -> List[str]:
        suffix = f"?pageNo={page_no}&pageSize={page_size}"
        if state_type:
            suffix += f"&stateType={state_type}"
        preferred = self.default_config["instance_endpoint_style"]
        workflow_path = f"/projects/{project_code}/workflow-instances{suffix}"
        process_path = f"/projects/{project_code}/process-instances{suffix}"
        if preferred == "workflow-instances":
            return [workflow_path, process_path]
        if preferred == "process-instances":
            return [process_path, workflow_path]
        return [workflow_path, process_path]

    def _instance_detail_paths(self, project_code: str, instance_id: Any) -> List[str]:
        preferred = self.default_config["instance_endpoint_style"]
        workflow_path = f"/projects/{project_code}/workflow-instances/{instance_id}"
        process_path = f"/projects/{project_code}/process-instances/{instance_id}"
        if preferred == "workflow-instances":
            return [workflow_path, process_path]
        if preferred == "process-instances":
            return [process_path, workflow_path]
        return [workflow_path, process_path]

    def _start_attempts(self) -> List[Tuple[str, str]]:
        endpoint = self.default_config["start_endpoint"]
        code_field = self.default_config["start_code_field"]
        api_mode = self.default_config["api_mode"]

        if endpoint != "auto" or code_field != "auto":
            selected_endpoint = endpoint if endpoint != "auto" else "start-process-instance"
            selected_field = code_field if code_field != "auto" else "processDefinitionCode"
            attempts = [(selected_endpoint, selected_field)]
            if selected_endpoint == "start-process-instance":
                attempts.append(("start-workflow-instance", "workflowDefinitionCode"))
            elif selected_endpoint == "start-workflow-instance":
                attempts.append(("start-process-instance", "processDefinitionCode"))
            return attempts

        if api_mode == "workflow_v1":
            return [("start-workflow-instance", "workflowDefinitionCode")]
        if api_mode == "process_v2":
            return [("start-process-instance", "processDefinitionCode")]

        return [
            ("start-process-instance", "processDefinitionCode"),
            ("start-workflow-instance", "workflowDefinitionCode"),
        ]

    def _coerce_list_result(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = result.get("data", [])
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("totalList", []) or data.get("records", []) or data.get("list", [])
        return []

    def start_workflow(
        self,
        project_code: str,
        process_code: str,
        custom_params: Optional[Dict[str, Any]] = None,
        task_code: Optional[str] = None,
        task_depend_type: str = "TASK_POST",
        environment_code: Optional[str] = None,
        tenant_code: Optional[str] = None,
        schedule_time: str = "",
    ) -> Dict[str, Any]:
        custom_payload = json.dumps(custom_params) if custom_params else None
        last_error = ""

        for endpoint, code_field in self._start_attempts():
            body = {
                "failureStrategy": self.default_config["failure_strategy"],
                "warningType": self.default_config["warning_type"],
                "warningGroupId": "0",
                "processInstancePriority": self.default_config["priority"],
                "workerGroup": self.default_config["worker_group"],
                "environmentCode": environment_code or self.default_config["environment_code"],
                "tenantCode": tenant_code or self.default_config["tenant_code"],
                "taskDependType": task_depend_type,
                "runMode": self.default_config["run_mode"],
                "execType": self.default_config["exec_type"],
                "dryRun": self.default_config["dry_run"],
                "scheduleTime": schedule_time if endpoint == "start-process-instance" else (
                    schedule_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ),
                code_field: process_code,
            }
            if custom_payload is not None:
                body["startParams"] = custom_payload
            if task_code:
                body["startNodeList"] = task_code

            try:
                result = self._request_json(
                    f"/projects/{project_code}/executors/{endpoint}",
                    method="POST",
                    data=body,
                )
            except RuntimeError as exc:
                last_error = str(exc)
                continue

            if result.get("code") == 0:
                instance_id = result.get("data")
                if isinstance(instance_id, list):
                    instance_id = instance_id[0] if instance_id else None
                return {
                    "success": True,
                    "instance_id": instance_id,
                    "message": "success",
                    "project_code": project_code,
                    "process_code": process_code,
                    "task_code": task_code,
                    "custom_params": custom_params,
                    "endpoint": endpoint,
                    "code_field": code_field,
                }

            last_error = result.get("msg", "Unknown error")

        return {
            "success": False,
            "error_code": "NETWORK_ERROR" if last_error.startswith("HTTP") else "API_ERROR",
            "error_message": last_error or "Unknown error",
            "project_code": project_code,
            "process_code": process_code,
        }

    def get_workflow_info(self, project_code: str, process_code: str) -> Dict[str, Any]:
        last_error = ""
        for path in self._definition_detail_endpoints(project_code, process_code):
            try:
                result = self._request_json(path, timeout=30)
            except RuntimeError as exc:
                last_error = str(exc)
                continue

            if result.get("code") == 0:
                return {"success": True, "data": result.get("data", {})}
            last_error = result.get("msg", "Unknown error")

        return {
            "success": False,
            "error_code": "API_ERROR",
            "error_message": last_error or "Unknown error",
        }

    def get_workflows_list(self, project_code: str) -> Dict[str, Any]:
        page_size = 100
        last_error = ""

        for path in self._definition_list_endpoints(project_code, page_no=1, page_size=page_size):
            if "pageNo=" not in path and "/v2/workflows" not in path:
                try:
                    result = self._request_json(path, timeout=30)
                except RuntimeError as exc:
                    last_error = str(exc)
                    continue

                if result.get("code") == 0:
                    data = self._coerce_list_result(result)
                    if data:
                        return {"success": True, "data": data}
                last_error = result.get("msg", "Unknown error")
                continue

            merged: List[Dict[str, Any]] = []
            page_no = 1
            total_pages = 1
            while page_no <= total_pages:
                current_path = path.replace("pageNo=1", f"pageNo={page_no}")
                try:
                    result = self._request_json(current_path, timeout=30)
                except RuntimeError as exc:
                    last_error = str(exc)
                    merged = []
                    break

                if result.get("code") != 0:
                    last_error = result.get("msg", "Unknown error")
                    merged = []
                    break

                data = result.get("data", {})
                if isinstance(data, dict):
                    merged.extend(data.get("totalList", []) or data.get("records", []))
                    total_pages = data.get("totalPage") or 1
                elif isinstance(data, list):
                    merged.extend(data)
                    total_pages = 1
                page_no += 1

            if merged:
                return {"success": True, "data": merged}

        return {
            "success": False,
            "error_code": "API_ERROR",
            "error_message": last_error or "Unknown error",
        }

    def get_workflow_instances(
        self,
        project_code: str,
        state_type: str = "RUNNING_EXECUTION",
        page_no: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        last_error = ""
        for path in self._instance_list_paths(project_code, state_type, page_no, page_size):
            try:
                result = self._request_json(path, timeout=30)
            except RuntimeError as exc:
                last_error = str(exc)
                continue

            if result.get("code") == 0:
                data = result.get("data", {})
                return {
                    "success": True,
                    "data": data.get("totalList", []) if isinstance(data, dict) else data,
                    "total": data.get("total", 0) if isinstance(data, dict) else len(data or []),
                }
            last_error = result.get("msg", "Unknown error")

        return {"success": False, "error_code": "API_ERROR", "error_message": last_error or "Unknown error"}

    def get_instance_detail(self, project_code: str, instance_id: Any) -> Dict[str, Any]:
        last_error = ""
        for path in self._instance_detail_paths(project_code, instance_id):
            try:
                result = self._request_json(path, timeout=30)
            except RuntimeError as exc:
                last_error = str(exc)
                continue

            if result.get("code") == 0:
                return {"success": True, "data": result.get("data", {})}
            last_error = result.get("msg", "Unknown error")

        return {"success": False, "error_code": "API_ERROR", "error_message": last_error or "Unknown error"}

    def stop_instance(self, project_code: str, instance_id: Any) -> Dict[str, Any]:
        try:
            result = self._request_json(
                f"/projects/{project_code}/executors/execute",
                method="POST",
                data={"processInstanceId": instance_id, "executeType": "STOP"},
                json_body=True,
                timeout=30,
            )
        except RuntimeError as exc:
            return {"success": False, "error_code": "NETWORK_ERROR", "error_message": str(exc)}

        if result.get("code") == 0:
            return {"success": True}
        return {
            "success": False,
            "error_code": result.get("code", "API_ERROR"),
            "error_message": result.get("msg", "Unknown error"),
        }

    def get_environments(self) -> Dict[str, Any]:
        try:
            result = self._request_json("/environment/list-paging?pageNo=1&pageSize=10", timeout=30)
        except RuntimeError as exc:
            return {"success": False, "error_code": "NETWORK_ERROR", "error_message": str(exc)}

        if result.get("code") == 0:
            return {"success": True, "data": result.get("data", {}).get("totalList", [])}
        return {
            "success": False,
            "error_code": result.get("code", "API_ERROR"),
            "error_message": result.get("msg", "Unknown error"),
        }

    def get_user_info(self) -> Dict[str, Any]:
        try:
            result = self._request_json("/users/get-user-info", timeout=30)
        except RuntimeError as exc:
            return {"success": False, "error_code": "NETWORK_ERROR", "error_message": str(exc)}

        if result.get("code") == 0:
            return {"success": True, "data": result.get("data", {})}
        return {
            "success": False,
            "error_code": result.get("code", "API_ERROR"),
            "error_message": result.get("msg", "Unknown error"),
        }


def start_workflow_simple(project_code: str, process_code: str, dt: Optional[str] = None) -> Dict[str, Any]:
    client = DolphinSchedulerClient(base_url=DS_CONFIG["base_url"], token=os.environ.get("DS_TOKEN", ""))
    custom_params = {"dt": dt} if dt else None
    return client.start_workflow(
        project_code=project_code,
        process_code=process_code,
        custom_params=custom_params,
    )


def start_single_task(project_code: str, process_code: str, task_code: str, dt: Optional[str] = None) -> Dict[str, Any]:
    client = DolphinSchedulerClient(base_url=DS_CONFIG["base_url"], token=os.environ.get("DS_TOKEN", ""))
    custom_params = {"dt": dt} if dt else None
    return client.start_workflow(
        project_code=project_code,
        process_code=process_code,
        custom_params=custom_params,
        task_code=task_code,
        task_depend_type="TASK_ONLY",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DolphinScheduler API 启动脚本")
    parser.add_argument("--project", required=True, help="项目 Code")
    parser.add_argument("--process", required=True, help="工作流 Code")
    parser.add_argument("--task", help="任务 Code（可选，指定单个任务时使用）")
    parser.add_argument("--dt", help="业务日期（可选），如 2026-03-17")
    parser.add_argument(
        "--mode",
        choices=["full", "single", "post", "pre"],
        default="full",
        help="执行模式：full=整个工作流，single=单个任务，post=当前 + 下游，pre=当前 + 上游",
    )

    args = parser.parse_args()
    mode_map = {
        "full": "TASK_POST",
        "single": "TASK_ONLY",
        "post": "TASK_POST",
        "pre": "TASK_PRE",
    }

    client = DolphinSchedulerClient(base_url=DS_CONFIG["base_url"], token=os.environ.get("DS_TOKEN", ""))
    custom_params = {"dt": args.dt} if args.dt else None

    print("🚀 正在启动工作流...")
    print(f"   项目 Code: {args.project}")
    print(f"   工作流 Code: {args.process}")
    if args.task:
        print(f"   任务 Code: {args.task}")
    if args.dt:
        print(f"   业务日期：{args.dt}")
    print(f"   执行模式：{args.mode}")
    print()

    result = client.start_workflow(
        project_code=args.project,
        process_code=args.process,
        custom_params=custom_params,
        task_code=args.task,
        task_depend_type=mode_map[args.mode],
    )

    if result["success"]:
        print("✅ 启动成功！")
        print(f"   实例 ID: {result['instance_id']}")
    else:
        print("❌ 启动失败！")
        print(f"   错误码：{result['error_code']}")
        print(f"   错误信息：{result['error_message']}")
