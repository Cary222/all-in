import io
import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from allin.db import get_db, insert_job
from allin.web import server


class PlatformDeliveryGuardTests(TestCase):
    @staticmethod
    def _request(path: str, body: dict | None = None):
        raw = json.dumps(body or {}).encode("utf-8")
        result = {}

        def start_response(status, headers, exc_info=None):
            result["status"] = status
            result["headers"] = dict(headers)

        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(raw)),
            "CONTENT_TYPE": "application/json",
            "SERVER_NAME": "127.0.0.1",
            "SERVER_PORT": "8686",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(raw),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }
        payload = b"".join(
            chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
            for chunk in server.app(environ, start_response)
        ).decode("utf-8")
        return result["status"], json.loads(payload)

    def test_unsupported_platforms_reject_delivery_and_resume_routes(self):
        platform = "unsupported_platform"
        job_id = "unsupported_platform:job-1"
        url = "https://example.com/job-1.html"

        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            db = get_db(base_dir / "data" / "allin.db")
            try:
                insert_job(db, {
                    "id": job_id,
                    "title": "采集岗位",
                    "company": "示例公司",
                    "jd": "JD",
                    "url": url,
                    "source_platform": platform,
                    "source_job_id": "job-1",
                })
            finally:
                db.close()
            server.set_base_dir(base_dir)

            with mock.patch.object(server.task_runner, "start") as start:
                deliver_status, deliver_payload = self._request(
                    "/api/workbench/deliver",
                    {"job_ids": [job_id]},
                )
            resume_status, resume_payload = self._request(f"/api/jobs/{job_id}/mark-resume-sent")

            self.assertTrue(deliver_status.startswith("403"), deliver_payload)
            self.assertEqual(deliver_payload.get("error"), "所选岗位的平台暂不支持投递动作")
            self.assertTrue(resume_status.startswith("403"), resume_payload)
            self.assertEqual(resume_payload.get("error"), "该岗位来源平台当前不支持投递或简历发送链路")
            start.assert_not_called()

    def test_all_supported_platforms_pass_platform_support_check(self):
        for platform in ("boss", "zhilian", "51job", "liepin"):
            with self.subTest(platform=platform):
                self.assertTrue(server.platform_supports(platform, "deliver"))

    def test_deliver_route_accepts_supported_platforms_and_sets_platform(self):
        for platform in ("boss", "zhilian", "51job", "liepin"):
            job_id = f"{platform}:job-test"
            with tempfile.TemporaryDirectory() as tmp:
                base_dir = Path(tmp)
                db = get_db(base_dir / "data" / "allin.db")
                try:
                    insert_job(db, {
                        "id": job_id,
                        "title": "测试岗位",
                        "company": "测试公司",
                        "jd": "JD",
                        "url": f"https://example.com/{platform}/1.html",
                        "source_platform": platform,
                        "source_job_id": "job-test",
                    })
                    db.execute("UPDATE jobs SET status = 'ready', greeting = '您好' WHERE id = ?", (job_id,))
                    db.commit()
                finally:
                    db.close()
                server.set_base_dir(base_dir)

                with mock.patch.object(server.task_runner, "start") as start:
                    start.return_value = {"id": "task-1", "status": "running"}
                    status, payload = self._request(
                        "/api/workbench/deliver",
                        {"job_ids": [job_id]},
                    )
                    self.assertTrue(status.startswith("200"), payload)
                    start.assert_called_once()
                    call_kwargs = start.call_args[1]
                    self.assertEqual(call_kwargs.get("platform"), platform)

    def test_deliver_route_mixed_platforms_sets_platform_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            db = get_db(base_dir / "data" / "allin.db")
            try:
                insert_job(db, {
                    "id": "boss:job-1",
                    "title": "岗位1",
                    "company": "公司1",
                    "url": "https://example.com/boss/1",
                    "source_platform": "boss",
                    "source_job_id": "1",
                })
                insert_job(db, {
                    "id": "zhilian:job-2",
                    "title": "岗位2",
                    "company": "公司2",
                    "url": "https://example.com/zhilian/2",
                    "source_platform": "zhilian",
                    "source_job_id": "2",
                })
                db.execute("UPDATE jobs SET status = 'ready', greeting = '您好' WHERE id IN ('boss:job-1', 'zhilian:job-2')")
                db.commit()
            finally:
                db.close()
            server.set_base_dir(base_dir)

            with mock.patch.object(server.task_runner, "start") as start:
                start.return_value = {"id": "task-2", "status": "running"}
                status, payload = self._request(
                    "/api/workbench/deliver",
                    {"job_ids": ["boss:job-1", "zhilian:job-2"]},
                )
                self.assertTrue(status.startswith("200"), payload)
                start.assert_called_once()
                call_kwargs = start.call_args[1]
                self.assertIsNone(call_kwargs.get("platform"))

    def test_send_greetings_scenario_b_accumulates_reports(self):
        from allin.executor.sender import send_greetings

        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            db_path = base_dir / "allin.db"
            db = get_db(db_path)
            try:
                insert_job(db, {
                    "id": "boss:1", "title": "B1", "company": "C1", "url": "u1", "source_platform": "boss",
                    "source_job_id": "1", "status": "approved", "greeting": "g1",
                })
                insert_job(db, {
                    "id": "zhilian:2", "title": "Z2", "company": "C2", "url": "u2", "source_platform": "zhilian",
                    "source_job_id": "2", "status": "approved", "greeting": "g2",
                })
            finally:
                db.close()

            config = {
                "_workbench_job_ids": ["boss:1", "zhilian:2"],
            }
            mock_boss_sender = mock.MagicMock()
            def boss_send(workbench_job_ids=None):
                mock_boss_sender.config["_workbench_send_report"] = {
                    "eligible_count": 1, "scheduled_count": 1, "attempted_count": 1,
                    "sent_count": 1, "failed_count": 0, "quota_deferred_count": 0,
                    "already_sent": 5, "daily_limit": 50, "remaining_quota": 45,
                }
                return 1
            mock_boss_sender.send_greetings.side_effect = boss_send

            mock_zhilian_sender = mock.MagicMock()
            def zhilian_send(workbench_job_ids=None):
                mock_zhilian_sender.config["_workbench_send_report"] = {
                    "eligible_count": 1, "scheduled_count": 1, "attempted_count": 1,
                    "sent_count": 1, "failed_count": 0, "quota_deferred_count": 0,
                    "already_sent": 2, "daily_limit": 100, "remaining_quota": 98,
                }
                return 1
            mock_zhilian_sender.send_greetings.side_effect = zhilian_send

            def get_sender_mock(plat, cfg, **kwargs):
                if plat == "boss":
                    mock_boss_sender.config = cfg
                    return mock_boss_sender
                mock_zhilian_sender.config = cfg
                return mock_zhilian_sender

            with mock.patch("allin.executor.sender.get_sender", side_effect=get_sender_mock):
                total = send_greetings(config, db_path=db_path)

            self.assertEqual(total, 2)
            rep = config["_workbench_send_report"]
            self.assertEqual(rep["sent_count"], 2)
            self.assertEqual(rep["eligible_count"], 2)
            self.assertEqual(rep["scheduled_count"], 2)
            self.assertEqual(rep["failed_count"], 0)
            self.assertEqual(rep["deferred_count"], 0)

