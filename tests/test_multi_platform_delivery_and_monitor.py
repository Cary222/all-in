"""Tests for 51job and Liepin delivery adapters and multi-platform monitor dispatch."""

import json
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from allin.executor.monitor import (
    _check_job51_replies,
    _check_liepin_replies,
    _open_conversation,
    _open_conversation_from_chat_list,
    check_replies,
)
from allin.executor.sender import (
    Job51Sender,
    LiepinSender,
    PLATFORM_SENDERS,
    _send_job51_greeting_once,
    _send_liepin_greeting_once,
    _send_zhilian_greeting_once,
    get_sender,
)


class MultiPlatformSenderDispatchTests(TestCase):
    """Test sender factory and registration for 51job and liepin."""

    def test_platform_senders_contains_all_four_platforms(self):
        self.assertIn("boss", PLATFORM_SENDERS)
        self.assertIn("zhilian", PLATFORM_SENDERS)
        self.assertIn("51job", PLATFORM_SENDERS)
        self.assertIn("liepin", PLATFORM_SENDERS)

    def test_get_sender_returns_expected_classes(self):
        cfg = {"daily_limit": 10}
        self.assertIsInstance(get_sender("51job", cfg), Job51Sender)
        self.assertIsInstance(get_sender("liepin", cfg), LiepinSender)


class ZhilianGreetingOnceTests(TestCase):
    """Unit tests for the Zhilian-specific delivery state machine."""

    @patch("allin.executor.sender._sleep_or_stop", return_value=False)
    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-zl")
    def test_zhilian_waits_for_real_apply_button_and_success_modal(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
        mock_sleep,
    ):
        job = {"id": "zhilian:1", "url": "https://www.zhaopin.com/jobdetail/1.htm", "greeting": "Hello"}
        mock_eval.side_effect = [
            json.dumps({"success": False, "error": "action_button_waiting"}),
            json.dumps({"success": True, "action": "clicked", "button_type": "apply"}),
            json.dumps({"success": False, "verified": False, "status_text": "waiting"}),
            json.dumps({
                "success": True,
                "verified": True,
                "status_text": "已向对方发送简历和打招呼语",
            }),
        ]

        res, target = _send_zhilian_greeting_once(
            job,
            "Hello",
            {
                "browse_before_greet": False,
                "_zhilian_action_attempts": 3,
                "_zhilian_status_attempts": 3,
            },
        )

        self.assertTrue(res["success"])
        self.assertTrue(res.get("verified"))
        self.assertIn(".summary-planes__action", mock_eval.call_args_list[0].args[1])
        self.assertIn(".deliver-greeting-modal", mock_eval.call_args_list[2].args[1])
        self.assertEqual(mock_eval.call_count, 4)
        mock_close.assert_called_once_with("tab-zl")

    @patch("allin.executor.sender._sleep_or_stop", return_value=False)
    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-zl")
    def test_zhilian_resume_picker_targets_the_matched_resume(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
        mock_sleep,
    ):
        """The picker must be driven by the job's matched resume, then delivery verified."""
        job = {
            "id": "zhilian:resume",
            "url": "https://www.zhaopin.com/jobdetail/r.htm",
            "greeting": "Hello",
            "matched_resume_name": "刘屹鹏的简历（App）",
        }
        mock_eval.side_effect = [
            json.dumps({"success": True, "action": "clicked", "button_type": "apply"}),
            json.dumps({
                "success": True, "verified": False,
                "step": "resume_selected", "selected": "刘屹鹏的简历（App）",
            }),
            json.dumps({
                "success": True, "verified": True,
                "status_text": "已向对方发送简历和打招呼语",
            }),
        ]

        res, target = _send_zhilian_greeting_once(
            job,
            "Hello",
            {"browse_before_greet": False, "_zhilian_status_attempts": 3},
        )

        self.assertTrue(res["success"])
        self.assertTrue(res.get("verified"))
        status_script = mock_eval.call_args_list[1].args[1]
        self.assertIn("刘屹鹏的简历（App）", status_script)
        self.assertIn("resume-select", status_script)

    @patch("allin.executor.sender._sleep_or_stop", return_value=False)
    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-zl")
    def test_zhilian_resume_picker_without_target_resume_fails_closed(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
        mock_sleep,
    ):
        """An unresolved resume picker must abort rather than send an arbitrary resume."""
        job = {
            "id": "zhilian:nopick",
            "url": "https://www.zhaopin.com/jobdetail/n.htm",
            "greeting": "Hello",
        }
        mock_eval.side_effect = [
            json.dumps({"success": True, "action": "clicked", "button_type": "apply"}),
            json.dumps({
                "success": False,
                "error": "zhilian_resume_picker_unresolved",
                "history_detail": "智联弹出简历选择框，但未指定目标简历，已停止以免投递错误简历",
                "skip_backoff": True,
            }),
        ]

        res, target = _send_zhilian_greeting_once(
            job,
            "Hello",
            {"browse_before_greet": False, "_zhilian_status_attempts": 3},
        )

        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "zhilian_resume_picker_unresolved")
        self.assertTrue(res.get("skip_backoff"))
        self.assertEqual(mock_eval.call_count, 2)
        mock_close.assert_called_once_with("tab-zl")

    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-zl")
    def test_zhilian_similar_jobs_only_is_unavailable_not_selector_error(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
    ):
        job = {"id": "zhilian:2", "url": "https://www.zhaopin.com/jobdetail/2.htm", "greeting": "Hello"}
        mock_eval.return_value = json.dumps({
            "success": False,
            "error": "job_page_unavailable",
            "history_detail": "智联岗位已停止招聘，详情页仅提供相似职位",
            "skip_backoff": True,
        })

        res, target = _send_zhilian_greeting_once(job, "Hello", {"browse_before_greet": False})

        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "job_page_unavailable")
        self.assertNotEqual(res["error"], "no_action_button")
        self.assertIn("查看更多相似职位", mock_eval.call_args.args[1])
        mock_close.assert_called_once_with("tab-zl")


