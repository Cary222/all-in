import json
import tempfile
import time
import unittest
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock, patch

from allin.db import add_history, get_db, insert_job, update_job_status
from allin.throttle import RequestThrottle


def _job(job_id: str, hr_name: str | None = None) -> dict:
    return {
        "id": job_id,
        "title": f"岗位-{job_id}",
        "company": f"公司-{job_id}",
        "salary": "20-30K",
        "city": "北京",
        "experience": "1-3年",
        "jd": "负责产品运营",
        "hr_name": hr_name or f"HR-{job_id}",
        "hr_title": "招聘者",
        "hr_active": "",
        "company_size": "",
        "company_industry": "",
        "url": f"https://example.com/{job_id}",
    }


class MonitorThrottleTests(unittest.TestCase):
    def test_boss_operation_multiplier_applies_to_monitor_cycle_wait(self):
        from allin.executor import monitor

        config = {
            "collection": {"collection_delay_multiplier": 1.5},
            "monitor": {"interval": 30},
        }

        self.assertEqual(monitor.get_boss_operation_interval_multiplier(config), 1.5)
        self.assertEqual(monitor.get_effective_monitor_interval_minutes(config), 45)

    def test_boss_operation_multiplier_applies_to_monitor_page_requests(self):
        from allin.executor import monitor

        config = {
            "collection": {"collection_delay_multiplier": 1.5},
            "throttle": {
                "interval_min": 60,
                "interval_max": 180,
                "send_windows": [],
            },
        }

        with patch.object(monitor, "RequestThrottle") as request_throttle, \
             patch.object(monitor, "check_replies", return_value=[]), \
             patch.object(monitor, "_check_follow_ups", return_value=0):
            monitor.monitor_and_send_resumes(config)

        request_throttle.assert_called_once_with(90, 270)

    def test_manual_chat_open_can_request_a_foreground_tab(self):
        from allin.executor import monitor

        with patch.object(monitor, "new_tab", return_value="chat-target") as new_tab:
            target_id = monitor._open_monitor_tab(
                "https://www.zhipin.com/web/geek/chat",
                {},
                background=False,
            )

        self.assertEqual(target_id, "chat-target")
        new_tab.assert_called_once_with(
            "https://www.zhipin.com/web/geek/chat",
            background=False,
        )

    def test_manual_reply_suggestion_is_counted_as_pending_not_failed(self):
        from allin.executor import monitor

        item = {"job": {"id": "pending-job"}, "conversation": {}}
        with patch.object(monitor, "check_replies", return_value=[item]), \
             patch.object(monitor, "_handle_conversation", return_value="reply_pending"), \
             patch.object(monitor, "_check_follow_ups", return_value=0):
            summary = monitor.monitor_and_send_resumes(
                {"throttle": {"send_windows": []}, "monitor": {}}
            )

        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["failed"], 0)

    def test_single_detected_reply_processing_disables_every_outbound_path(self):
        from allin.executor import monitor

        with patch.object(
            monitor,
            "monitor_and_send_resumes",
            return_value={"pending": 1},
        ) as run_monitor, patch.object(monitor, "close_monitor_chat_target") as close_target:
            summary = monitor.process_detected_reply(
                "job-one",
                {
                    "monitor": {"auto_reply_hr_questions": True, "max_conversations_per_cycle": 5},
                    "follow_up": {"enabled": True},
                },
            )

        safe_config = run_monitor.call_args.args[0]
        self.assertEqual(summary, {"pending": 1})
        self.assertEqual(safe_config["_monitor_job_ids"], ["job-one"])
        self.assertEqual(safe_config["monitor"]["max_conversations_per_cycle"], 1)
        self.assertFalse(safe_config["monitor"]["auto_reply_hr_questions"])
        self.assertFalse(safe_config["follow_up"]["enabled"])
        self.assertEqual(safe_config["throttle"]["send_windows"], [])
        self.assertTrue(safe_config["_monitor_reuse_chat_tab"])
        close_target.assert_called_once_with(safe_config)

    def test_boss_operation_multiplier_is_bounded_and_tolerates_invalid_values(self):
        from allin.executor import monitor

        self.assertEqual(
            monitor.get_boss_operation_interval_multiplier(
                {"collection": {"collection_delay_multiplier": 99}}
            ),
            5,
        )
        self.assertEqual(
            monitor.get_boss_operation_interval_multiplier(
                {"collection": {"collection_delay_multiplier": "invalid"}}
            ),
            1.5,
        )

    def test_mark_makes_configured_request_interval_effective(self):
        throttle = RequestThrottle(delay_min=60, delay_max=60)

        with patch("allin.throttle.time.time", return_value=100), \
             patch("allin.throttle.random.gauss", return_value=60), \
             patch("allin.throttle.random.random", return_value=1), \
             patch("allin.throttle.time.sleep") as sleep:
            throttle.mark()
            stopped = throttle.wait()

        self.assertFalse(stopped)
        sleep.assert_called_once_with(60)

    def test_every_monitor_tab_open_marks_and_waits_after_the_first(self):
        from allin.executor import monitor

        events = []

        class FakeThrottle:
            has_marked_request = False

            def wait(self, _stop_event=None):
                events.append("wait")
                return False

            def mark(self):
                events.append("mark")
                self.has_marked_request = True

        throttle = FakeThrottle()

        def open_tab(_url, background=False):
            self.assertTrue(background)
            events.append("open")
            return f"target-{events.count('open')}"

        config = {"_monitor_request_throttle": throttle}
        with patch.object(monitor, "new_tab", side_effect=open_tab):
            monitor._open_monitor_tab("https://example.com/one", config)
            monitor._open_monitor_tab("https://example.com/two", config)

        self.assertEqual(events, ["open", "mark", "wait", "open", "mark"])

    def test_web_monitor_reuses_one_live_chat_list_tab(self):
        from allin.executor import monitor

        config = {
            "_monitor_reuse_chat_tab": True,
            "_monitor_runtime_state": {},
        }
        with patch.object(monitor, "_open_monitor_tab", return_value="chat-target") as open_tab, \
             patch.object(monitor, "get_page_info", return_value={"url": "https://www.zhipin.com/web/geek/chat"}), \
             patch.object(monitor, "close_tab") as close_tab:
            first = monitor._get_monitor_chat_target("https://www.zhipin.com/web/geek/chat", config)
            second = monitor._get_monitor_chat_target("https://www.zhipin.com/web/geek/chat", config)
            monitor.close_monitor_chat_target(config)

        self.assertEqual(first, ("chat-target", False))
        self.assertEqual(second, ("chat-target", True))
        open_tab.assert_called_once()
        close_tab.assert_called_once_with("chat-target")

    def test_web_monitor_selects_scanned_row_without_opening_another_page(self):
        from allin.executor import monitor

        conversation = {
            "_chat_target_id": "chat-target",
            "element_index": 3,
            "hr_name": "HR-复用",
            "company": "示例公司",
        }
        monitor._SHARED_MONITOR_TARGETS.add("chat-target")
        try:
            with patch.object(
                monitor,
                "get_page_info",
                return_value={"url": "https://www.zhipin.com/web/geek/chat"},
            ), patch.object(
                monitor,
                "evaluate",
                return_value=json.dumps({"success": True}),
            ) as evaluate, patch.object(monitor, "_inspect_monitor_page"):
                target_id = monitor._open_scanned_conversation(
                    _job("reuse", "HR-复用") | {"company": "示例公司"},
                    {},
                    conversation,
                )
        finally:
            monitor._SHARED_MONITOR_TARGETS.discard("chat-target")

        self.assertEqual(target_id, "chat-target")
        script = evaluate.call_args.args[1]
        self.assertIn("expectedIndex = 3", script)
        self.assertIn("target.click()", script)


