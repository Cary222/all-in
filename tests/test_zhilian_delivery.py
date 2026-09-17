"""Tests for Zhilian delivery adapter, multi-platform sender dispatch and worker slots."""

import json
import sqlite3
import tempfile
from pathlib import Path
from threading import Event
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from allin.db import count_sent_today, get_db, insert_job
from allin.executor.sender import (
    BaseSender,
    BossSender,
    PLATFORM_SENDERS,
    ZhilianSender,
    _send_zhilian_greeting_once,
    get_sender,
    send_greetings,
)
from allin.web.tasks import (
    GLOBAL_EXCLUSIVE_MODES,
    TaskAlreadyRunningError,
    WorkbenchTask,
    WorkbenchTaskRunner,
    WorkerSlot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(job_id="zhilian:test-1", platform="zhilian", greeting="你好", **extra):
    return {
        "id": job_id,
        "title": "测试岗位",
        "company": "测试公司",
        "jd": "岗位描述",
        "url": "https://jobs.zhaopin.com/test-1.htm",
        "source_platform": platform,
        "source_job_id": "test-1",
        "greeting": greeting,
        **extra,
    }


def _seed_db(db_path, jobs):
    db = get_db(db_path)
    try:
        for job in jobs:
            insert_job(db, job)
            if job.get("greeting"):
                db.execute(
                    "UPDATE jobs SET greeting=?, status='ready' WHERE id=?",
                    (job["greeting"], job["id"]),
                )
            if job.get("score"):
                db.execute(
                    "UPDATE jobs SET score=? WHERE id=?",
                    (job["score"], job["id"]),
                )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# _send_zhilian_greeting_once unit tests
# ---------------------------------------------------------------------------

class ZhilianGreetingOnceTests(TestCase):
    """Test the low-level single-job Zhilian send function."""

    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-1")
    def test_open_page_failed_returns_error(self, mock_new_tab, mock_eval, mock_wait, mock_close):
        mock_new_tab.return_value = None
        result, target = _send_zhilian_greeting_once(
            _make_job(), "你好", {"browse_before_greet": False},
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "open_page_failed")
        self.assertIsNone(target)
        mock_close.assert_not_called()

    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-1")
    def test_already_sent_returns_success(self, mock_new_tab, mock_eval, mock_wait, mock_close):
        mock_eval.return_value = json.dumps({
            "success": True, "already_sent": True, "verified": True,
            "history_detail": "岗位已处于已投递或沟通中状态",
        })
        result, target = _send_zhilian_greeting_once(
            _make_job(), "你好", {"browse_before_greet": False},
        )
        self.assertTrue(result["success"])
        self.assertTrue(result.get("already_sent"))
        mock_close.assert_called_once_with("tab-1")

    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-1")
    def test_blocked_page_returns_error(self, mock_new_tab, mock_eval, mock_wait, mock_close):
        mock_eval.return_value = json.dumps({
            "success": False, "error": "blocked",
            "history_detail": "智联出现验证码或访问限制",
        })
        result, target = _send_zhilian_greeting_once(
            _make_job(), "你好", {"browse_before_greet": False},
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "blocked")
        mock_close.assert_called_once_with("tab-1")

    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-1")
    @patch("allin.executor.sender._sleep_or_stop", return_value=False)
    def test_successful_click_and_verify(self, mock_sleep, mock_new_tab, mock_eval, mock_wait, mock_close):
        # First evaluate: click button, second: confirm dialog, third: not called
        mock_eval.side_effect = [
            json.dumps({"success": True, "action": "clicked", "button_type": "apply"}),
            json.dumps({"success": True, "handled_dialog": True, "verified": True, "status_text": "已投递"}),
        ]
        result, target = _send_zhilian_greeting_once(
            _make_job(), "你好HR", {"browse_before_greet": False},
        )
        self.assertTrue(result["success"])
        self.assertTrue(result.get("verified"))
        mock_close.assert_called_once_with("tab-1")

    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-1")
    def test_stop_event_aborts_early(self, mock_new_tab, mock_eval, mock_wait, mock_close):
        stop = Event()
        stop.set()
        result, target = _send_zhilian_greeting_once(
            _make_job(), "你好", {"browse_before_greet": False}, stop_event=stop,
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "stopped")
        mock_close.assert_called_once_with("tab-1")

    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-1")
    def test_job_page_unavailable(self, mock_new_tab, mock_eval, mock_wait, mock_close):
        mock_eval.return_value = json.dumps({
            "success": False, "error": "job_page_unavailable",
            "history_detail": "岗位已下线或关闭", "skip_backoff": True,
        })
        result, _ = _send_zhilian_greeting_once(
            _make_job(), "你好", {"browse_before_greet": False},
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "job_page_unavailable")
        self.assertTrue(result.get("skip_backoff"))

    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-1")
    def test_no_action_button(self, mock_new_tab, mock_eval, mock_wait, mock_close):
        mock_eval.return_value = json.dumps({
            "success": False, "error": "no_action_button",
            "history_detail": "未找到智联沟通或投递按钮", "skip_backoff": True,
        })
        result, _ = _send_zhilian_greeting_once(
            _make_job(), "你好", {"browse_before_greet": False},
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "no_action_button")

    def test_access_guard_blocks(self):
        from allin.platform_safety import PlatformAccessGuard, PlatformSafetyStop

        guard = Mock(spec=PlatformAccessGuard)
        guard.reserve.side_effect = PlatformSafetyStop("页面访问上限")
        result, target = _send_zhilian_greeting_once(
            _make_job(), "你好", {"_platform_access_guard": guard},
        )
        self.assertFalse(result["success"])
        self.assertIn("安全", result["history_detail"])
        self.assertIsNone(target)


# ---------------------------------------------------------------------------
# Sender class & factory tests
# ---------------------------------------------------------------------------

class SenderClassTests(TestCase):
    def test_platform_senders_registry(self):
        self.assertIn("boss", PLATFORM_SENDERS)
        self.assertIn("zhilian", PLATFORM_SENDERS)
        self.assertIs(PLATFORM_SENDERS["boss"], BossSender)
        self.assertIs(PLATFORM_SENDERS["zhilian"], ZhilianSender)

    def test_get_sender_returns_correct_type(self):
        boss = get_sender("boss", {})
        self.assertIsInstance(boss, BossSender)
        self.assertEqual(boss.platform_name, "boss")

        zhilian = get_sender("zhilian", {})
        self.assertIsInstance(zhilian, ZhilianSender)
        self.assertEqual(zhilian.platform_name, "zhilian")

    def test_get_sender_unsupported_raises(self):
        with self.assertRaises(ValueError):
            get_sender("unknown_platform", {})

    def test_base_sender_is_abstract(self):
        with self.assertRaises(TypeError):
            BaseSender({})

    def test_boss_sender_delegates_to_greeting_once(self):
        sender = BossSender({})
        with patch("allin.executor.sender._send_greeting_once") as mock_fn:
            mock_fn.return_value = ({"success": True}, "tab-x")
            result, target = sender.send_single_job(
                _make_job(platform="boss"), "你好", {},
            )
            mock_fn.assert_called_once()
            self.assertTrue(result["success"])

    def test_zhilian_sender_delegates_to_zhilian_once(self):
        sender = ZhilianSender({})
        with patch("allin.executor.sender._send_zhilian_greeting_once") as mock_fn:
            mock_fn.return_value = ({"success": True, "verified": True}, None)
            result, target = sender.send_single_job(
                _make_job(), "你好", {}, stop_event=None,
            )
            mock_fn.assert_called_once()
            self.assertTrue(result["success"])


# ---------------------------------------------------------------------------
# send_greetings dispatcher tests
# ---------------------------------------------------------------------------

class SendGreetingsDispatchTests(TestCase):
    """Test the top-level send_greetings dispatch across platforms."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = Path(self.tmp) / "test.db"
        # Common patches to avoid browser/throttle side effects
        self._patches = [
            patch("allin.executor.sender.should_take_day_off", return_value=False),
            patch("allin.executor.sender.SendWindowChecker.is_active", return_value=True),
            patch("allin.executor.sender.SendWindowChecker.next_window_info", return_value=""),
            patch("allin.executor.sender.PlatformAccessGuard.ensure_unlocked"),
            patch("allin.executor.sender.get_page_targets", return_value=[]),
            patch("allin.executor.sender.close_tab"),
            patch("allin.executor.sender.new_tab", return_value="tab-mock"),
            patch("allin.executor.sender.wait_for_load"),
            patch("allin.executor.sender.evaluate", return_value=json.dumps({
                "success": True, "verified": True, "history_detail": "模拟成功",
            })),
            patch("allin.executor.sender._sleep_or_stop", return_value=False),
            patch("allin.executor.sender.RequestThrottle.wait", return_value=0),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_explicit_platform_routes_to_sender(self):
        _seed_db(self.db_path, [
            _make_job("zl-1", "zhilian", "你好", score=80),
        ])
        config = {"throttle": {"daily_limit": 10, "interval_min": 0, "interval_max": 0}}
        with patch.object(ZhilianSender, "send_greetings", return_value=1) as mock_send:
            result = send_greetings(config, db_path=self.db_path, platform="zhilian")
            mock_send.assert_called_once()
            self.assertEqual(result, 1)

    def test_workbench_job_ids_dispatch_by_platform(self):
        _seed_db(self.db_path, [
            _make_job("boss-1", "boss", "你好boss", score=80),
            _make_job("zl-1", "zhilian", "你好zl", score=80),
        ])
        config = {
            "_workbench_job_ids": ["boss-1", "zl-1"],
            "throttle": {"daily_limit": 10, "interval_min": 0, "interval_max": 0},
        }
        with patch.object(BossSender, "send_greetings", return_value=1) as boss_send, \
             patch.object(ZhilianSender, "send_greetings", return_value=1) as zl_send:
            result = send_greetings(config, db_path=self.db_path)
            boss_send.assert_called_once()
            zl_send.assert_called_once()
            self.assertEqual(result, 2)

    def test_unsupported_platform_skipped_in_dispatch(self):
        _seed_db(self.db_path, [
            _make_job("unsupported-1", "lagou", "你好", score=80),
        ])
        config = {
            "_workbench_job_ids": ["unsupported-1"],
            "throttle": {"daily_limit": 10},
        }
        result = send_greetings(config, db_path=self.db_path)
        self.assertEqual(result, 0)
        report = config.get("_workbench_send_report", {})
        self.assertIn("unsupported-1", report.get("unsupported_platform_ids", []))

    def test_config_platform_key_routes_correctly(self):
        _seed_db(self.db_path, [
            _make_job("boss-1", "boss", "你好", score=80),
        ])
        config = {
            "_platform": "boss",
            "throttle": {"daily_limit": 10, "interval_min": 0, "interval_max": 0},
        }
        with patch.object(BossSender, "send_greetings", return_value=1) as mock_send:
            result = send_greetings(config, db_path=self.db_path)
            mock_send.assert_called_once()
            self.assertEqual(result, 1)

    def test_already_delivered_greeting_records_without_consuming_quota(self):
        """A greeting already present in the conversation must not burn today's quota.

        The bubble proves an earlier run delivered it, so this run did not send
        anything. It is recorded via ``manual_sent`` (the action used for
        out-of-band sends) purely for visibility, and ``count_sent_today`` — which
        only counts ``sent`` — must stay at zero.
        """
        _seed_db(self.db_path, [
            _make_job("lp-1", "liepin", "你好猎聘", score=80),
        ])
        db = get_db(self.db_path)
        try:
            before = count_sent_today(db, platform="liepin")
        finally:
            db.close()

        already_delivered = json.dumps({
            "success": True,
            "verified": True,
            "already_sent": True,
            "status_text": "ai_greeting_already_delivered",
            "sent_message": "你好猎聘",
        })
        config = {
            "_workbench_job_ids": ["lp-1"],
            "throttle": {"daily_limit": 10, "interval_min": 0, "interval_max": 0},
        }
        with patch("allin.executor.sender.evaluate", return_value=already_delivered):
            send_greetings(config, db_path=self.db_path, platform="liepin")

        db = get_db(self.db_path)
        try:
            after = count_sent_today(db, platform="liepin")
            job = db.execute("SELECT status FROM jobs WHERE id = 'lp-1'").fetchone()
            actions = [
                row["action"]
                for row in db.execute(
                    "SELECT action FROM history WHERE job_id = 'lp-1' ORDER BY id"
                ).fetchall()
            ]
        finally:
            db.close()

        self.assertEqual(before, 0)
        self.assertEqual(after, 0, "already-delivered greeting must not count as sent today")
        self.assertEqual(job["status"], "sent")
        self.assertIn("manual_sent", actions)
        self.assertNotIn("sent", actions)

    def test_page_limit_stop_does_not_mark_job_as_error(self):
        """A platform page-budget stop must not be recorded as a per-job failure.

        Hitting the daily platform-page budget or an active risk cooldown means the
        job was never attempted — the job itself is fine. It must stop the run
        without flipping the job to `error`, without counting a failure, and without
        burning a backoff cycle.
        """
        _seed_db(self.db_path, [
            _make_job("lp-limit", "liepin", "你好猎聘", score=80),
        ])
        config = {
            "_workbench_job_ids": ["lp-limit"],
            "throttle": {"daily_limit": 10, "interval_min": 0, "interval_max": 0},
        }
        limit_result = json.dumps({
            "success": False,
            "error": "daily_platform_page_limit",
            "history_detail": "为了账户安全，已达到平台页面访问上限",
        })
        with patch("allin.executor.sender.evaluate", return_value=limit_result):
            send_greetings(config, db_path=self.db_path, platform="liepin")

        report = config.get("_workbench_send_report", {})
        db = get_db(self.db_path)
        try:
            job = db.execute("SELECT status, last_error_code FROM jobs WHERE id = 'lp-limit'").fetchone()
            actions = [
                row["action"]
                for row in db.execute(
                    "SELECT action FROM history WHERE job_id = 'lp-limit' ORDER BY id"
                ).fetchall()
            ]
        finally:
            db.close()

        self.assertEqual(report.get("stop_reason"), "daily_platform_page_limit")
        self.assertEqual(report.get("failed_count"), 0)
        self.assertNotEqual(job["status"], "error")
        self.assertNotIn("error", actions)

    def test_risk_lock_stop_does_not_mark_job_as_error(self):
        """An active risk cooldown is likewise a safety stop, not a job failure."""
        _seed_db(self.db_path, [
            _make_job("zl-lock", "zhilian", "你好智联", score=80),
        ])
        config = {
            "_workbench_job_ids": ["zl-lock"],
            "throttle": {"daily_limit": 10, "interval_min": 0, "interval_max": 0},
        }
        lock_result = json.dumps({
            "success": False,
            "error": "persistent_risk_lock",
            "history_detail": "仍在风险冷却中",
        })
        with patch("allin.executor.sender.evaluate", return_value=lock_result):
            send_greetings(config, db_path=self.db_path, platform="zhilian")

        report = config.get("_workbench_send_report", {})
        db = get_db(self.db_path)
        try:
            job = db.execute("SELECT status FROM jobs WHERE id = 'zl-lock'").fetchone()
        finally:
            db.close()

        self.assertEqual(report.get("stop_reason"), "persistent_risk_lock")
        self.assertEqual(report.get("failed_count"), 0)
        self.assertNotEqual(job["status"], "error")

    def test_boss_daily_limit_is_not_silently_clamped(self):
        """The configured daily limit must be honoured, not clamped to 50.

        An earlier refactor clamped BOSS to 50 while `config_schema.json` allows up
        to 200, so a saved value above 50 was silently ignored and the workbench
        quota no longer matched what was actually sent.
        """
        _seed_db(self.db_path, [
            _make_job("boss-limit", "boss", "你好boss", score=80),
        ])
        config = {
            "_workbench_job_ids": ["boss-limit"],
            "throttle": {"daily_limit": 303, "interval_min": 0, "interval_max": 0},
        }
        with patch("allin.executor.sender.evaluate", return_value=json.dumps({
            "success": True, "verified": True,
        })):
            send_greetings(config, db_path=self.db_path, platform="boss")

        report = config.get("_workbench_send_report", {})
        self.assertEqual(report.get("daily_limit"), 303)


# ---------------------------------------------------------------------------
# WorkbenchTaskRunner multi-platform slot tests
# ---------------------------------------------------------------------------

class WorkerSlotTests(TestCase):
    """Test the multi-platform worker slot scheduling in WorkbenchTaskRunner."""

    def test_global_exclusive_modes(self):
        self.assertIn("full", GLOBAL_EXCLUSIVE_MODES)
        self.assertIn("score", GLOBAL_EXCLUSIVE_MODES)
        self.assertIn("rescore", GLOBAL_EXCLUSIVE_MODES)
        self.assertNotIn("collect", GLOBAL_EXCLUSIVE_MODES)
        self.assertNotIn("deliver", GLOBAL_EXCLUSIVE_MODES)

    def test_task_snapshot_includes_platform_and_slot(self):
        task = WorkbenchTask(id="t-1", mode="deliver", label="确认投递", platform="zhilian", slot="platform:zhilian")
        snap = task.snapshot()
        self.assertEqual(snap["platform"], "zhilian")
        self.assertEqual(snap["slot"], "platform:zhilian")
        self.assertEqual(snap["worker_type"], "thread")

    def test_resolve_slot_global_for_full(self):
        runner = WorkbenchTaskRunner()
        slot_id, plat, exclusive = runner._resolve_slot("full", {})
        self.assertEqual(slot_id, "global")
        self.assertTrue(exclusive)

    def test_resolve_slot_platform_from_config(self):
        runner = WorkbenchTaskRunner()
        slot_id, plat, exclusive = runner._resolve_slot("deliver", {"_platform": "zhilian"})
        self.assertEqual(slot_id, "platform:zhilian")
        self.assertEqual(plat, "zhilian")
        self.assertFalse(exclusive)

    def test_resolve_slot_single_collection_platform(self):
        runner = WorkbenchTaskRunner()
        config = {"_collection_options": {"platform_order": ["boss"]}}
        slot_id, plat, exclusive = runner._resolve_slot("collect", config)
        self.assertEqual(slot_id, "platform:boss")
        self.assertEqual(plat, "boss")
        self.assertFalse(exclusive)

    def test_resolve_slot_multi_collection_is_global(self):
        runner = WorkbenchTaskRunner()
        config = {"_collection_options": {"platform_order": ["boss", "zhilian"]}}
        slot_id, plat, exclusive = runner._resolve_slot("collect", config)
        self.assertEqual(slot_id, "global")
        self.assertTrue(exclusive)

    def test_different_platform_tasks_run_concurrently(self):
        entered_boss, entered_zl = Event(), Event()
        release = Event()

        def boss_executor(task, config):
            entered_boss.set()
            release.wait(timeout=5)

        def zl_executor(task, config):
            entered_zl.set()
            release.wait(timeout=5)

        runner = WorkbenchTaskRunner({"deliver": boss_executor})
        try:
            # Start boss deliver
            t1 = runner.start("deliver", {"_platform": "boss"}, platform="boss")
            self.assertEqual(t1["platform"], "boss")
            self.assertEqual(t1["slot"], "platform:boss")

            # Replace executor for zhilian task
            runner._executors["deliver"] = zl_executor
            t2 = runner.start("deliver", {"_platform": "zhilian"}, platform="zhilian")
            self.assertEqual(t2["platform"], "zhilian")
            self.assertEqual(t2["slot"], "platform:zhilian")

            # Both should be running concurrently
            self.assertTrue(entered_boss.wait(timeout=2))
            self.assertTrue(entered_zl.wait(timeout=2))

            status = runner.status()
            self.assertEqual(len(status["active_tasks"]), 2)
            self.assertIn("boss", status["active_by_platform"])
            self.assertIn("zhilian", status["active_by_platform"])
        finally:
            release.set()
            runner.wait(timeout=3)

    def test_same_platform_tasks_conflict(self):
        release = Event()

        def slow_executor(task, config):
            release.wait(timeout=5)

        runner = WorkbenchTaskRunner({"deliver": slow_executor})
        try:
            runner.start("deliver", {"_platform": "boss"}, platform="boss")
            with self.assertRaises(TaskAlreadyRunningError):
                runner.start("deliver", {"_platform": "boss"}, platform="boss")
        finally:
            release.set()
            runner.wait(timeout=3)

    def test_global_exclusive_blocks_platform_task(self):
        release = Event()

        def slow_executor(task, config):
            release.wait(timeout=5)

        runner = WorkbenchTaskRunner({"full": slow_executor, "deliver": slow_executor})
        try:
            runner.start("full", {})
            with self.assertRaises(TaskAlreadyRunningError):
                runner.start("deliver", {"_platform": "zhilian"}, platform="zhilian")
        finally:
            release.set()
            runner.wait(timeout=3)

    def test_platform_task_blocks_global_exclusive(self):
        release = Event()

        def slow_executor(task, config):
            release.wait(timeout=5)

        runner = WorkbenchTaskRunner({"deliver": slow_executor, "full": slow_executor})
        try:
            runner.start("deliver", {"_platform": "boss"}, platform="boss")
            with self.assertRaises(TaskAlreadyRunningError):
                runner.start("full", {})
        finally:
            release.set()
            runner.wait(timeout=3)

    def test_stop_platform_only_stops_matching_tasks(self):
        entered_boss, entered_zl = Event(), Event()
        release = Event()

        def executor(task, config):
            if task.platform == "boss":
                entered_boss.set()
            else:
                entered_zl.set()
            release.wait(timeout=5)

        runner = WorkbenchTaskRunner({"deliver": executor})
        try:
            runner.start("deliver", {"_platform": "boss"}, platform="boss")
            runner._executors["deliver"] = executor
            runner.start("deliver", {"_platform": "zhilian"}, platform="zhilian")

            entered_boss.wait(timeout=2)
            entered_zl.wait(timeout=2)

            stopped = runner.stop_platform("boss")
            self.assertEqual(len(stopped), 1)
            self.assertEqual(stopped[0]["platform"], "boss")

            status = runner.status()
            active = [t for t in status["active_tasks"] if t["status"] == "running"]
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["platform"], "zhilian")
        finally:
            release.set()
            runner.wait(timeout=3)

    def test_stop_all(self):
        release = Event()

        def executor(task, config):
            release.wait(timeout=5)

        runner = WorkbenchTaskRunner({"deliver": executor})
        try:
            runner.start("deliver", {"_platform": "boss"}, platform="boss")
            runner._executors["deliver"] = executor
            runner.start("deliver", {"_platform": "zhilian"}, platform="zhilian")

            stopped = runner.stop_all()
            self.assertEqual(len(stopped), 2)
        finally:
            release.set()
            runner.wait(timeout=3)

    def test_slot_released_after_task_completes(self):
        runner = WorkbenchTaskRunner({"deliver": lambda t, c: None})
        runner.start("deliver", {"_platform": "boss"}, platform="boss")
        runner.wait(timeout=2)

        status = runner.status()
        self.assertIsNone(status["active"])
        self.assertEqual(len(status["active_tasks"]), 0)
        self.assertEqual(status["slots"], {})

        # Should be able to start again
        runner._executors["deliver"] = lambda t, c: None
        t = runner.start("deliver", {"_platform": "boss"}, platform="boss")
        self.assertEqual(t["status"], "running")
        runner.wait(timeout=2)

    def test_max_slots_limit(self):
        release = Event()

        def executor(task, config):
            release.wait(timeout=5)

        runner = WorkbenchTaskRunner({"deliver": executor}, max_slots=2)
        try:
            runner.start("deliver", {"_platform": "boss"}, platform="boss")
            runner._executors["deliver"] = executor
            runner.start("deliver", {"_platform": "zhilian"}, platform="zhilian")

            with self.assertRaises(TaskAlreadyRunningError):
                runner._executors["deliver"] = executor
                runner.start("deliver", {"_platform": "liepin"}, platform="liepin")
        finally:
            release.set()
            runner.wait(timeout=3)

    def test_status_platform_filter(self):
        release = Event()

        def executor(task, config):
            release.wait(timeout=5)

        runner = WorkbenchTaskRunner({"deliver": executor})
        try:
            runner.start("deliver", {"_platform": "boss"}, platform="boss")
            runner._executors["deliver"] = executor
            runner.start("deliver", {"_platform": "zhilian"}, platform="zhilian")

            boss_status = runner.status(platform="boss")
            self.assertEqual(boss_status["active"]["platform"], "boss")

            zl_status = runner.status(platform="zhilian")
            self.assertEqual(zl_status["active"]["platform"], "zhilian")
        finally:
            release.set()
            runner.wait(timeout=3)

    def test_backward_compat_single_active(self):
        """status()['active'] returns the latest active task for backward compat."""
        runner = WorkbenchTaskRunner({"deliver": lambda t, c: None})
        t = runner.start("deliver", {})
        runner.wait(timeout=2)

        status = runner.status()
        self.assertIsNone(status["active"])
        self.assertEqual(status["last_task"]["status"], "completed")
        self.assertIsInstance(status["tasks"], list)