class Job51GreetingOnceTests(TestCase):
    """Unit tests for _send_job51_greeting_once."""

    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-51")
    def test_job51_already_applied(self, mock_new_tab, mock_eval, mock_wait, mock_close):
        job = {"id": "51job:1", "url": "https://jobs.51job.com/1.html", "greeting": "Hello"}
        mock_eval.return_value = json.dumps({
            "success": True,
            "already_sent": True,
            "verified": True,
            "history_detail": "岗位已处于已投递或沟通中状态",
        })
        res, target = _send_job51_greeting_once(job, "Hello", {"browse_before_greet": False})
        self.assertTrue(res["success"])
        self.assertTrue(res.get("already_sent"))
        mock_close.assert_called_once_with("tab-51")

    @patch("allin.executor.sender._sleep_or_stop", return_value=False)
    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-51")
    def test_job51_successful_apply(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
        mock_sleep,
    ):
        job = {"id": "51job:2", "url": "https://jobs.51job.com/2.html", "greeting": "Hello"}
        mock_eval.side_effect = [
            json.dumps({"success": True, "action": "clicked", "button_type": "apply"}),
            json.dumps({"success": True, "verified": False, "step": "resume_confirmed"}),
            json.dumps({"success": True, "verified": False, "step": "attachment_sent"}),
            json.dumps({"success": True, "verified": True, "status_text": "success-popup-2"}),
        ]
        res, target = _send_job51_greeting_once(
            job,
            "Hello",
            {"browse_before_greet": False, "_job51_apply_state_attempts": 4},
        )
        self.assertTrue(res["success"])
        self.assertTrue(res.get("verified"))
        self.assertIn(".jobapply-wrapper .apply-btn-new", mock_eval.call_args_list[0].args[1])
        self.assertIn(".apply-component-resume-dialog", mock_eval.call_args_list[1].args[1])
        self.assertIn(".attachment_resume_dialog", mock_eval.call_args_list[1].args[1])
        self.assertIn(".success-popup-2", mock_eval.call_args_list[1].args[1])
        self.assertEqual(mock_eval.call_count, 4)
        mock_close.assert_called_once_with("tab-51")