class MonitorIdempotencyAndLimitTests(unittest.TestCase):
    def test_single_job_filter_limits_detection_to_the_requested_job(self):
        from allin.executor import monitor

        db = MagicMock()
        jobs = [_job("job-one"), _job("job-two")]
        with patch.object(monitor, "get_db", return_value=db), \
             patch.object(
                 monitor,
                 "get_jobs_by_status",
                 side_effect=lambda _db, status: jobs if status == "sent" else [],
             ), \
             patch.object(monitor, "_check_boss_replies", return_value=[]) as check_boss:
            result = monitor.check_replies({"_monitor_job_ids": ["job-two"]})

        self.assertEqual(result, [])
        checked_jobs = check_boss.call_args.args[1]
        self.assertEqual([job["id"] for job in checked_jobs], ["job-two"])
        db.close.assert_called_once()

    def test_same_unresolved_reply_is_skipped_but_new_hr_message_is_processed(self):
        from allin.executor import monitor

        original_messages = [
            {"sender": "me", "text": "你好，我对岗位感兴趣。"},
            {"sender": "hr", "text": "请介绍一下相关经验。"},
        ]
        new_messages = [
            *original_messages,
            {"sender": "hr", "text": "也请补充一个最近的项目案例。"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "allin.db"
            db = get_db(db_path)
            try:
                insert_job(db, _job("dedup"))
                update_job_status(db, "dedup", "replied")
                add_history(
                    db,
                    "dedup",
                    "reply_pending",
                    monitor._build_reply_detail(original_messages, "建议回复"),
                )
            finally:
                db.close()

            def open_db():
                return get_db(db_path)

            common = [
                patch.object(monitor, "get_db", side_effect=open_db),
                patch.object(monitor, "_open_conversation", return_value="target-1"),
                patch.object(monitor, "close_tab"),
                patch.object(monitor.time, "sleep"),
            ]
            with common[0], common[1] as open_conversation, common[2], common[3], \
                 patch.object(monitor, "evaluate", return_value=json.dumps(original_messages)), \
                 patch.object(monitor, "_generate_auto_reply") as generate_reply:
                same_action = monitor._handle_conversation(_job("dedup") | {"status": "replied"}, {"monitor": {}})

            self.assertEqual(same_action, "skipped_existing_pending")
            open_conversation.assert_called_once()
            generate_reply.assert_not_called()

            with patch.object(monitor, "get_db", side_effect=open_db), \
                 patch.object(monitor, "_open_conversation", return_value="target-2"), \
                 patch.object(monitor, "close_tab"), \
                 patch.object(monitor.time, "sleep"), \
                 patch.object(monitor, "evaluate", return_value=json.dumps(new_messages)), \
                 patch.object(monitor, "_generate_auto_reply", return_value="新的建议回复") as generate_reply:
                new_action = monitor._handle_conversation(_job("dedup") | {"status": "replied"}, {"monitor": {}})

            verify_db = get_db(db_path)
            try:
                pending_count = verify_db.execute(
                    "SELECT COUNT(*) FROM history WHERE job_id = ? AND action = 'reply_pending'",
                    ("dedup",),
                ).fetchone()[0]
            finally:
                verify_db.close()

        self.assertEqual(new_action, "reply_pending")
        self.assertEqual(pending_count, 2)
        generate_reply.assert_called_once()

    def test_same_auto_reply_is_not_sent_twice_but_later_hr_turn_is_processed(self):
        from allin.executor import monitor

        original_messages = [
            {"sender": "me", "text": "你好，我对岗位感兴趣。"},
            {"sender": "hr", "text": "请介绍一下相关经验。"},
        ]
        later_messages = [
            *original_messages,
            {"sender": "hr", "text": "也请补充一个最近的项目案例。"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "allin.db"
            db = get_db(db_path)
            try:
                insert_job(db, _job("auto-round"))
                update_job_status(db, "auto-round", "replied")
                add_history(
                    db,
                    "auto-round",
                    "auto_replied",
                    monitor._build_reply_detail(
                        original_messages,
                        "第一轮自动回复",
                        "auto_replied.v1",
                    ),
                )
            finally:
                db.close()

            def open_db():
                return get_db(db_path)

            config = {"monitor": {"auto_reply_hr_questions": True}}
            with patch.object(monitor, "get_db", side_effect=open_db), \
                 patch.object(monitor, "_open_conversation", return_value="same-target"), \
                 patch.object(monitor, "_wait_or_stop", return_value=False), \
                 patch.object(monitor, "evaluate", return_value=json.dumps(original_messages)), \
                 patch.object(monitor, "close_tab"), \
                 patch.object(monitor, "_generate_auto_reply") as generate_reply, \
                 patch.object(monitor, "_send_message_in_chat") as send_message:
                same_action = monitor._handle_conversation(
                    _job("auto-round") | {"status": "replied"},
                    config,
                )

            self.assertEqual(same_action, "skipped_handled_reply")
            generate_reply.assert_not_called()
            send_message.assert_not_called()

            with patch.object(monitor, "get_db", side_effect=open_db), \
                 patch.object(monitor, "_open_conversation", return_value="later-target"), \
                 patch.object(monitor, "_wait_or_stop", return_value=False), \
                 patch.object(monitor, "evaluate", return_value=json.dumps(later_messages)), \
                 patch.object(monitor, "close_tab"), \
                 patch.object(monitor, "_generate_auto_reply", return_value="第二轮自动回复") as generate_reply, \
                 patch.object(monitor, "_send_message_in_chat", return_value=True) as send_message:
                later_action = monitor._handle_conversation(
                    _job("auto-round") | {"status": "replied"},
                    config,
                )

            verify_db = get_db(db_path)
            try:
                auto_reply_count = verify_db.execute(
                    "SELECT COUNT(*) FROM history WHERE job_id = ? AND action = 'auto_replied'",
                    ("auto-round",),
                ).fetchone()[0]
            finally:
                verify_db.close()

        self.assertEqual(later_action, "auto_replied")
        self.assertEqual(auto_reply_count, 2)
        generate_reply.assert_called_once()
        # The platform is passed explicitly so the right composer is used (BOSS
        # uses a Vue-internal submit, Zhilian a plain textarea).
        send_message.assert_called_once_with("later-target", "第二轮自动回复", "boss")

    def test_chat_list_skips_same_pending_before_opening_and_caps_new_items(self):
        from allin.executor import monitor

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "allin.db"
            db = get_db(db_path)
            try:
                for job_id in ("one", "two", "three"):
                    insert_job(db, _job(job_id))
                    update_job_status(db, job_id, "sent")
                messages = [{"sender": "hr", "text": "旧问题"}]
                add_history(
                    db,
                    "one",
                    "reply_pending",
                    monitor._build_reply_detail(
                        messages,
                        "旧建议",
                        conversation={"last_message": "旧问题"},
                    ),
                )
                update_job_status(db, "one", "replied")
            finally:
                db.close()

            conversations = [
                {
                    "hr_name": f"HR-{job_id}",
                    "company": f"公司-{job_id}",
                    "last_message": "旧问题" if job_id == "one" else f"新问题-{job_id}",
                    "has_reply": True,
                    "has_unread": False,
                }
                for job_id in ("one", "two", "three")
            ]

            def open_db():
                return get_db(db_path)

            with patch.object(monitor, "get_db", side_effect=open_db), \
                 patch.object(monitor, "_open_monitor_tab", return_value="chat-target"), \
                 patch.object(monitor, "_wait_or_stop", return_value=False), \
                 patch.object(monitor, "_wait_for_page_or_stop", return_value=True), \
                 patch.object(monitor, "evaluate", return_value=json.dumps(conversations)), \
                 patch.object(monitor, "close_tab"):
                results = monitor.check_replies({"monitor": {"max_conversations_per_cycle": 1}})

            verify_db = get_db(db_path)
            try:
                detected_actions = [
                    row["action"]
                    for row in verify_db.execute(
                        "SELECT action FROM history WHERE job_id = ? ORDER BY id",
                        ("two",),
                    ).fetchall()
                ]
            finally:
                verify_db.close()

        self.assertEqual([item["job"]["id"] for item in results], ["two"])
        self.assertEqual(detected_actions, ["hr_reply_detected"])

    def test_web_chat_scan_carries_shared_target_into_processing(self):
        from allin.executor import monitor

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "allin.db"
            db = get_db(db_path)
            try:
                insert_job(db, _job("shared"))
                update_job_status(db, "shared", "sent")
            finally:
                db.close()

            conversation = {
                "element_index": 2,
                "hr_name": "HR-shared",
                "company": "公司-shared",
                "last_message": "方便介绍一下相关经验吗？",
                "has_reply": True,
                "has_unread": True,
            }

            def open_db():
                return get_db(db_path)

            config = {
                "_monitor_reuse_chat_tab": True,
                "_monitor_runtime_state": {},
                "monitor": {"max_conversations_per_cycle": 1},
            }
            with patch.object(monitor, "get_db", side_effect=open_db), \
                 patch.object(monitor, "_open_monitor_tab", return_value="chat-target"), \
                 patch.object(monitor, "_wait_or_stop", return_value=False), \
                 patch.object(monitor, "_wait_for_page_or_stop", return_value=True), \
                 patch.object(monitor, "evaluate", return_value=json.dumps([conversation])), \
                 patch.object(monitor, "close_tab"):
                results = monitor.check_replies(config)

            monitor._SHARED_MONITOR_TARGETS.discard("chat-target")

        self.assertEqual(results[0]["conversation"]["_chat_target_id"], "chat-target")

    def test_chat_list_includes_unrecorded_outbound_reply_but_skips_plain_sent_job(self):
        from allin.executor import monitor

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "allin.db"
            db = get_db(db_path)
            try:
                insert_job(db, _job("greeting"))
                insert_job(db, _job("manual"))
                update_job_status(db, "greeting", "sent")
                update_job_status(db, "manual", "replied")
            finally:
                db.close()

            conversations = [
                {
                    "hr_name": f"HR-{job_id}",
                    "company": f"公司-{job_id}",
                    "last_message": message,
                    "last_direction": "me",
                    "is_our_message": True,
                    "has_reply": False,
                }
                for job_id, message in (
                    ("greeting", "您好，我对岗位很感兴趣。"),
                    ("manual", "可以，我补充一下相关经历。"),
                )
            ]

            def open_db():
                return get_db(db_path)

            with patch.object(monitor, "get_db", side_effect=open_db), \
                 patch.object(monitor, "_open_monitor_tab", return_value="chat-target"), \
                 patch.object(monitor, "_wait_or_stop", return_value=False), \
                 patch.object(monitor, "_wait_for_page_or_stop", return_value=True), \
                 patch.object(monitor, "evaluate", return_value=json.dumps(conversations)), \
                 patch.object(monitor, "close_tab"):
                results = monitor.check_replies({"monitor": {"max_conversations_per_cycle": 5}})

        self.assertEqual([item["job"]["id"] for item in results], ["manual"])


class MonitorRiskTests(unittest.TestCase):
    def test_captcha_stops_cycle_and_records_only_safe_risk_detail(self):
        from allin.executor import monitor

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "allin.db"
            db = get_db(db_path)
            try:
                insert_job(db, _job("risk"))
                update_job_status(db, "risk", "sent")
            finally:
                db.close()

            def open_db():
                return get_db(db_path)

            with patch.object(monitor, "get_db", side_effect=open_db), \
                 patch.object(monitor, "_open_monitor_tab", return_value="chat-target"), \
                 patch.object(monitor, "_wait_or_stop", return_value=False), \
                 patch.object(monitor, "_wait_for_page_or_stop", return_value=True), \
                 patch.object(monitor, "evaluate", return_value=json.dumps({"risk": "captcha"})), \
                 patch.object(monitor, "close_tab"):
                summary = monitor.monitor_and_send_resumes({"throttle": {"send_windows": []}, "monitor": {}})

            verify_db = get_db(db_path)
            try:
                events = [dict(row) for row in verify_db.execute("SELECT event_type, detail FROM risk_events").fetchall()]
            finally:
                verify_db.close()

        self.assertEqual(summary["stop_reason"], "captcha")
        self.assertEqual(events, [{"event_type": "monitor_captcha", "detail": "监测检测到验证码，已停止"}])

    def test_consecutive_page_failures_stop_at_configured_threshold(self):
        from allin.executor import monitor

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "allin.db"

            def open_db():
                return get_db(db_path)

            guard = monitor.MonitorSafetyGuard({"monitor": {"max_consecutive_page_failures": 2}})
            with patch.object(monitor, "get_db", side_effect=open_db):
                guard.record_page_failure()
                with self.assertRaises(monitor.MonitorRiskDetected) as raised:
                    guard.record_page_failure()

            verify_db = get_db(db_path)
            try:
                event = dict(verify_db.execute("SELECT event_type, detail FROM risk_events").fetchone())
            finally:
                verify_db.close()

        self.assertEqual(raised.exception.kind, "consecutive_page_failures")
        self.assertEqual(event["event_type"], "monitor_consecutive_page_failures")

    def test_platform_risk_lock_is_scoped_to_its_own_platform(self):
        """A non-BOSS risk signal must never lock BOSS.

        ``set_platform_safety_lock`` defaults to the BOSS platform. If a Liepin
        captcha were recorded without an explicit platform, it would write a BOSS
        lock and block BOSS delivery and monitoring until the cooldown expired.
        """
        from allin.executor import monitor

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "allin.db"
            get_db(db_path).close()

            def open_db():
                return get_db(db_path)

            with patch.object(monitor, "get_db", side_effect=open_db):
                monitor._record_monitor_risk("captcha", {"_monitor_platform": "liepin"})

            verify_db = get_db(db_path)
            try:
                rows = {
                    str(row["platform"]): str(row["reason"])
                    for row in verify_db.execute(
                        "SELECT platform, reason FROM platform_safety_state"
                    ).fetchall()
                }
            finally:
                verify_db.close()

        self.assertEqual(rows.get("liepin"), "captcha")
        self.assertNotIn("boss", rows, "a Liepin captcha must not create a BOSS lock")

    def test_boss_risk_lock_still_targets_boss(self):
        """The BOSS platform scope must keep working after the fix."""
        from allin.executor import monitor

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "allin.db"
            get_db(db_path).close()

            def open_db():
                return get_db(db_path)

            with patch.object(monitor, "get_db", side_effect=open_db):
                monitor._record_monitor_risk("rate_limit", {"_monitor_platform": "boss"})

            verify_db = get_db(db_path)
            try:
                row = verify_db.execute(
                    "SELECT platform, reason FROM platform_safety_state"
                ).fetchone()
            finally:
                verify_db.close()

        self.assertEqual(str(row["platform"]), "boss")
        self.assertEqual(str(row["reason"]), "rate_limit")

    def test_own_greeting_preview_is_not_counted_as_hr_reply(self):
        """A conversation whose newest message is our own greeting is not a reply.

        The chat-list preview shows the newest message. For a freshly greeted job
        that is our own outbound greeting, so treating it as an HR reply both fakes
        a reply and flips the job to `replied`.
        """
        from allin.executor import monitor

        greeting = "您好，我对这个岗位很感兴趣，之前做过相关项目。"
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "allin.db"
            db = get_db(db_path)
            try:
                insert_job(db, _job("own"))
                db.execute("UPDATE jobs SET greeting = ? WHERE id = ?", (greeting, "own"))
                db.commit()
                update_job_status(db, "own", "sent")
            finally:
                db.close()

            def open_db():
                return get_db(db_path)

            jobs = [dict(get_db(db_path).execute("SELECT * FROM jobs WHERE id='own'").fetchone())]
            get_db(db_path).close()

            list_payload = json.dumps({
                "success": True,
                "results": [{
                    "index": 0,
                    "raw_text": f"公司-own 岗位-own {greeting}",
                    "title": "岗位-own",
                    "last_message": greeting,
                    "has_unread": False,
                    "has_reply": None,
                }],
            })

            with patch.object(monitor, "get_db", side_effect=open_db), \
                 patch.object(monitor, "_open_monitor_tab", return_value="chat-target"), \
                 patch.object(monitor, "_wait_or_stop", return_value=False), \
                 patch.object(monitor, "_wait_for_page_or_stop", return_value=True), \
                 patch.object(monitor, "evaluate", return_value=list_payload), \
                 patch.object(monitor, "close_tab"):
                results = monitor._check_platform_replies("liepin", "https://x.test/chat", {}, jobs)

            verify_db = get_db(db_path)
            try:
                status = str(verify_db.execute("SELECT status FROM jobs WHERE id='own'").fetchone()["status"])
                hr_events = verify_db.execute(
                    "SELECT COUNT(*) AS c FROM history WHERE job_id='own' AND action='hr_reply_detected'"
                ).fetchone()["c"]
            finally:
                verify_db.close()

        self.assertEqual(status, "sent", "own greeting must not flip the job to replied")
        self.assertEqual(hr_events, 0, "own greeting must not be recorded as an HR reply")
        self.assertTrue(results and results[0]["conversation"]["has_reply"] is False)

    def test_platform_chat_urls_are_configurable_and_corrected(self):
        """Entry points come from one source and honour config overrides."""
        from allin.executor import monitor

        # The previously broken hardcoded URLs must be gone.
        self.assertEqual(monitor.PLATFORM_CHAT_URLS["zhilian"], "https://i.zhaopin.com/im")
        self.assertNotIn("im.zhaopin.com", monitor.PLATFORM_CHAT_URLS["zhilian"])
        # Overrides win.
        self.assertEqual(
            monitor._platform_chat_url("zhilian", {"monitor": {"zhilian_chat_url": "https://custom.test/im"}}),
            "https://custom.test/im",
        )
        self.assertEqual(
            monitor._platform_chat_url("boss", {"monitor": {"chat_url": "https://boss.test/chat"}}),
            "https://boss.test/chat",
        )
        # Defaults are used when no override exists.
        self.assertEqual(
            monitor._platform_chat_url("51job", {}),
            monitor.PLATFORM_CHAT_URLS["51job"],
        )

    def test_unverified_platform_reports_instead_of_silently_empty(self):
        """A platform without verified selectors must say so, not look like an empty inbox.

        Silence is what previously made dead platforms appear healthy: the generic
        selector set matched nothing and the caller concluded "no replies".
        """
        from allin.executor import monitor

        js = monitor._build_list_extractor_js("51job")
        self.assertIn("selectors_unverified", js)
        # Zhilian has verified selectors, so it must NOT take that branch.
        zl = monitor._build_list_extractor_js("zhilian")
        self.assertNotIn("selectors_unverified: true", zl)
        self.assertIn(".im-session-item", zl)

    def test_zhilian_list_extractor_uses_verified_field_selectors(self):
        """Zhilian rows expose discrete fields; the extractor must read those."""
        from allin.executor import monitor

        js = monitor._build_list_extractor_js("zhilian")
        for sel in (
            ".im-session-item__name",
            ".im-session-item__company-name",
            ".im-session-item__job",
            ".im-session-item__preview-text",
        ):
            self.assertIn(sel, js)

    def test_zhilian_conversation_reader_uses_position_for_direction(self):
        """Zhilian has no self/other class, so direction comes from layout position."""
        from allin.executor import monitor

        js = monitor._conversation_extractor_js("zhilian")
        self.assertIn(".im-message", js)
        self.assertIn("panelCenter", js)
        self.assertIn("im-message--custom", js)
        # Zhilian nests `.im-message` inside `.im-message`; without de-duplication
        # each message is read twice (verified live: 2 real messages came out as 4).
        self.assertIn("other.contains(el)", js)
        # Other platforms still fall back to the BOSS-shaped reader.
        self.assertIs(
            monitor._conversation_extractor_js("51job"),
            monitor.JS_EXTRACT_CONVERSATION,
        )

    def test_zhilian_resume_request_card_is_detected(self):
        """Zhilian asks for the resume with a consent card, not attachment wording.

        Live wording: "我想要一份你的简历，你是否同意？" with 拒绝/同意 actions.
        """
        from allin.executor import monitor

        card = "我想要一份你的简历，你是否同意？ 拒绝 同意"
        self.assertTrue(monitor._looks_like_resume_request_card(card))
        # It is HR's request even though the extractor cannot label the sender.
        reconciled = monitor._reconcile_conversation_messages(
            [{"sender": "unknown", "text": card, "kind": "custom_card"}],
            {"greeting": "这是一段足够长的个性化招呼语用于比对测试"},
        )
        self.assertEqual(reconciled[0]["sender"], "hr")
        self.assertTrue(monitor._detect_resume_request(reconciled))
        # A rejection mentioning 简历-like context must not be read as a request.
        self.assertFalse(
            monitor._detect_resume_request([
                {"sender": "hr", "text": "很遗憾，您与该岗位不太符合", "kind": "message"}
            ])
        )

    def test_zhilian_send_uses_its_own_composer(self):
        """Each platform needs its own send script; using the wrong one fails silently."""
        from allin.executor import monitor

        zl = monitor._send_message_js("zhilian", "你好")
        self.assertIn("textarea.im-sender__input", zl)
        boss = monitor._send_message_js("boss", "你好")
        self.assertIn("#chat-input", boss)
        self.assertNotIn("im-sender__input", boss)


class FullFlowMonitorCooldownTests(unittest.TestCase):
    def test_full_flow_initial_cooldown_is_cancellable_before_first_scan(self):
        from allin.web.tasks import WorkbenchTask, wait_for_initial_monitor_cooldown

        task = WorkbenchTask(id="cooldown", mode="full", label="运行全流程")
        result = []

        worker = Thread(
            target=lambda: result.append(
                wait_for_initial_monitor_cooldown(
                    task,
                    {"monitor": {"initial_cooldown_minutes": 1}},
                    lambda current_task, message: current_task.logs.append(message),
                )
            )
        )
        worker.start()
        deadline = time.monotonic() + 1
        while not task.logs and time.monotonic() < deadline:
            time.sleep(0.01)
        task.stop_requested.set()
        worker.join(timeout=0.5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [True])
        self.assertIn("首次监测冷却已取消", task.logs)


class LiepinReplyMonitorTests(unittest.TestCase):
    """Liepin keeps conversations inside the job page's chat modal (verified live)."""

    def _liepin_job(self, job_id: str = "lp-1", greeting: str = "") -> dict:
        job = _job(job_id, hr_name="")
        job["source_platform"] = "liepin"
        job["greeting"] = greeting
        job["url"] = f"https://www.liepin.com/job/{job_id}.shtml"
        return job

    def test_liepin_uses_its_own_conversation_reader(self):
        """The BOSS-shaped reader only understands BOSS DOM and would silently read nothing."""
        from allin.executor import monitor

        js = monitor._conversation_extractor_js("liepin")
        self.assertIn(".im-ui-chat-modal-container", js)
        self.assertIn("im-ui-message-item-send", js)
        self.assertIsNot(js, monitor.JS_EXTRACT_CONVERSATION)
        # Zhilian must keep its own verified reader (its list selector lives in
        # PLATFORM_LIST_SELECTORS, while the conversation reader uses `.im-message`).
        self.assertIn(".im-message", monitor._conversation_extractor_js("zhilian"))
        # Still-unverified platforms keep falling back to the BOSS reader.
        self.assertIs(
            monitor._conversation_extractor_js("51job"),
            monitor.JS_EXTRACT_CONVERSATION,
        )

    def test_every_liepin_job_gets_visited_across_cycles(self):
        """Liepin pays one page visit per job, so the cap must rotate, not repeat.

        Taking `tracked_jobs[:max_jobs]` every cycle re-checked the same first jobs
        and left every job behind them permanently unvisited.
        """
        from allin.db import get_db, set_monitor_cursor
        from allin.executor import monitor

        jobs = [self._liepin_job(f"lp-{i}") for i in range(12)]
        with tempfile.TemporaryDirectory() as tmp:
            db = get_db(Path(tmp) / "data" / "allin.db")
            try:
                visited: list[str] = []
                for _ in range(4):
                    window, _remaining = monitor._liepin_cycle_window(db, jobs, 5)
                    ids = [job["id"] for job in window]
                    visited.extend(ids)
                    set_monitor_cursor(db, "liepin", ids[-1])
            finally:
                db.close()

        # Four cycles of 5 cover all 12 jobs (with wrap-around), and every job is seen.
        self.assertEqual(sorted(set(visited), key=lambda value: int(value.split("-")[1])),
                         [f"lp-{i}" for i in range(12)])

    def test_liepin_cycle_window_wraps_and_reports_remaining(self):
        """The window wraps at the end so a cycle is never short-changed."""
        from allin.db import get_db, set_monitor_cursor
        from allin.executor import monitor

        jobs = [self._liepin_job(f"lp-{i}") for i in range(7)]
        with tempfile.TemporaryDirectory() as tmp:
            db = get_db(Path(tmp) / "data" / "allin.db")
            try:
                # Cursor sits on the last job: the next window must wrap to the start.
                set_monitor_cursor(db, "liepin", "lp-6")
                window, remaining = monitor._liepin_cycle_window(db, jobs, 3)
                self.assertEqual([job["id"] for job in window], ["lp-0", "lp-1", "lp-2"])
                self.assertEqual(remaining, 4)
                # A stale cursor naming an unknown job must not lose the cycle.
                set_monitor_cursor(db, "liepin", "lp-gone")
                window, remaining = monitor._liepin_cycle_window(db, jobs, 3)
                self.assertEqual([job["id"] for job in window], ["lp-0", "lp-1", "lp-2"])
                self.assertEqual(remaining, 4)
                # No cursor yet: start at the top.
                set_monitor_cursor(db, "liepin", "")
                window, remaining = monitor._liepin_cycle_window(db, jobs, 3)
                self.assertEqual([job["id"] for job in window], ["lp-0", "lp-1", "lp-2"])
                self.assertEqual(remaining, 4)
            finally:
                db.close()

    def test_liepin_cursor_advances_past_jobs_without_replies(self):
        """A silent job must not block the ones behind it from being checked."""
        from allin.db import get_db, get_monitor_cursor, set_monitor_cursor
        from allin.executor import monitor

        jobs = [self._liepin_job(f"lp-{i}") for i in range(4)]
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "allin.db"

            def open_db():
                return get_db(db_path)

            config = {"monitor": {"max_conversations_per_cycle": 2}}
            with patch.object(monitor, "_check_liepin_job_reply", return_value=None), \
                 patch.object(monitor, "get_db", side_effect=open_db), \
                 patch.object(monitor, "close_tab"):
                monitor._check_liepin_replies(config, jobs)
                # Second cycle must move on rather than repeat the first two.
                monitor._check_liepin_replies(config, jobs)

            verify = open_db()
            try:
                self.assertEqual(get_monitor_cursor(verify, "liepin"), "lp-3")
            finally:
                verify.close()

    def test_own_greeting_alone_is_not_reported_as_a_reply(self):
        """A conversation whose newest message is our own greeting has no HR reply."""
        from allin.executor import monitor

        greeting = "您好，我看了岗位描述，我的相关经验比较匹配，方便聊聊吗？"
        job = self._liepin_job(greeting=greeting)
        messages = json.dumps([
            {"sender": "system", "text": "求职过程中如遇收取费用请举报", "kind": "message"},
            {"sender": "me", "text": greeting, "kind": "message"},
        ])
        with patch.object(monitor, "_open_monitor_tab", return_value="tab"), \
             patch.object(monitor, "_wait_or_stop", return_value=False), \
             patch.object(monitor, "_wait_for_page_or_stop", return_value=True), \
             patch.object(monitor, "_inspect_monitor_page"), \
             patch.object(monitor, "evaluate", side_effect=[
                 json.dumps({"status": "ok", "history_readable": True}), messages,
             ]), \
             patch.object(monitor, "close_tab"):
            result = monitor._check_liepin_job_reply(job, {"monitor": {}}, MagicMock())

        self.assertIsNone(result)

    def test_hr_message_after_our_greeting_is_reported(self):
        """The receive branch (a body tile without the `send` marker) is HR's message."""
        from allin.executor import monitor

        greeting = "您好，我看了岗位描述，我的相关经验比较匹配，方便聊聊吗？"
        job = self._liepin_job(greeting=greeting)
        job["status"] = "sent"
        hr_message = "方便发一份简历过来吗？"
        messages = json.dumps([
            {"sender": "me", "text": greeting, "kind": "message"},
            {"sender": "hr", "text": hr_message, "kind": "message"},
        ])
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None
        with patch.object(monitor, "_open_monitor_tab", return_value="tab"), \
             patch.object(monitor, "_wait_or_stop", return_value=False), \
             patch.object(monitor, "_wait_for_page_or_stop", return_value=True), \
             patch.object(monitor, "_inspect_monitor_page"), \
             patch.object(monitor, "update_job_status") as update_status, \
             patch.object(monitor, "add_history") as add_history_mock, \
             patch.object(monitor, "evaluate", side_effect=[
                 json.dumps({"status": "ok", "history_readable": True}), messages,
             ]), \
             patch.object(monitor, "close_tab"):
            result = monitor._check_liepin_job_reply(job, {"monitor": {}}, db)

        self.assertIsNotNone(result)
        self.assertEqual(result["conversation"]["last_message"], hr_message)
        # The job must actually move out of `sent`.
        update_status.assert_called_once_with(db, job["id"], "replied")
        add_history_mock.assert_called_once()

    def test_unreadable_history_is_skipped_instead_of_guessed(self):
        """Liepin hides some history; guessing there could fake a reply."""
        from allin.executor import monitor

        job = self._liepin_job()
        with patch.object(monitor, "_open_monitor_tab", return_value="tab"), \
             patch.object(monitor, "_wait_or_stop", return_value=False), \
             patch.object(monitor, "_wait_for_page_or_stop", return_value=True), \
             patch.object(monitor, "_inspect_monitor_page"), \
             patch.object(monitor, "evaluate", return_value=json.dumps(
                 {"status": "ok", "history_readable": False}
             )) as evaluate_mock, \
             patch.object(monitor, "close_tab"):
            result = monitor._check_liepin_job_reply(job, {"monitor": {}}, MagicMock())

        self.assertIsNone(result)
        # Must not even attempt to read messages from a hidden history.
        self.assertEqual(evaluate_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
