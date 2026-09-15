"""Tests for Multi-Target Collection Pipeline and Adaptive Multi-Resume Scoring."""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from allin.ai.scorer import resolve_job_resume, score_jobs
from allin.collection.models import JobCandidate, PlatformCollectionRequest
from allin.collection.orchestrator import _SharedProcessor, normalize_collection_options
from allin.config import DEFAULTS, get_job_targets
from allin.db import get_db, insert_job_if_new
from allin.resume_manager import save_resume_file
from allin.scoring_selection import preview_scoring, select_scoring_jobs, validate_options
from allin.web import server


class TestMultiTargetScoringPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temp_dir_obj.name)
        (self.temp_dir / "data").mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "data" / "allin.db"
        self.config = json.loads(json.dumps(DEFAULTS))
        self.config["profile"]["resume_path"] = str(self.temp_dir / "resume.md")
        self.config["ai"]["api_key"] = "test-key"
        self.config["ai"]["provider"] = "anthropic"
        self.config["job_targets"] = [
            {
                "id": "target_fullstack",
                "name": "全栈开发",
                "resume_id": "res_fullstack",
                "keywords": ["全栈", "Python"],
                "cities": ["北京"],
            },
            {
                "id": "target_ai",
                "name": "AI算法",
                "resume_id": "res_ai",
                "keywords": ["大模型", "LLM", "算法"],
                "cities": ["上海"],
            },
        ]

    def tearDown(self):
        try:
            self.temp_dir_obj.cleanup()
        except Exception:
            pass

    def test_collection_options_normalization_with_target(self):
        supplied = {
            "platform_order": ["boss"],
            "target_id": "target_fullstack",
            "platforms": {
                "boss": {
                    "keywords": ["全栈"],
                    "cities": ["北京"],
                }
            }
        }
        opts = normalize_collection_options(self.config, supplied)
        self.assertEqual(opts.get("target_id"), "target_fullstack")
        self.assertEqual(opts.get("target_name"), "全栈开发")
        self.assertEqual(opts.get("resume_id"), "res_fullstack")

    def test_shared_processor_save_inherits_target_from_request(self):
        conn = get_db(self.db_path)
        request = PlatformCollectionRequest(
            platform="boss",
            keywords=["Python"],
            cities=["北京"],
            city_codes={"北京": "101010100"},
            target_id="target_fullstack",
            target_name="全栈开发",
            resume_id="res_fullstack",
        )
        processor = _SharedProcessor(
            conn,
            request,
            run_id="run_1",
            platform_index=1,
            platform_total=1,
            stop_event=None,
            config=self.config,
            emit=lambda p: None,
        )
        candidate = JobCandidate(
            platform="boss",
            source_job_id="job_123",
            title="全栈工程师",
            company="测试公司",
            city="北京",
            salary="20-35K",
            jd="负责后端架构设计与前端页面开发",
        )
        saved = processor.save(candidate)
        self.assertTrue(saved)
        row = conn.execute("SELECT * FROM jobs WHERE source_job_id = 'job_123'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["target_id"], "target_fullstack")
        self.assertEqual(row["target_name"], "全栈开发")
        self.assertEqual(row["resume_id"], "res_fullstack")
        conn.close()

    def test_scoring_selection_target_and_resume_filter(self):
        conn = get_db(self.db_path)
        j1 = JobCandidate(platform="boss", source_job_id="j1", title="全栈", company="A", city="北京", salary="20K", jd="全栈开发", target_id="target_fullstack", resume_id="res_fullstack")
        j2 = JobCandidate(platform="boss", source_job_id="j2", title="AI研究员", company="B", city="上海", salary="30K", jd="大模型微调", target_id="target_ai", resume_id="res_ai")
        insert_job_if_new(conn, j1.as_job_record())
        insert_job_if_new(conn, j2.as_job_record())

        # Select target_fullstack
        fullstack_jobs = select_scoring_jobs(conn, target_id="target_fullstack")
        self.assertEqual(len(fullstack_jobs), 1)
        self.assertEqual(fullstack_jobs[0]["source_job_id"], "j1")

        # Select target_ai
        ai_jobs = select_scoring_jobs(conn, target_id="target_ai")
        self.assertEqual(len(ai_jobs), 1)
        self.assertEqual(ai_jobs[0]["source_job_id"], "j2")

        # Preview scoring with resume filter
        preview = preview_scoring(conn, resume_id="res_fullstack")
        self.assertEqual(preview["eligible_jobs"], 1)
        self.assertEqual(preview["skipped_jobs"], 0)

        conn.close()

    def test_resolve_job_resume_priorities(self):
        resumes = [
            {"id": "res_default", "name": "默认全能简历", "target_direction": "通用软件开发", "is_default": True},
            {"id": "res_fullstack", "name": "全栈专家简历", "target_direction": "全栈开发/Python/React", "is_default": False},
            {"id": "res_ai", "name": "大模型算法简历", "target_direction": "大模型/AI/LLM算法", "is_default": False},
        ]
        targets = self.config["job_targets"]

        # Priority 1: Explicit resume ID
        meta, _ = resolve_job_resume({}, resumes, targets, self.config, explicit_resume_id="res_ai")
        self.assertEqual(meta["id"], "res_ai")

        # Priority 2: Bound resume_id on job
        meta, _ = resolve_job_resume({"resume_id": "res_fullstack"}, resumes, targets, self.config)
        self.assertEqual(meta["id"], "res_fullstack")

        # Priority 3: Target id on job
        meta, _ = resolve_job_resume({"target_id": "target_ai"}, resumes, targets, self.config)
        self.assertEqual(meta["id"], "res_ai")

        # Priority 4: Adaptive keyword matching
        job_ai = {"title": "大模型应用工程师", "source_keyword": "LLM", "jd": "负责RAG检索增强与大模型微调"}
        meta, _ = resolve_job_resume(job_ai, resumes, targets, self.config)
        self.assertEqual(meta["id"], "res_ai")

        job_fs = {"title": "高级全栈开发", "source_keyword": "全栈", "jd": "负责全栈研发，精通 Python 和 React"}
        meta, _ = resolve_job_resume(job_fs, resumes, targets, self.config)
        self.assertEqual(meta["id"], "res_fullstack")

        # Priority 5: Fallback to default
        job_other = {"title": "出纳专员", "source_keyword": "财务", "jd": "负责日常记账"}
        meta, _ = resolve_job_resume(job_other, resumes, targets, self.config)
        self.assertEqual(meta["id"], "res_default")

    @patch("allin.ai.scorer.get_db")
    @patch("allin.ai.scorer._call_claude")
    def test_score_jobs_adaptive_multi_resume_persistence(self, mock_call_claude, mock_get_db):
        conn = get_db(self.db_path)
        mock_get_db.return_value = conn

        # Save two resumes to temp_dir
        res_fs = save_resume_file(
            b"# Fullstack Resume Content",
            "fullstack.md",
            name="全栈开发专家",
            target_direction="全栈开发",
            config=self.config,
            base_dir=self.temp_dir,
        )
        res_ai = save_resume_file(
            b"# AI Algorithm Resume Content",
            "ai.md",
            name="大模型算法研究员",
            target_direction="大模型算法",
            config=self.config,
            base_dir=self.temp_dir,
        )

        # Insert 2 pending jobs (one fullstack, one ai)
        j1 = JobCandidate(platform="boss", source_job_id="j1", title="全栈开发工程师", company="Corp A", city="北京", salary="25K", jd="熟练掌握 Python 和全栈架构")
        j2 = JobCandidate(platform="boss", source_job_id="j2", title="大模型算法专家", company="Corp B", city="上海", salary="40K", jd="精通大模型预训练与微调")
        insert_job_if_new(conn, j1.as_job_record())
        insert_job_if_new(conn, j2.as_job_record())

        score_mock_resp = json.dumps({
            "role_summary": "合适岗位",
            "hard_requirements": {"evidence": "符合", "score": 15},
            "core_duties": {"evidence": "有充分实践", "score": 35},
            "transferable_evidence": {"evidence": "丰富可迁移经验", "score": 22},
            "tools_industry": {"evidence": "匹配", "score": 9},
            "practical_fit": {"evidence": "城市薪资匹配", "score": 10},
            "caps": [],
            "hard_gaps": [],
            "reason": "非常符合候选人背景",
            "missing": "无",
        })
        mock_call_claude.return_value = score_mock_resp

        # Run score_jobs with base_dir pointing to temp_dir
        scored, filtered = score_jobs(self.config, base_dir=self.temp_dir)
        self.assertEqual(scored, 2)
        self.assertEqual(filtered, 0)

        # Verify in DB that matched_resume_id and matched_resume_name were persisted adaptively!
        verify_conn = get_db(self.db_path)
        row1 = verify_conn.execute("SELECT * FROM jobs WHERE source_job_id = 'j1'").fetchone()
        row2 = verify_conn.execute("SELECT * FROM jobs WHERE source_job_id = 'j2'").fetchone()

        self.assertEqual(row1["matched_resume_id"], res_fs["id"])
        self.assertEqual(row2["matched_resume_id"], res_ai["id"])
        self.assertEqual(row1["status"], "ready")
        self.assertEqual(row2["status"], "ready")

        verify_conn.close()

    def test_web_scoring_preview_with_target(self):
        original_base = server.BASE_DIR
        try:
            server.set_base_dir(self.temp_dir)
            with open(self.temp_dir / "config.json", "w", encoding="utf-8") as f:
                json.dump(self.config, f)

            conn = get_db(self.db_path)
            j1 = JobCandidate(platform="boss", source_job_id="j1", title="全栈", company="A", city="北京", salary="20K", jd="全栈开发", target_id="target_fullstack")
            j2 = JobCandidate(platform="boss", source_job_id="j2", title="AI研究员", company="B", city="上海", salary="30K", jd="大模型微调", target_id="target_ai")
            insert_job_if_new(conn, j1.as_job_record())
            insert_job_if_new(conn, j2.as_job_record())
            conn.close()

            status_headers = {}
            def start_response(status, headers, exc_info=None):
                status_headers["status"] = status
                status_headers["headers"] = dict(headers)

            req_body = json.dumps({"scope": "pending", "target_id": "target_fullstack"}).encode("utf-8")
            environ = {
                "REQUEST_METHOD": "POST",
                "PATH_INFO": "/api/scoring/preview",
                "QUERY_STRING": "",
                "SERVER_NAME": "127.0.0.1",
                "SERVER_PORT": "8686",
                "wsgi.version": (1, 0),
                "wsgi.url_scheme": "http",
                "wsgi.input": io.BytesIO(req_body),
                "wsgi.errors": io.StringIO(),
                "wsgi.multithread": False,
                "wsgi.multiprocess": False,
                "wsgi.run_once": False,
                "CONTENT_LENGTH": str(len(req_body)),
                "CONTENT_TYPE": "application/json",
            }
            res_iter = server.app(environ, start_response)
            body = b"".join(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8") for chunk in res_iter).decode("utf-8")
            data = json.loads(body)
            self.assertEqual(status_headers["status"], "200 OK")
            self.assertEqual(data.get("eligible_jobs"), 1)
        finally:
            server.set_base_dir(original_base)


if __name__ == "__main__":
    unittest.main()