class LiepinGreetingOnceTests(TestCase):
    """Unit tests for _send_liepin_greeting_once."""

    @patch("allin.executor.sender._sleep_or_stop", return_value=False)
    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-lp")
    def test_liepin_already_delivered_is_not_resent(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
        mock_sleep,
    ):
        """A greeting bubble already present (before we type) must skip re-sending.

        The job-page button text only reports whether a conversation exists, so
        "already sent" can only be proven inside the chat dialog. This test pins
        that contract: the dialog reports the bubble as pre-existing, and the
        result must be marked ``already_sent`` without filling or clicking send.
        """
        job = {"id": "liepin:1", "url": "https://www.liepin.com/job/1.shtml", "greeting": "Hello"}
        mock_eval.side_effect = [
            json.dumps({
                "success": True,
                "action": "clicked",
                "button_type": "chat",
                "button_text": "继续聊",
                "existing_chat": True,
            }),
            json.dumps({
                "success": True,
                "verified": True,
                "already_sent": True,
                "status_text": "ai_greeting_already_delivered",
                "sent_message": "Hello",
            }),
        ]

        res, target = _send_liepin_greeting_once(
            job,
            "Hello",
            {"browse_before_greet": False, "_liepin_chat_state_attempts": 4},
        )

        self.assertTrue(res["success"])
        self.assertTrue(res.get("already_sent"))
        self.assertIn("未重复发送", res["history_detail"])
        self.assertIn("a.btn-main", mock_eval.call_args_list[0].args[1])
        self.assertIn("继续聊", mock_eval.call_args_list[0].args[1])
        # The dialog probe must distinguish "sent in this run" from "sent earlier".
        self.assertIn("__allinPendingLiepinGreeting", mock_eval.call_args_list[1].args[1])
        self.assertIn("ai_greeting_already_delivered", mock_eval.call_args_list[1].args[1])
        self.assertEqual(mock_eval.call_count, 2)
        mock_close.assert_called_once_with("tab-lp")

    @patch("allin.executor.sender._sleep_or_stop", return_value=False)
    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-lp")
    def test_liepin_successful_greet_requires_ai_message_bubble(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
        mock_sleep,
    ):
        job = {"id": "liepin:2", "url": "https://www.liepin.com/job/2.shtml", "greeting": "Hi HR"}
        mock_eval.side_effect = [
            json.dumps({
                "success": True,
                "action": "clicked",
                "button_type": "chat",
                "button_text": "继续聊",
                "existing_chat": True,
            }),
            # “继续聊”与平台默认问候都不能作为成功凭证。
            json.dumps({"success": True, "verified": False, "step": "waiting_chat_dialog"}),
            json.dumps({"success": True, "verified": False, "step": "greeting_filled"}),
            json.dumps({"success": True, "verified": False, "step": "waiting_send_enabled"}),
            json.dumps({"success": True, "verified": False, "step": "send_clicked"}),
            json.dumps({"success": True, "verified": False, "step": "waiting_message_verification"}),
            json.dumps({
                "success": True,
                "verified": True,
                "status_text": "ai_greeting_message_present",
                "sent_message": "Hi HR",
            }),
        ]
        res, target = _send_liepin_greeting_once(
            job,
            "Hi HR",
            {"browse_before_greet": False, "_liepin_chat_state_attempts": 8},
        )
        self.assertTrue(res["success"])
        self.assertTrue(res.get("verified"))
        self.assertEqual(res["history_detail"], "猎聘 AI 招呼语已发送并在消息气泡中验证")
        confirm_script = mock_eval.call_args_list[1].args[1]
        self.assertIn("textarea.im-ui-textarea", confirm_script)
        self.assertIn("button.im-ui-basic-send-btn", confirm_script)
        self.assertIn("im-ui-message-item-body.im-ui-message-item-send", confirm_script)
        self.assertIn("=== normalizedGreeting", confirm_script)
        self.assertIn("ai_greeting_message_present", confirm_script)
        self.assertIn("window.__allinPendingLiepinGreeting", confirm_script)
        self.assertEqual(mock_eval.call_count, 7)
        mock_close.assert_called_once_with("tab-lp")

    @patch("allin.executor.sender._sleep_or_stop", return_value=False)
    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-lp")
    def test_liepin_waits_for_spa_action_button(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
        mock_sleep,
    ):
        job = {"id": "liepin:3", "url": "https://www.liepin.com/job/3.shtml", "greeting": "Hi HR"}
        mock_eval.side_effect = [
            json.dumps({"success": False, "error": "action_button_waiting"}),
            json.dumps({"success": False, "error": "action_button_waiting"}),
            json.dumps({"success": True, "action": "clicked", "button_type": "chat", "button_text": "聊一聊"}),
            json.dumps({"success": True, "verified": True, "status_text": "继续聊"}),
        ]

        res, target = _send_liepin_greeting_once(
            job,
            "Hi HR",
            {"browse_before_greet": False, "_liepin_action_attempts": 4},
        )

        self.assertTrue(res["success"])
        self.assertTrue(res.get("verified"))
        click_script = mock_eval.call_args_list[0].args[1]
        confirm_script = mock_eval.call_args_list[3].args[1]
        self.assertIn("section.job-apply-container", click_script)
        self.assertIn('a.btn-main[data-selector="chat-chat"]', click_script)
        self.assertNotIn("document.querySelectorAll('span, div')", click_script)
        self.assertIn("ai_greeting_message_present", confirm_script)
        self.assertIn("button.im-ui-basic-send-btn", confirm_script)
        self.assertEqual(mock_eval.call_count, 4)
        mock_close.assert_called_once_with("tab-lp")

    @patch("allin.executor.sender._sleep_or_stop", return_value=False)
    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-lp")
    def test_liepin_render_timeout_has_its_own_error_code(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
        mock_sleep,
    ):
        """A never-rendering entry point must not be reported as a missing button.

        "The SPA never rendered the chat entry" (slow load or selector drift) needs
        different diagnosis from "the page rendered and genuinely has no such
        button" (e.g. withdrawn job), so the timeout keeps its own error code.
        """
        job = {"id": "liepin:timeout", "url": "https://www.liepin.com/job/t.shtml", "greeting": "Hi HR"}
        mock_eval.return_value = json.dumps({
            "success": False,
            "error": "action_button_waiting",
            "history_detail": "等待猎聘右上角聊一聊按钮渲染",
        })

        res, target = _send_liepin_greeting_once(
            job,
            "Hi HR",
            {"browse_before_greet": False, "_liepin_action_attempts": 3},
        )

        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "liepin_action_button_timeout")
        self.assertNotEqual(res["error"], "no_action_button")
        self.assertTrue(res.get("skip_backoff"))
        mock_close.assert_called_once_with("tab-lp")

    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-lp")
    def test_liepin_cross_border_authorization_stops_retry(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
    ):
        job = {"id": "liepin:cross-border", "url": "https://www.liepin.com/job/5.shtml", "greeting": "Hi HR"}
        mock_eval.side_effect = [
            json.dumps({"success": True, "action": "clicked", "button_type": "chat", "button_text": "聊一聊"}),
            json.dumps({
                "success": False,
                "error": "liepin_cross_border_authorization_required",
                "history_detail": "猎聘招聘方位于境外，需人工确认简历跨境查阅授权，已停止自动重试",
                "skip_backoff": True,
            }),
            json.dumps({"success": False, "verified": False}),
        ]

        res, target = _send_liepin_greeting_once(job, "Hi HR", {"browse_before_greet": False})

        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "liepin_cross_border_authorization_required")
        self.assertTrue(res.get("skip_backoff"))
        self.assertIn("job-overseas-authorize-modal", mock_eval.call_args_list[1].args[1])
        mock_close.assert_called_once_with("tab-lp")

    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-lp")
    def test_liepin_security_center_is_blocked_not_missing_button(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
    ):
        job = {"id": "liepin:4", "url": "https://www.liepin.com/job/4.shtml", "greeting": "Hi HR"}
        mock_eval.return_value = json.dumps({
            "success": False,
            "error": "blocked",
            "history_detail": "猎聘出现验证码或访问限制",
        })

        res, target = _send_liepin_greeting_once(job, "Hi HR", {"browse_before_greet": False})

        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "blocked")
        self.assertNotEqual(res["error"], "no_action_button")
        self.assertNotIn("skip_backoff", res)
        self.assertIn("safe.liepin.com", mock_eval.call_args.args[1])
        mock_close.assert_called_once_with("tab-lp")

    @patch("allin.executor.sender._sleep_or_stop", return_value=False)
    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-lp")
    def test_liepin_unreadable_history_is_fail_closed(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
        mock_sleep,
    ):
        """Unreadable chat history must abort the send instead of risking a re-send.

        Liepin replaces some historical messages with a placeholder such as
        "不支持此消息查看，请登录猎聘APP查看消息内容". When the history cannot be read
        we cannot prove whether the AI greeting was already delivered, and sending
        again would message the same real HR twice with no way to undo it. The
        sender must therefore refuse (fail closed) rather than proceed.
        """
        job = {
            "id": "liepin:unreadable",
            "url": "https://www.liepin.com/job/u.shtml",
            "greeting": "Hi HR",
            "company": "目标公司",
            "title": "目标岗位",
        }
        mock_eval.side_effect = [
            json.dumps({
                "success": True,
                "action": "clicked",
                "button_type": "chat",
                "button_text": "继续聊",
                "existing_chat": True,
            }),
            json.dumps({
                "success": False,
                "error": "liepin_history_not_readable",
                "history_detail": "猎聘会话历史含不可读消息，无法确认 AI 招呼语是否已送达，已停止发送以免重复打扰",
                "skip_backoff": True,
            }),
        ]

        res, target = _send_liepin_greeting_once(
            job,
            "Hi HR",
            {"browse_before_greet": False, "_liepin_chat_state_attempts": 4},
        )

        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "liepin_history_not_readable")
        self.assertTrue(res.get("skip_backoff"))
        # The guard must be part of the dialog probe, checked against the job identity.
        probe = mock_eval.call_args_list[1].args[1]
        self.assertIn("不支持此消息查看", probe)
        self.assertIn("liepin_history_not_readable", probe)
        self.assertEqual(mock_eval.call_count, 2)
        mock_close.assert_called_once_with("tab-lp")

    @patch("allin.executor.sender._sleep_or_stop", return_value=False)
    @patch("allin.executor.sender.close_tab")
    @patch("allin.executor.sender.wait_for_load")
    @patch("allin.executor.sender.evaluate")
    @patch("allin.executor.sender.new_tab", return_value="tab-lp")
    def test_liepin_dialog_must_belong_to_target_job(
        self,
        mock_new_tab,
        mock_eval,
        mock_wait,
        mock_close,
        mock_sleep,
    ):
        """A chat dialog that never belongs to the target job must not be typed into.

        Liepin can render several conversation containers at once (e.g. the drawer
        of a previous chat). Sending the AI greeting into the wrong one would
        message an unrelated HR. The dialog probe therefore reports a mismatch as a
        *retryable* waiting state (the target dialog may render slightly later), and
        only fails once every attempt still points at another HR.
        """
        job = {
            "id": "liepin:9",
            "url": "https://www.liepin.com/job/9.shtml",
            "greeting": "Hi HR",
            "company": "目标公司",
            "title": "目标岗位",
        }
        mismatch = json.dumps({
            "success": True,
            "verified": False,
            "step": "waiting_target_conversation",
            "identity_mismatch": True,
        })
        mock_eval.side_effect = [
            json.dumps({
                "success": True,
                "action": "clicked",
                "button_type": "chat",
                "button_text": "继续聊",
                "existing_chat": True,
            }),
            mismatch,
            mismatch,
        ]

        res, target = _send_liepin_greeting_once(
            job,
            "Hi HR",
            {"browse_before_greet": False, "_liepin_chat_state_attempts": 2},
        )

        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "liepin_conversation_mismatch")
        self.assertTrue(res.get("skip_backoff"))
        # The guard must be built from the job identity and run before typing.
        guard_script = mock_eval.call_args_list[1].args[1]
        self.assertIn("目标公司", guard_script)
        self.assertIn("目标岗位", guard_script)
        self.assertIn("identity_mismatch", guard_script)
        self.assertEqual(mock_eval.call_count, 3)
        mock_close.assert_called_once_with("tab-lp")


