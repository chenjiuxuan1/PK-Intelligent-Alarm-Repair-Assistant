import io
import unittest
import urllib.error
from unittest import mock

from dolphinscheduler import dolphinscheduler_api
from dolphinscheduler import run_fuyan_workflows


class FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def make_http_error(url: str, code: int, reason: str, body: str = ""):
    return urllib.error.HTTPError(url, code, reason, {}, io.BytesIO(body.encode("utf-8")))


class DolphinSchedulerApiTests(unittest.TestCase):
    def test_get_workflows_list_falls_back_to_query_workflow_definition_list(self):
        client = dolphinscheduler_api.DolphinSchedulerClient(base_url="http://ds", token="token")
        client.default_config["definition_endpoint_style"] = "auto"

        def fake_urlopen(req, timeout=30):
            url = req.full_url
            if url.endswith("/workflow-definition?pageNo=1&pageSize=100"):
                return FakeResponse("<!DOCTYPE html>")
            if url.endswith("/process-definition?pageNo=1&pageSize=100"):
                return FakeResponse("<!DOCTYPE html>")
            if url.endswith("/workflow-definition/query-workflow-definition-list"):
                return FakeResponse('{"code":0,"data":[{"code":"wf-1"}]}')
            raise AssertionError(url)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.get_workflows_list("project-1")

        self.assertTrue(result["success"])
        self.assertEqual(result["data"], [{"code": "wf-1"}])

    def test_start_workflow_falls_back_to_start_workflow_instance(self):
        client = dolphinscheduler_api.DolphinSchedulerClient(base_url="http://ds", token="token")
        client.default_config["start_endpoint"] = "start-process-instance"
        client.default_config["start_code_field"] = "processDefinitionCode"

        def fake_urlopen(req, timeout=30):
            url = req.full_url
            if url.endswith("/start-process-instance"):
                raise make_http_error(url, 405, "Method Not Allowed")
            if url.endswith("/start-workflow-instance"):
                return FakeResponse('{"code":0,"data":98765}')
            raise AssertionError(url)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.start_workflow("project-1", "wf-1", custom_params={"dt": "2026-05-20"})

        self.assertTrue(result["success"])
        self.assertEqual(result["instance_id"], 98765)
        self.assertEqual(result["endpoint"], "start-workflow-instance")
        self.assertEqual(result["code_field"], "workflowDefinitionCode")

    def test_get_workflow_instances_falls_back_to_process_instances(self):
        client = dolphinscheduler_api.DolphinSchedulerClient(base_url="http://ds", token="token")
        client.default_config["instance_endpoint_style"] = "workflow-instances"

        def fake_urlopen(req, timeout=30):
            url = req.full_url
            if "/workflow-instances?" in url:
                return FakeResponse("<!DOCTYPE html>")
            if "/process-instances?" in url:
                return FakeResponse(
                    '{"code":0,"data":{"total":1,"totalList":[{"id":1,"workflowDefinitionCode":"wf-1"}]}}'
                )
            raise AssertionError(url)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.get_workflow_instances("project-1")

        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["workflowDefinitionCode"], "wf-1")

    def test_run_fuyan_start_workflow_uses_start_node_list_with_task_only(self):
        with mock.patch.object(run_fuyan_workflows.CLIENT, "start_workflow", return_value={"success": True, "instance_id": 1}) as mocked:
            success, instance_id, message = run_fuyan_workflows.start_workflow(
                "project-1",
                "wf-1",
                "每小时复验1级表数据(D-1)",
                dt="2026-05-20",
                start_node_list="node-1",
            )

        self.assertTrue(success)
        self.assertEqual(instance_id, 1)
        self.assertEqual(message, "启动成功")
        mocked.assert_called_once_with(
            project_code="project-1",
            process_code="wf-1",
            custom_params={"dt": "2026-05-20"},
            task_code="node-1",
            task_depend_type="TASK_ONLY",
            environment_code=run_fuyan_workflows.DS_ENVIRONMENT_CODE,
            tenant_code=run_fuyan_workflows.DS_TENANT_CODE,
        )


if __name__ == "__main__":
    unittest.main()