class MultiPlatformMonitorDispatchTests(TestCase):
    """Test monitor platform dispatch and URL routing."""

    @patch("allin.executor.monitor._open_monitor_tab", return_value="target-51")
    @patch("allin.executor.monitor._wait_for_page_or_stop", return_value=True)
    @patch("allin.executor.monitor._inspect_monitor_page")
    @patch("allin.executor.monitor.evaluate")
    def test_open_conversation_from_chat_list_51job(self, mock_eval, mock_inspect, mock_wait, mock_open):
        mock_eval.return_value = json.dumps({"success": True})
        job = {"source_platform": "51job", "company": "测试公司", "hr_name": "张经理"}
        cfg = {"monitor": {}}
        tid = _open_conversation_from_chat_list(job, cfg)
        self.assertEqual(tid, "target-51")
        mock_open.assert_called_once()
        args, _ = mock_open.call_args
        self.assertEqual(args[0], "https://we.51job.com/pc/message")

    @patch("allin.executor.monitor._open_monitor_tab", return_value="target-lp")
    @patch("allin.executor.monitor._wait_for_page_or_stop", return_value=True)
    @patch("allin.executor.monitor._inspect_monitor_page")
    @patch("allin.executor.monitor.evaluate")
    def test_open_conversation_from_chat_list_liepin(self, mock_eval, mock_inspect, mock_wait, mock_open):
        mock_eval.return_value = json.dumps({"success": True})
        job = {"source_platform": "liepin", "company": "猎聘公司", "hr_name": "李总"}
        cfg = {"monitor": {}}
        tid = _open_conversation_from_chat_list(job, cfg)
        self.assertEqual(tid, "target-lp")
        mock_open.assert_called_once()
        args, _ = mock_open.call_args
        self.assertEqual(args[0], "https://www.liepin.com/chat/")
