"""Sender module - Auto-send greetings with throttle control."""

import abc
import json
import random
import time
from pathlib import Path
from threading import Event
from urllib.parse import urljoin
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from allin.browser import (
    new_tab,
    close_tab,
    evaluate,
    click_at,
    get_page_targets,
    navigate,
    press_key,
    type_text,
    wait_for_load,
)
from allin.db import (
    get_db, get_jobs_ready_to_send, update_job_status, update_job_last_error,
    add_history, add_risk_event, set_platform_safety_lock, count_sent_today,
)
from allin.collection.capabilities import platform_supports
from allin.throttle import RequestThrottle, SendWindowChecker, ProgressiveBackoff, should_take_day_off
from allin.platform_safety import PlatformAccessGuard, PlatformSafetyStop

console = Console()

CHAT_BUTTON_SELECTOR = (
    'a[redirect-url*="/web/geek/chat"], '
    'a[data-url*="/friend/add"], '
    'a.btn-startchat, '
    '[ka="job_detail_chat"], '
    '[ka^="go_chat"], '
    '[ka*="gochat"], '
    '.op-btn-chat, '
    '.btn-startchat-wrap'
)

# 命中任一即视为岗位已关闭/下架/停止招聘/招满。用于岗位详情页失败时推断真实业务状态。
JOB_CLOSED_MARKERS = (
    "访问的页面不存在", "您访问的页面不存在", "Oops!",
    "职位已关闭", "职位已经关闭", "该职位已关闭", "此职位已关闭", "岗位已关闭",
    "该职位已下线", "该职位已下架", "职位已下线", "职位已下架",
    "该职位已暂停招聘", "职位已暂停招聘", "职位暂停招聘", "停止招聘", "已停止招聘",
    "暂停招聘", "招聘已暂停", "该职位已招满", "职位已招满", "已招满",
    "该职位暂不招人", "暂不招人",
)

CHAT_BUTTON_SCRIPT_FOR_TESTS = """
(() => {
    const selectors = [
        'a[redirect-url*="/web/geek/chat"]',
        'a[data-url*="/friend/add"]',
        'a.btn-startchat',
        '[ka="job_detail_chat"]',
        '[ka^="go_chat"]',
        '[ka*="gochat"]',
        '.op-btn-chat',
        '.btn-startchat-wrap'
    ];
    const candidates = selectors.flatMap((selector, priority) =>
        Array.from(document.querySelectorAll(selector)).map((el) => ({el, selector, priority}))
    );
    const elementState = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        const visible = !!(
            rect.width && rect.height &&
            style.display !== 'none' &&
            style.visibility !== 'hidden' &&
            style.pointerEvents !== 'none'
        );
        const inViewport = visible && rect.bottom > 0 && rect.right > 0 &&
            rect.top < innerHeight && rect.left < innerWidth;
        const x = Math.min(Math.max(rect.x + rect.width / 2, 0), innerWidth - 1);
        const y = Math.min(Math.max(rect.y + rect.height / 2, 0), innerHeight - 1);
        const top = inViewport ? document.elementFromPoint(x, y) : null;
        const topmost = !!(top && (top === el || el.contains(top)));
        return {rect, visible, inViewport, topmost};
    };
    const isVisible = (el) => elementState(el).visible;
    const score = (item) => {
        const el = item.el;
        const text = (el.innerText || el.textContent || '').trim();
        const ka = el.getAttribute('ka') || '';
        const redirectUrl = el.getAttribute('redirect-url') || '';
        const dataUrl = el.getAttribute('data-url') || '';
        const tagName = String(el.tagName || '').toLowerCase();
        let value = 0;
        if (isVisible(el)) value += 1000;
        const state = elementState(el);
        if (state.inViewport) value += 500;
        if (state.topmost) value += 300;
        if (tagName === 'a') value += 200;
        if (redirectUrl.includes('/web/geek/chat')) value += 300;
        if (dataUrl.includes('/friend/add')) value += 250;
        if (el.classList && el.classList.contains('btn-startchat')) value += 120;
        if (text.includes('沟通')) value += 80;
        if (ka === 'job_detail_chat' || ka.includes('go_chat') || ka.includes('gochat')) value += 60;
        if (el.classList && el.classList.contains('btn-startchat-wrap')) value -= 100;
        return value - item.priority;
    };
    const matches = candidates
        .filter((item) => {
            const el = item.el;
            const text = (el.innerText || el.textContent || '').trim();
            const ka = el.getAttribute('ka') || '';
            const redirectUrl = el.getAttribute('redirect-url') || '';
            const dataUrl = el.getAttribute('data-url') || '';
            return (
                text.includes('沟通') ||
                redirectUrl.includes('/web/geek/chat') ||
                dataUrl.includes('/friend/add') ||
                ka === 'job_detail_chat' ||
                ka.includes('go_chat') ||
                ka.includes('gochat')
            );
        })
        .sort((a, b) => score(b) - score(a));
    const btn = matches[0] && matches[0].el;
    if (!btn) return JSON.stringify({
        success: false,
        error: 'no_chat_button',
        candidates: candidates.map((item) => {
            const el = item.el;
            const text = (el.innerText || el.textContent || '').trim();
            return {
                text,
                ka: el.getAttribute('ka'),
                className: String(el.className || ''),
                tagName: el.tagName,
                redirectUrl: el.getAttribute('redirect-url'),
                dataUrl: el.getAttribute('data-url'),
                visible: isVisible(el)
            };
        })
    });
    btn.scrollIntoView({block: 'center', inline: 'center'});
    const rect = btn.getBoundingClientRect();
    btn.click();
    return JSON.stringify({
        success: true,
        interaction: 'dom_click',
        x: rect.x + rect.width / 2,
        y: rect.y + rect.height / 2,
        button_text: (btn.innerText || btn.textContent || '').trim(),
        ka: btn.getAttribute('ka'),
        className: String(btn.className || ''),
        tagName: btn.tagName,
        redirectUrl: btn.getAttribute('redirect-url'),
        dataUrl: btn.getAttribute('data-url'),
        visible: isVisible(btn)
    });
})()
"""


def _parse_js_result(result) -> dict:
    if not result:
        return {"success": False, "error": "no_response"}
    if isinstance(result, dict):
        return result
    try:
        return json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return {"success": False, "error": "parse_error"}


def _stop_requested(stop_event) -> bool:
    return bool(stop_event and stop_event.is_set())


def _sleep_or_stop(seconds: float, stop_event) -> bool:
    if stop_event:
        return bool(stop_event.wait(seconds))
    time.sleep(seconds)
    return False


def _detect_greet_popup(target_id: str) -> dict:
    detect_popup_js = """
    (() => {
        const visible = (element) => element && !!(
            element.offsetWidth || element.offsetHeight || element.getClientRects().length
        );
        const explicitPreset = Array.from(document.querySelectorAll('.greet-boss-pop, .greet-pop'))
            .find((element) => visible(element));
        if (explicitPreset) {
            return JSON.stringify({success: true, popup: true, kind: 'preset_greeting'});
        }

        const startChat = Array.from(document.querySelectorAll('.dialog-wrap.startchat-dialog'))
            .find((element) => visible(element) && element.querySelector('textarea.input-area'));
        if (startChat) {
            return JSON.stringify({success: true, popup: true, kind: 'startchat_dialog'});
        }

        const continueChat = Array.from(document.querySelectorAll(
            '.dialog-wrap, [role="dialog"], .boss-dialog, [class*="dialog"], [class*="modal"]'
        )).find((element) => {
            if (!visible(element)) return false;
            const text = String(element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim();
            return /您与该Boss已沟通过/.test(text) && /是否就新职位.*继续沟通/.test(text);
        });
        if (continueChat) {
            return JSON.stringify({success: true, popup: true, kind: 'continue_chat_dialog'});
        }

        const preset = Array.from(document.querySelectorAll('.dialog-wrap'))
            .find((element) => {
                if (!visible(element)) return false;
                const text = (element.innerText || element.textContent || '').trim();
                const hasEditableGreeting = !!element.querySelector('textarea.input-area');
                return !hasEditableGreeting && /预设招呼语|默认招呼语|自动招呼语|打招呼语/.test(text);
            });
        if (preset) {
            return JSON.stringify({success: true, popup: true, kind: 'preset_greeting'});
        }
        return JSON.stringify({success: true, popup: false, kind: null});
    })()
    """
    return _parse_js_result(evaluate(target_id, detect_popup_js))


def _is_preset_greeting_popup(state: dict) -> bool:
    if state.get("action") == "no_popup":
        return False
    if not state.get("popup"):
        return False
    return state.get("kind") in {None, "preset_greeting"}


def _confirm_preset_greeting(target_id: str) -> dict:
    result = _parse_js_result(evaluate(target_id, """
    (() => {
        const visible = (element) => {
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return !!(rect.width && rect.height && style.display !== 'none'
                && style.visibility !== 'hidden' && style.pointerEvents !== 'none');
        };
        const dialogs = Array.from(document.querySelectorAll('.greet-boss-pop, .greet-pop, .dialog-wrap'))
            .filter(visible);
        const popup = dialogs.find((element) =>
            element.matches('.greet-boss-pop, .greet-pop')
            || /预设招呼语|默认招呼语|自动招呼语|打招呼语/.test(
                (element.innerText || element.textContent || '').trim()
            )
        );
        if (!popup) return JSON.stringify({success: false, error: 'preset_popup_missing'});
        const buttons = Array.from(popup.querySelectorAll(
            '[ka="dialog_confirm"], .btn-sure, button, [role="button"]'
        )).filter((element) => {
            if (!visible(element) || element.disabled || element.classList.contains('disabled')) return false;
            const text = (element.innerText || element.textContent || '').trim();
            return element.matches('[ka="dialog_confirm"], .btn-sure')
                || /确定|确认|继续|开始沟通|立即沟通/.test(text);
        });
        const button = buttons[0];
        if (!button) return JSON.stringify({success: false, error: 'preset_confirm_missing'});
        button.scrollIntoView({block: 'center', inline: 'center'});
        button.click();
        return JSON.stringify({success: true, action: 'preset_confirmed'});
    })()
    """))
    if not result.get("success"):
        return {
            **result,
            "history_detail": "检测到平台招呼语，但无法确认招呼语弹窗",
            "skip_backoff": True,
        }
    return {"success": True, "action": "preset_confirmed"}


def _confirm_continue_chat(target_id: str) -> dict:
    """Confirm BOSS's dialog for continuing an existing Boss conversation about a new job."""
    result = _parse_js_result(evaluate(target_id, """
    (() => {
        const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
        const visible = element => {
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return !!(rect.width && rect.height && style.display !== 'none'
                && style.visibility !== 'hidden' && style.pointerEvents !== 'none');
        };
        const dialogs = Array.from(document.querySelectorAll(
            '.dialog-wrap, [role="dialog"], .boss-dialog, [class*="dialog"], [class*="modal"]'
        )).filter(visible);
        const dialog = dialogs.find(element => {
            const text = normalize(element.innerText || element.textContent);
            return /您与该Boss已沟通过/.test(text) && /是否就新职位.*继续沟通/.test(text);
        });
        if (!dialog) return JSON.stringify({success: false, error: 'continue_chat_popup_missing'});

        const buttons = Array.from(dialog.querySelectorAll(
            '[ka="dialog_confirm"], .btn-sure, button, a, [role="button"], [class*="btn"]'
        )).filter(element => visible(element) && !element.disabled && !element.classList.contains('disabled'));
        const confirmButton = buttons.find(element =>
            /^(?:继续沟通|确定|确认|继续)$/.test(normalize(element.innerText || element.textContent || element.value))
        ) || buttons.find(element => element.matches('[ka="dialog_confirm"], .btn-sure'));
        if (!confirmButton) {
            return JSON.stringify({
                success: false,
                error: 'continue_chat_confirm_missing',
                buttons: buttons.map(element => normalize(element.innerText || element.textContent || element.value)).filter(Boolean)
            });
        }
        confirmButton.scrollIntoView({block: 'center', inline: 'center'});
        confirmButton.click();
        return JSON.stringify({
            success: true,
            action: 'continue_chat_confirmed',
            button_text: normalize(confirmButton.innerText || confirmButton.textContent || confirmButton.value)
        });
    })()
    """))
    if not result.get("success"):
        return {
            **result,
            "history_detail": "检测到已沟通过提示，但无法确认继续沟通",
            "skip_backoff": True,
        }
    return {"success": True, "action": "continue_chat_confirmed"}


def _submit_startchat_greeting(target_id: str, greeting: str) -> dict:
    greeting_escaped = json.dumps(greeting, ensure_ascii=False)
    input_state = _parse_js_result(evaluate(target_id, """
    (() => {
        const visible = (element) => {
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return !!(rect.width && rect.height && style.display !== 'none'
                && style.visibility !== 'hidden' && style.pointerEvents !== 'none');
        };
        const dialog = Array.from(document.querySelectorAll('.dialog-wrap.startchat-dialog'))
            .find(visible);
        const input = dialog && Array.from(dialog.querySelectorAll('textarea.input-area, textarea'))
            .find(visible);
        if (!input) return JSON.stringify({success: false, error: 'startchat_input_missing'});
        input.scrollIntoView({block: 'center', inline: 'center'});
        const rect = input.getBoundingClientRect();
        return JSON.stringify({
            success: true,
            x: rect.x + rect.width / 2,
            y: rect.y + rect.height / 2
        });
    })()
    """))
    if not input_state.get("success"):
        return {
            **input_state,
            "history_detail": "首次沟通弹窗中未找到招呼语输入框",
            "skip_backoff": True,
        }
    if not click_at(target_id, f"{input_state['x']},{input_state['y']}"):
        return {"success": False, "error": "startchat_input_focus_failed", "skip_backoff": True}
    if not press_key(target_id, "SelectAll") or not press_key(target_id, "Backspace"):
        return {"success": False, "error": "startchat_input_clear_failed", "skip_backoff": True}
    if not type_text(target_id, greeting, human=True):
        return {"success": False, "error": "startchat_trusted_input_failed", "skip_backoff": True}

    submit_state = _parse_js_result(evaluate(target_id, f"""
    (() => {{
        const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
        const visible = (element) => {{
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return !!(rect.width && rect.height && style.display !== 'none'
                && style.visibility !== 'hidden' && style.pointerEvents !== 'none');
        }};
        const dialog = Array.from(document.querySelectorAll('.dialog-wrap.startchat-dialog'))
            .find(visible);
        const input = dialog && Array.from(dialog.querySelectorAll('textarea.input-area, textarea'))
            .find(visible);
        if (!input || normalize(input.value) !== normalize({greeting_escaped})) {{
            return JSON.stringify({{success: false, error: 'startchat_input_not_filled'}});
        }}
        const buttons = Array.from(dialog.querySelectorAll(
            '.send-message, [ka="dialog_confirm"], .btn-sure, .btn-send, '
            + '.send-btn, button, [role="button"]'
        )).filter((element) => {{
            if (!visible(element) || element.disabled || element.classList.contains('disabled')) return false;
            const text = (element.innerText || element.textContent || '').trim();
            return element.matches(
                '.send-message, [ka="dialog_confirm"], .btn-sure, .btn-send, .send-btn'
            ) || /发送|确定|开始沟通|立即沟通/.test(text);
        }});
        const button = buttons[0];
        if (!button) return JSON.stringify({{success: false, error: 'startchat_submit_missing'}});
        button.scrollIntoView({{block: 'center', inline: 'center'}});
        const rect = button.getBoundingClientRect();
        return JSON.stringify({{
            success: true,
            x: rect.x + rect.width / 2,
            y: rect.y + rect.height / 2
        }});
    }})()
    """))
    if not submit_state.get("success"):
        return {
            **submit_state,
            "history_detail": "首次沟通招呼语未被 BOSS 输入组件接受",
            "skip_backoff": True,
        }
    if not click_at(target_id, f"{submit_state['x']},{submit_state['y']}"):
        return {
            "success": False,
            "error": "startchat_submit_click_failed",
            "history_detail": "首次沟通招呼语已填写，但真实提交点击失败",
            "skip_backoff": True,
        }
    return {"success": True, "action": "first_contact_submitted"}


def _navigate_to_chat_redirect(target_id: str, click_result: dict) -> bool:
    """Reuse BOSS's own chat destination without foregrounding the job tab."""
    redirect_url = str(click_result.get("redirectUrl") or "").strip()
    if not redirect_url.startswith("/web/geek/chat"):
        return False
    return navigate(target_id, urljoin("https://www.zhipin.com", redirect_url))


def _handle_greet_popup(target_id: str, greeting: str, click_result: dict | None = None) -> dict:
    state = _detect_greet_popup(target_id)
    if not state.get("success"):
        return {
            "success": False,
            "error": state.get("error", "popup_detection_failed"),
            "history_detail": "无法识别首次沟通页面状态",
            "skip_backoff": True,
        }
    if _is_preset_greeting_popup(state):
        return _confirm_preset_greeting(target_id)
    if state.get("kind") == "continue_chat_dialog":
        return _confirm_continue_chat(target_id)
    if state.get("kind") == "startchat_dialog":
        if click_result and _navigate_to_chat_redirect(target_id, click_result):
            return {"success": True, "action": "startchat_redirected"}
        return {
            "success": False,
            "error": "startchat_redirect_unavailable",
            "history_detail": "首次沟通弹窗缺少可验证的聊天地址，已停止发送且未切换前台",
            "skip_backoff": True,
        }
    return {"success": True, "action": "no_popup"}


def _chat_target_matches_job(target_id: str, job: dict, *, allow_company_only: bool = False) -> bool:
    job_id = json.dumps(str(job.get("id") or ""), ensure_ascii=False)
    company = json.dumps(str(job.get("company") or ""), ensure_ascii=False)
    title = json.dumps(str(job.get("title") or ""), ensure_ascii=False)
    allow_company_only_js = "true" if allow_company_only else "false"
    result = _parse_js_result(evaluate(target_id, f"""
    (() => {{
        const normalize = (value) => String(value || '').replace(/\s+/g, '').toLowerCase();
        const expectedId = normalize({job_id});
        const expectedCompany = normalize({company});
        const expectedTitle = normalize({title});
        const allowCompanyOnly = {allow_company_only_js};

        const activeRoots = Array.from(new Set([
            document.querySelector('.chat-conversation'),
            document.querySelector('.friend-content.selected')
        ].filter(Boolean)));
        const activeText = normalize(
            activeRoots.map((element) => element.innerText || element.textContent || '').join(' ')
        );
        const activeHtml = activeRoots.map((element) => element.outerHTML || '').join(' ');
        const idMatch = !!expectedId && (
            location.href.includes(expectedId) ||
            activeHtml.includes(expectedId)
        );
        const companyMatch = !!expectedCompany && activeText.includes(expectedCompany);
        const identityMatch = companyMatch && (
            allowCompanyOnly || !expectedTitle || activeText.includes(expectedTitle)
        );
        return JSON.stringify({{success: true, matches: idMatch || identityMatch}});
    }})()
    """))
    return bool(result.get("success") and result.get("matches"))


def _wait_for_chat_page(
    target_id: str,
    stop_event,
    attempts: int = 20,
    job: dict | None = None,
    excluded_target_ids: set[str] | None = None,
    allow_company_only: bool = False,
) -> dict:
    for _ in range(attempts):
        if _sleep_or_stop(0.5, stop_event):
            close_tab(target_id)
            return {"success": False, "error": "stopped", "history_detail": "用户已请求停止", "skip_backoff": True}
        url_now = evaluate(target_id, "location.pathname")
        if url_now and "/web/geek/chat" in url_now:
            if job is None:
                return {"success": True, "target_id": target_id}
            matches_current = (
                _chat_target_matches_job(target_id, job, allow_company_only=True)
                if allow_company_only
                else _chat_target_matches_job(target_id, job)
            )
            if matches_current:
                return {"success": True, "target_id": target_id}
        if job is not None:
            for candidate in get_page_targets():
                candidate_id = str(candidate.get("targetId") or "")
                candidate_url = str(candidate.get("url") or "")
                matches_candidate = False
                if candidate_id and candidate_id != target_id and "/web/geek/chat" in candidate_url:
                    matches_candidate = (
                        _chat_target_matches_job(candidate_id, job, allow_company_only=True)
                        if allow_company_only
                        else _chat_target_matches_job(candidate_id, job)
                    )
                if matches_candidate:
                    return {"success": True, "target_id": candidate_id, "opened_new_tab": True}
    return {"success": False, "error": "chat_navigation_timeout"}


def _click_chat_button(target_id: str, stop_event, attempts: int = 30) -> dict:
    click_chat_js = CHAT_BUTTON_SCRIPT_FOR_TESTS

    last_result: dict = {"success": False, "error": "no_chat_button"}
    for attempt in range(max(1, attempts)):
        if _stop_requested(stop_event):
            return {"success": False, "error": "stopped", "history_detail": "用户已请求停止", "skip_backoff": True}
        last_result = _parse_js_result(evaluate(target_id, click_chat_js))
        if last_result.get("success"):
            return last_result
        if attempt < attempts - 1 and _sleep_or_stop(1, stop_event):
            return {"success": False, "error": "stopped", "history_detail": "用户已请求停止", "skip_backoff": True}

    return last_result


def _adopt_chat_target(current_target_id: str, chat_ready: dict) -> str:
    """Switch to a matching chat tab and close the superseded job tab."""
    next_target_id = str(chat_ready.get("target_id") or current_target_id)
    if next_target_id != current_target_id:
        close_tab(current_target_id)
    return next_target_id


def _message_delivery_state(target_id: str, greeting: str) -> str:
    greeting_escaped = json.dumps(greeting, ensure_ascii=False)
    result = _parse_js_result(evaluate(target_id, f"""
    (() => {{
        const normalize = (value) => String(value || '')
            .replace(/[\\u200b-\\u200f\\ufeff]/g, '')
            .replace(/\\s+/g, ' ')
            .trim();
        const removeDeliveryLabels = (value) => normalize(value)
            .replace(/(发送中|已读|未读|送达|发送成功|重试|重新发送)$/g, '')
            .trim();
        const textMatchesExpected = (value, expectedText) => {{
            const text = removeDeliveryLabels(value);
            return text === expectedText || text.includes(expectedText);
        }};
        const messageText = (node) => {{
            const contentNode = node.querySelector(
                '.message-content, .text, .content, .message-text, '
                + '[class*="message-content"], [class*="msg-content"], [class*="text"]'
            );
            return normalize(contentNode ? contentNode.innerText || contentNode.textContent : node.innerText || node.textContent);
        }};
        const expected = normalize({greeting_escaped});
        const ownMessages = Array.from(document.querySelectorAll(
            '.chat-record .message-item.item-myself, .chat-record .item-myself, '
            + '.chat-record .message-item.item-self, .chat-record [class*="item-my"]'
        ));
        const matching = ownMessages.filter((node) => textMatchesExpected(messageText(node), expected));
        const messageList = document.querySelector('.chat-record');
        const vue = messageList && messageList.__vue__;
        const records = vue && Array.isArray(vue.list$) ? vue.list$ : [];
        const matchingRecords = records.filter((message) => {{
            if (!message || !message.isSelf) return false;
            const text = message.text || message.lastText || message.content || message.message || message.body || '';
            return textMatchesExpected(text, expected);
        }});
        if (!matching.length && !matchingRecords.length) {{
            return JSON.stringify({{success: true, state: 'missing'}});
        }}
        const domStates = matching.map((node) => {{
            const statusNode = node.querySelector('.message-status');
            const statusClass = statusNode ? String(statusNode.className || '') : '';
            if (statusClass.includes('status-error')) return 'failed';
            if (statusClass.includes('status-loading')) return 'pending';
            return 'delivered';
        }});
        const recordStates = matchingRecords.map((record) => {{
            const status = Number(record.status);
            if (status === 4) return 'failed';
            if (status === 0) return 'pending';
            return 'delivered';
        }});
        const states = [...domStates, ...recordStates];
        const state = states.includes('delivered') ? 'delivered'
            : states.includes('pending') ? 'pending' : 'failed';
        return JSON.stringify({{success: true, state}});
    }})()
    """))
    if not result.get("success"):
        return "missing"
    return str(result.get("state") or "missing")


def _verify_greeting_in_chat_list(
    job: dict,
    greeting: str,
    stop_event,
    attempts: int = 6,
) -> bool:
    """Confirm an ambiguous send from the matching BOSS chat-list row.

    A cleared input only proves that the page handled the submit action. Require
    the target company and complete greeting in the same row before recording a
    success, so this fallback cannot cause an automatic duplicate or false sent
    state.
    """
    company = " ".join(str(job.get("company") or "").split())
    expected = " ".join(str(greeting or "").split())
    if not company or not expected:
        return False

    target_id = new_tab("https://www.zhipin.com/web/geek/chat", background=True)
    if not target_id:
        return False

    try:
        wait_for_load(target_id, timeout=10)
        company_json = json.dumps(company, ensure_ascii=False)
        expected_json = json.dumps(expected, ensure_ascii=False)
        expression = f"""
        (() => {{
			const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
            const expectedCompany = normalize({company_json});
            const expectedGreeting = normalize({expected_json});
            const rows = Array.from(document.querySelectorAll('li[role=listitem]'));
            const matched = rows.some((row) => {{
                const nameBox = row.querySelector('.name-box');
                const spans = nameBox ? Array.from(nameBox.querySelectorAll('span')) : [];
                const actualCompany = normalize(spans.length >= 2 ? spans[1].textContent : '');
                const lastMessage = row.querySelector('.last-msg-text, .last-msg, .message-text');
                const actualMessage = normalize(lastMessage ? lastMessage.textContent : row.innerText);
                const companyMatches = actualCompany && (
                    actualCompany === expectedCompany
                    || actualCompany.includes(expectedCompany)
                    || expectedCompany.includes(actualCompany)
                );
                return companyMatches && actualMessage.includes(expectedGreeting);
            }});
            return JSON.stringify({{success: true, matched}});
        }})()
        """
        for attempt in range(max(1, attempts)):
            if _stop_requested(stop_event):
                return False
            result = _parse_js_result(evaluate(target_id, expression, timeout=5))
            if result.get("success") and result.get("matched"):
                return True
            if attempt + 1 < attempts and _sleep_or_stop(1, stop_event):
                return False
        return False
    finally:
        close_tab(target_id)


def _submit_chat_message_background(target_id: str, greeting: str) -> dict:
    """Use All In's original Vue submit path without foregrounding Chrome."""
    greeting_escaped = json.dumps(greeting, ensure_ascii=False)
    result = _parse_js_result(evaluate(target_id, f"""
    (() => {{
        const input = document.querySelector('#chat-input');
        if (!input) return JSON.stringify({{success: false, error: 'no_chat_input'}});

        let vue = null;
        let element = input;
        for (let index = 0; index < 15 && element; index += 1) {{
            if (element.__vue__) {{
                vue = element.__vue__;
                break;
            }}
            element = element.parentElement;
        }}
        if (!vue || typeof vue.handleSubmit !== 'function') {{
            return JSON.stringify({{success: false, error: 'legacy_submit_unavailable'}});
        }}

        input.innerText = {greeting_escaped};
        input.dispatchEvent(new InputEvent('input', {{
            bubbles: true,
            inputType: 'insertText',
            data: {greeting_escaped}
        }}));
        if (vue._data) vue._data.enableSubmit = true;
        vue.handleSubmit();
        return JSON.stringify({{success: true, action: 'chat_submitted_background'}});
    }})()
    """))
    if result.get("success"):
        return {"success": True, "action": "chat_submitted_background"}
    return result


def _fill_chat_input(target_id: str, greeting: str) -> dict:
    greeting_escaped = json.dumps(greeting, ensure_ascii=False)
    input_state = _parse_js_result(evaluate(target_id, """
    (() => {
        const input = document.querySelector('#chat-input');
        if (!input) return JSON.stringify({success: false, error: 'no_chat_input'});
        return JSON.stringify({success: true});
    })()
    """))
    if not input_state.get("success"):
        return input_state
    if not click_at(target_id, "#chat-input"):
        return {"success": False, "error": "chat_input_focus_failed"}
    if not press_key(target_id, "SelectAll") or not press_key(target_id, "Backspace"):
        return {"success": False, "error": "chat_input_clear_failed"}
    if not type_text(target_id, greeting, human=True):
        return {"success": False, "error": "trusted_input_failed"}

    result = _parse_js_result(evaluate(target_id, f"""
    (() => {{
        const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
        const input = document.querySelector('#chat-input');
        if (!input) return JSON.stringify({{success: false, error: 'no_chat_input'}});
        const sendButton = document.querySelector('.btn-send');
        const disabled = !sendButton || sendButton.disabled || sendButton.classList.contains('disabled');
        const matches = normalize(input.innerText || input.textContent) === normalize({greeting_escaped});
        return JSON.stringify({{
            success: matches,
            error: matches ? null : 'input_not_filled',
            send_button: !!sendButton,
            disabled
        }});
    }})()
    """))
    if result.get("success") and result.get("disabled"):
        if type_text(target_id, " ") and press_key(target_id, "Backspace"):
            result = _parse_js_result(evaluate(target_id, f"""
            (() => {{
                const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
                const input = document.querySelector('#chat-input');
                const sendButton = document.querySelector('.btn-send');
                const disabled = !sendButton || sendButton.disabled || sendButton.classList.contains('disabled');
                const matches = !!input && normalize(input.innerText || input.textContent) === normalize({greeting_escaped});
                return JSON.stringify({{success: matches, error: matches ? null : 'input_not_filled', disabled}});
            }})()
            """))
    return result


# JS: 在岗位详情页点击"立即沟通"并发送招呼语
JS_SEND_GREETING = """
(async (greeting) => {
    // 找到"立即沟通"按钮
    const btn = document.querySelector('.btn-startchat, .op-btn-chat, [ka="job_detail_chat"]');
    if (!btn) return JSON.stringify({success: false, error: 'no_chat_button'});

    btn.click();
    await new Promise(r => setTimeout(r, 2000));

    // 等待聊天输入框出现
    const input = document.querySelector('.chat-input textarea, .chat-input [contenteditable], .input-area textarea');
    if (!input) return JSON.stringify({success: false, error: 'no_input_box'});

    // 输入招呼语
    if (input.tagName === 'TEXTAREA') {
        input.value = greeting;
        input.dispatchEvent(new Event('input', {bubbles: true}));
    } else {
        input.innerHTML = greeting;
        input.dispatchEvent(new Event('input', {bubbles: true}));
    }

    await new Promise(r => setTimeout(r, 500));

    // 点击发送
    const sendBtn = document.querySelector('.btn-send, .send-btn, [class*="send"]');
    if (sendBtn) {
        sendBtn.click();
        await new Promise(r => setTimeout(r, 1000));
        return JSON.stringify({success: true});
    }

    return JSON.stringify({success: false, error: 'no_send_button'});
})(arguments[0])
"""


def _detect_job_closed_on_page(target_id: str) -> dict | None:
    """Attempt to confirm whether the opened job page reports the job as closed/down.

    Used as a fallback when a step on the job-detail page fails (e.g. no chat button),
    so we can surface the real business conclusion ("job is closed") instead of only the
    technical step that failed. Returns a send-result dict when a closed marker is found.
    """
    markers = list(JOB_CLOSED_MARKERS)
    probe = _parse_js_result(evaluate(target_id, f"""
    (() => {{
        const text = document.body ? document.body.innerText : '';
        const title = document.title || '';
        const markers = {json.dumps(markers, ensure_ascii=False)};
        const hit = title.includes('访问的页面不存在') || markers.some((m) => text.includes(m));
        if (!hit) return JSON.stringify({{closed: false}});
        const snippet = markers.find((m) => text.includes(m)) || '职位已关闭';
        return JSON.stringify({{closed: true, snippet}});
    }})()
    """))
    if probe.get("closed"):
        return {
            "success": False,
            "error": "job_page_unavailable",
            "history_detail": "岗位已关闭或下架",
            "skip_backoff": True,
        }
    return None


def _send_greeting_once(job: dict, greeting: str, throttle_config: dict) -> tuple[dict, str | None]:
    stop_event = throttle_config.get("_workbench_stop_event")
    existing_target_ids = {
        str(target.get("targetId") or "")
        for target in get_page_targets()
        if target.get("targetId")
    }
    access_guard = throttle_config.get("_platform_access_guard")
    if isinstance(access_guard, PlatformAccessGuard):
        try:
            access_guard.reserve("job_page")
        except PlatformSafetyStop as exc:
            return {
                "success": False,
                "error": exc.reason,
                "history_detail": "为了账户安全，已达到平台页面访问上限或仍处于风险冷却",
            }, None
    target_id = new_tab(job["url"], background=True)
    if not target_id:
        return {"success": False, "error": "open_page_failed", "history_detail": "无法打开页面", "skip_backoff": True}, None

    if _stop_requested(stop_event):
        close_tab(target_id)
        return {"success": False, "error": "stopped", "history_detail": "用户已请求停止", "skip_backoff": True}, None

    browse_min = throttle_config.get("browse_duration_min", 15)
    browse_max = throttle_config.get("browse_duration_max", 30)
    if throttle_config.get("browse_before_greet", True):
        import random
        browse_time = random.uniform(browse_min, browse_max)
        if _sleep_or_stop(browse_time, stop_event):
            close_tab(target_id)
            return {"success": False, "error": "stopped", "history_detail": "用户已请求停止", "skip_backoff": True}, None

    page_check_js = f"""
    (() => {{
        const text = document.body ? document.body.innerText : '';
        const title = document.title || '';
        const closedMarkers = {json.dumps(list(JOB_CLOSED_MARKERS), ensure_ascii=False)};
        if (
            title.includes('访问的页面不存在') ||
            closedMarkers.some((marker) => text.includes(marker))
        ) {{
            return JSON.stringify({{
                success: false,
                error: 'job_page_unavailable',
                history_detail: '岗位已关闭或下架',
                skip_backoff: true
            }});
        }}
        return JSON.stringify({{success: true}});
    }})()
    """
    page_check = _parse_js_result(evaluate(target_id, page_check_js))
    if not page_check.get("success"):
        close_tab(target_id)
        return page_check, None

    chat_button_attempts = int(throttle_config.get("_chat_button_attempts", 30))
    result1a = _click_chat_button(target_id, stop_event, chat_button_attempts)
    if not result1a.get("success"):
        closed_result = _detect_job_closed_on_page(target_id)
        close_tab(target_id)
        if closed_result:
            return closed_result, None
        return {"success": False, "error": "no_chat_button", "history_detail": "无法找到沟通按钮", "skip_backoff": True}, None

    if _sleep_or_stop(4, stop_event):
        close_tab(target_id)
        return {"success": False, "error": "stopped", "history_detail": "用户已请求停止", "skip_backoff": True}, None

    popup_result = _handle_greet_popup(target_id, greeting, result1a)
    if not popup_result.get("success"):
        return popup_result, target_id
    contact_action = str(popup_result.get("action") or "no_popup")

    navigation_attempts = int(throttle_config.get("_chat_navigation_attempts", 20))
    chat_ready = _wait_for_chat_page(
        target_id,
        stop_event,
        navigation_attempts,
        job,
        excluded_target_ids=existing_target_ids,
        allow_company_only=contact_action == "continue_chat_confirmed",
    )
    if chat_ready.get("success"):
        target_id = _adopt_chat_target(target_id, chat_ready)
    if chat_ready.get("error") == "stopped":
        return chat_ready, None
    if chat_ready.get("success") and contact_action == "continue_chat_confirmed":
        close_tab(target_id)
        return {
            "success": True,
            "verified": True,
            "already_present": True,
            "continued_existing_conversation": True,
            "history_detail": "已确认就新职位继续与该 Boss 沟通，归入后续跟进",
        }, None
    if not chat_ready.get("success") and contact_action not in {
        "first_contact_submitted",
        "startchat_redirected",
        "continue_chat_confirmed",
    }:
        console.print("[yellow]    ! 沟通按钮未跳转聊天页，尝试真实点击兜底[/yellow]")
        if click_at(target_id, CHAT_BUTTON_SELECTOR):
            if _sleep_or_stop(1, stop_event):
                close_tab(target_id)
                return {"success": False, "error": "stopped", "history_detail": "用户已请求停止", "skip_backoff": True}, None
            popup_result = _handle_greet_popup(target_id, greeting, result1a)
            if not popup_result.get("success"):
                return popup_result, target_id
            contact_action = str(popup_result.get("action") or "no_popup")
            chat_ready = _wait_for_chat_page(
                target_id,
                stop_event,
                navigation_attempts,
                job,
                excluded_target_ids=existing_target_ids,
            )
            if chat_ready.get("success"):
                target_id = _adopt_chat_target(target_id, chat_ready)
            if chat_ready.get("error") == "stopped":
                return chat_ready, None

    if not chat_ready.get("success"):
        if contact_action == "continue_chat_confirmed":
            close_tab(target_id)
            return {
                "success": True,
                "verified": True,
                "already_present": True,
                "continued_existing_conversation": True,
                "verified_from_continue_prompt": True,
                "history_detail": "BOSS 已确认该 Boss 存在历史沟通，已归入新职位继续跟进",
            }, None
        if contact_action == "first_contact_submitted":
            if _verify_greeting_in_chat_list(job, greeting, stop_event):
                close_tab(target_id)
                return {
                    "success": True,
                    "verified": True,
                    "first_contact": True,
                    "verified_from_chat_list": True,
                }, None
            return {
                "success": False,
                "error": "first_contact_navigation_unverified",
                "history_detail": "首次招呼语已经提交，但未能进入对应会话验证结果；为避免重复发送，请人工检查",
                "skip_backoff": True,
            }, target_id
        return {
            "success": False,
            "error": "no_chat_input",
            "history_detail": "发送失败: 未进入具体聊天会话，可能是BOSS继续沟通跳转失败",
            "skip_backoff": True,
        }, target_id

    verification_attempts = int(throttle_config.get("_send_verification_attempts", 20))
    if contact_action == "first_contact_submitted":
        for _ in range(max(1, verification_attempts)):
            if _sleep_or_stop(0.5, stop_event):
                close_tab(target_id)
                return {"success": False, "error": "stopped", "history_detail": "用户已请求停止", "skip_backoff": True}, None
            delivery_state = _message_delivery_state(target_id, greeting)
            if delivery_state == "failed":
                return {
                    "success": False,
                    "error": "first_contact_send_rejected",
                    "history_detail": "首次沟通招呼语被标记为发送失败",
                    "skip_backoff": True,
                }, target_id
            if delivery_state == "delivered":
                if _sleep_or_stop(2, stop_event):
                    close_tab(target_id)
                    return {"success": False, "error": "stopped", "history_detail": "用户已请求停止", "skip_backoff": True}, None
                if _message_delivery_state(target_id, greeting) == "delivered":
                    close_tab(target_id)
                    return {
                        "success": True,
                        "verified": True,
                        "first_contact": True,
                    }, None
                if _verify_greeting_in_chat_list(job, greeting, stop_event):
                    close_tab(target_id)
                    return {
                        "success": True,
                        "verified": True,
                        "first_contact": True,
                        "verified_from_chat_list": True,
                    }, None
                return {
                    "success": False,
                    "error": "first_contact_send_not_stable",
                    "history_detail": "首次招呼语曾出现但未稳定保留在会话中",
                    "skip_backoff": True,
                }, target_id
        if _verify_greeting_in_chat_list(job, greeting, stop_event):
            close_tab(target_id)
            return {
                "success": True,
                "verified": True,
                "first_contact": True,
                "verified_from_chat_list": True,
            }, None
        return {
            "success": False,
            "error": "first_contact_delivery_unverified",
            "history_detail": "首次招呼语已提交，但会话中未确认对应消息；为避免重复发送，请人工检查",
            "skip_backoff": True,
        }, target_id

    existing_state = _message_delivery_state(target_id, greeting)
    if existing_state == "delivered":
        close_tab(target_id)
        return {"success": True, "already_present": True, "verified": True}, None
    if existing_state in {"pending", "failed"}:
        return {
            "success": False,
            "error": f"existing_message_{existing_state}",
            "history_detail": f"会话中已有状态为 {existing_state} 的相同消息，请人工检查",
            "skip_backoff": True,
        }, target_id

    submit_result = _submit_chat_message_background(target_id, greeting)
    if not submit_result.get("success"):
        input_result = _fill_chat_input(target_id, greeting)
        if not input_result.get("success"):
            return input_result, target_id
        if input_result.get("disabled"):
            return {
                "success": False,
                "error": "send_button_unavailable",
                "history_detail": "招呼语已填入，但发送按钮不可用，未标记成功",
                "skip_backoff": True,
            }, target_id
        if not click_at(target_id, ".btn-send:not(.disabled)"):
            return {
                "success": False,
                "error": "send_button_click_failed",
                "history_detail": "招呼语已填入，但发送按钮点击失败，未标记成功",
                "skip_backoff": True,
            }, target_id

    for _ in range(max(1, verification_attempts)):
        if _sleep_or_stop(0.5, stop_event):
            close_tab(target_id)
            return {"success": False, "error": "stopped", "history_detail": "用户已请求停止", "skip_backoff": True}, None
        delivery_state = _message_delivery_state(target_id, greeting)
        if delivery_state == "failed":
            return {
                "success": False,
                "error": "send_rejected_after_click",
                "history_detail": "BOSS 将消息标记为发送失败，未记录为已发送",
                "skip_backoff": True,
            }, target_id
        if delivery_state == "delivered":
            if _sleep_or_stop(2, stop_event):
                close_tab(target_id)
                return {"success": False, "error": "stopped", "history_detail": "用户已请求停止", "skip_backoff": True}, None
            if _message_delivery_state(target_id, greeting) == "delivered":
                close_tab(target_id)
                return {"success": True, "verified": True}, None
            if _verify_greeting_in_chat_list(job, greeting, stop_event):
                close_tab(target_id)
                return {
                    "success": True,
                    "verified": True,
                    "verified_from_chat_list": True,
                }, None
            return {
                "success": False,
                "error": "send_not_stable",
                "history_detail": "消息曾出现但未稳定保留在会话中，未记录为已发送",
                "skip_backoff": True,
            }, target_id

    if _verify_greeting_in_chat_list(job, greeting, stop_event):
        close_tab(target_id)
        return {
            "success": True,
            "verified": True,
            "verified_from_chat_list": True,
        }, None

    return {
        "success": False,
        "error": "send_not_confirmed",
        "history_detail": "已点击发送，但会话中未确认对应招呼语，未记录为已发送",
        "skip_backoff": True,
    }, target_id


_send_single_job = _send_greeting_once


def _send_zhilian_greeting_once(
    job: dict,
    greeting: str,
    throttle_config: dict,
    stop_event: Event | None = None,
) -> tuple[dict, str | None]:
    """Execute Zhilian-specific greeting and application flow for a single job."""
    access_guard = throttle_config.get("_platform_access_guard")
    if isinstance(access_guard, PlatformAccessGuard):
        try:
            access_guard.reserve("job_page")
        except PlatformSafetyStop as exc:
            return {
                "success": False,
                "error": exc.reason,
                "history_detail": "为了账户安全，已达到智联页面访问上限或仍处于风险冷却",
            }, None

    target_id = new_tab(job["url"], background=False)
    if not target_id:
        return {
            "success": False,
            "error": "open_page_failed",
            "history_detail": "无法打开智联岗位详情页",
            "skip_backoff": True,
        }, None

    if _stop_requested(stop_event):
        close_tab(target_id)
        return {
            "success": False,
            "error": "stopped",
            "history_detail": "用户已请求停止",
            "skip_backoff": True,
        }, None

    wait_for_load(target_id, timeout=15)

    if throttle_config.get("browse_before_greet", True):
        browse_min = float(throttle_config.get("browse_duration_min", 2))
        browse_max = float(throttle_config.get("browse_duration_max", 5))
        browse_time = random.uniform(min(browse_min, browse_max), max(browse_min, browse_max))
        scroll_js = """
        (() => {
            window.scrollBy({top: 260, behavior: 'smooth'});
            setTimeout(() => window.scrollBy({top: -120, behavior: 'smooth'}), 700);
        })()
        """
        try:
            evaluate(target_id, scroll_js)
        except Exception:
            pass
        if _sleep_or_stop(browse_time, stop_event):
            close_tab(target_id)
            return {
                "success": False,
                "error": "stopped",
                "history_detail": "用户已请求停止",
                "skip_backoff": True,
            }, None

    click_js = """
    (() => {
        const text = (document.body ? document.body.innerText : '') + ' ' + (document.title || '');
        if (/验证码|滑块|访问频繁|频率限制|账号异常|拒绝访问/.test(text)) {
            return JSON.stringify({success: false, error: 'blocked', history_detail: '智联出现验证码或访问限制'});
        }

        const closedMarkers = [
            "职位已下线", "职位已下架", "该职位已关闭", "职位已关闭",
            "此职位已停止招聘", "该职位已暂停招聘", "职位不存在", "已停止招聘",
            "该职位暂不招人", "暂不招人", "访问的页面不存在", "页面不存在", "404"
        ];
        if (closedMarkers.some(m => text.includes(m))) {
            return JSON.stringify({
                success: false,
                error: 'job_page_unavailable',
                history_detail: '岗位已下线或关闭',
                skip_backoff: true
            });
        }

        const isVisible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
        };

        const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
        const actionSelectors = [
            '.summary-planes__action > button.a-button.a--filled',
            '.summary-fixed__action > button.a-button.a--filled',
            'button.a-button.a--bordered.a--filled'
        ];
        const actionButtons = actionSelectors.flatMap(selector =>
            Array.from(document.querySelectorAll(selector))
        ).filter(isVisible);
        const allButtons = Array.from(document.querySelectorAll('button, a, [role="button"]')).filter(isVisible);

        const alreadyBtn = allButtons.find(button =>
            /^(?:已投递|已沟通|沟通中|已申请|已打招呼|继续沟通)$/.test(normalize(button.innerText))
        );
        if (alreadyBtn) {
            return JSON.stringify({
                success: true,
                already_sent: true,
                verified: true,
                status_text: normalize(alreadyBtn.innerText),
                history_detail: '岗位已处于已投递或沟通中状态'
            });
        }

        const applyBtn = actionButtons.find(button => normalize(button.innerText) === '立即投递');
        if (!applyBtn) {
            if (/请先登录|扫码登录|账号登录/.test(text)) {
                return JSON.stringify({
                    success: false,
                    error: 'login_required',
                    history_detail: '未登录智联招聘账号',
                    skip_backoff: true
                });
            }

            const similarOnly = allButtons.some(button => normalize(button.innerText) === '查看更多相似职位') &&
                !document.querySelector('.summary-planes__action button, .summary-fixed__action button');
            if (similarOnly) {
                return JSON.stringify({
                    success: false,
                    error: 'job_page_unavailable',
                    history_detail: '智联岗位已停止招聘，详情页仅提供相似职位',
                    skip_backoff: true
                });
            }

            return JSON.stringify({
                success: false,
                error: 'action_button_waiting',
                history_detail: '等待智联立即投递按钮渲染'
            });
        }

        applyBtn.scrollIntoView({block: 'center', inline: 'center'});
        applyBtn.click();

        return JSON.stringify({
            success: true,
            action: 'clicked',
            button_type: 'apply',
            button_text: normalize(applyBtn.innerText)
        });
    })()
    """
    action_attempts = max(int(throttle_config.get("_zhilian_action_attempts", 8)), 1)
    click_res: dict = {}
    for attempt in range(action_attempts):
        click_res = _parse_js_result(evaluate(target_id, click_js))
        if click_res.get("success") or click_res.get("error") != "action_button_waiting":
            break
        if attempt + 1 < action_attempts and _sleep_or_stop(0.75, stop_event):
            close_tab(target_id)
            return {
                "success": False,
                "error": "stopped",
                "history_detail": "用户已请求停止",
                "skip_backoff": True,
            }, None

    if not click_res.get("success"):
        if click_res.get("error") == "action_button_waiting":
            click_res = {
                "success": False,
                "error": "no_action_button",
                "history_detail": "智联岗位页已加载，但等待后仍未找到立即投递按钮",
                "skip_backoff": True,
            }
        close_tab(target_id)
        return click_res, None

    if click_res.get("already_sent"):
        close_tab(target_id)
        return click_res, None

    if _sleep_or_stop(2.0, stop_event):
        close_tab(target_id)
        return {
            "success": False,
            "error": "stopped",
            "history_detail": "用户已请求停止",
            "skip_backoff": True,
        }, None

    status_js = """
    (() => {
        const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
        const isVisible = el => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
        };

        const successModal = document.querySelector('.deliver-greeting-modal');
        if (
            isVisible(successModal) &&
            /已向对方发送简历和打招呼语/.test(normalize(successModal.innerText))
        ) {
            return JSON.stringify({
                success: true,
                verified: true,
                status_text: '已向对方发送简历和打招呼语'
            });
        }

        const buttons = Array.from(document.querySelectorAll('button, a, [role="button"]')).filter(isVisible);
        const changedBtn = buttons.find(button =>
            /^(?:已投递|已沟通|沟通中|已申请|继续沟通)$/.test(normalize(button.innerText))
        );
        if (changedBtn) {
            return JSON.stringify({
                success: true,
                verified: true,
                status_text: normalize(changedBtn.innerText)
            });
        }

        return JSON.stringify({success: true, verified: false, status_text: 'waiting'});
    })()
    """
    status_attempts = max(int(throttle_config.get("_zhilian_status_attempts", 8)), 1)
    status_res: dict = {}
    for attempt in range(status_attempts):
        status_res = _parse_js_result(evaluate(target_id, status_js))
        if status_res.get("verified"):
            break
        if attempt + 1 < status_attempts and _sleep_or_stop(0.75, stop_event):
            close_tab(target_id)
            return {
                "success": False,
                "error": "stopped",
                "history_detail": "用户已请求停止",
                "skip_backoff": True,
            }, None

    close_tab(target_id)
    if status_res.get("verified"):
        return {
            "success": True,
            "verified": True,
            "history_detail": f"智联投递成功 ({status_res.get('status_text')})",
        }, None

    return {
        "success": False,
        "error": "zhilian_send_unverified",
        "history_detail": "智联已点击立即投递，但未出现“已向对方发送简历和打招呼语”成功弹窗",
        "skip_backoff": True,
    }, None


def _send_job51_greeting_once(
    job: dict,
    greeting: str,
    throttle_config: dict,
    stop_event: Event | None = None,
) -> tuple[dict, str | None]:
    """Execute 51job-specific greeting and application flow for a single job."""
    access_guard = throttle_config.get("_platform_access_guard")
    if isinstance(access_guard, PlatformAccessGuard):
        try:
            access_guard.reserve("job_page")
        except PlatformSafetyStop as exc:
            return {
                "success": False,
                "error": exc.reason,
                "history_detail": "为了账户安全，已达到前程无忧页面访问上限或仍处于风险冷却",
            }, None

    target_id = new_tab(job["url"], background=False)
    if not target_id:
        return {
            "success": False,
            "error": "open_page_failed",
            "history_detail": "无法打开前程无忧岗位详情页",
            "skip_backoff": True,
        }, None

    if _stop_requested(stop_event):
        close_tab(target_id)
        return {
            "success": False,
            "error": "stopped",
            "history_detail": "用户已请求停止",
            "skip_backoff": True,
        }, None

    wait_for_load(target_id, timeout=15)

    if throttle_config.get("browse_before_greet", True):
        browse_min = float(throttle_config.get("browse_duration_min", 2))
        browse_max = float(throttle_config.get("browse_duration_max", 5))
        browse_time = random.uniform(min(browse_min, browse_max), max(browse_min, browse_max))
        scroll_js = """
        (() => {
            window.scrollBy({top: 280, behavior: 'smooth'});
            setTimeout(() => window.scrollBy({top: -100, behavior: 'smooth'}), 700);
        })()
        """
        try:
            evaluate(target_id, scroll_js)
        except Exception:
            pass
        if _sleep_or_stop(browse_time, stop_event):
            close_tab(target_id)
            return {
                "success": False,
                "error": "stopped",
                "history_detail": "用户已请求停止",
                "skip_backoff": True,
            }, None

    click_js = """
    (() => {
        const text = (document.body ? document.body.innerText : '') + ' ' + (document.title || '');
        if (/验证码|滑块|访问频繁|频率限制|账号异常|拒绝访问/.test(text)) {
            return JSON.stringify({success: false, error: 'blocked', history_detail: '前程无忧出现验证码或访问限制'});
        }

        const closedMarkers = [
            "职位已下线", "职位已下架", "该职位已关闭", "职位已关闭",
            "此职位已停止招聘", "该职位已暂停招聘", "职位不存在", "已停止招聘",
            "该职位暂不招人", "暂不招人", "访问的页面不存在", "页面不存在", "404"
        ];
        if (closedMarkers.some(m => text.includes(m))) {
            return JSON.stringify({
                success: false,
                error: 'job_page_unavailable',
                history_detail: '岗位已下线或关闭',
                skip_backoff: true
            });
        }

        const isVisible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
        };

        const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
        const buttons = Array.from(document.querySelectorAll('button, a, [role="button"], .apply-btn-new')).filter(isVisible);

        const alreadyBtn = buttons.find(button =>
            /^(?:已申请|已投递|已沟通|沟通中|已申请该职位)$/.test(normalize(button.innerText))
        );
        if (alreadyBtn) {
            return JSON.stringify({
                success: true,
                already_sent: true,
                verified: true,
                status_text: normalize(alreadyBtn.innerText),
                history_detail: '岗位已处于已申请或沟通中状态'
            });
        }

        const applyBtn = Array.from(document.querySelectorAll('.jobapply-wrapper .apply-btn-new, .apply-btn-new.big'))
            .filter(isVisible)
            .find(button => normalize(button.innerText) === '立即投递');
        if (!applyBtn) {
            if (/请先登录|扫码登录|账号登录/.test(text)) {
                return JSON.stringify({
                    success: false,
                    error: 'login_required',
                    history_detail: '未登录前程无忧账号',
                    skip_backoff: true
                });
            }
            return JSON.stringify({
                success: false,
                error: 'no_action_button',
                history_detail: '未找到前程无忧顶部立即投递按钮',
                skip_backoff: true
            });
        }

        applyBtn.scrollIntoView({block: 'center', inline: 'center'});
        applyBtn.click();

        return JSON.stringify({
            success: true,
            action: 'clicked',
            button_type: 'apply',
            button_text: normalize(applyBtn.innerText)
        });
    })()
    """
    click_res = _parse_js_result(evaluate(target_id, click_js))
    if not click_res.get("success"):
        close_tab(target_id)
        return click_res, None

    if click_res.get("already_sent"):
        close_tab(target_id)
        return click_res, None

    if _sleep_or_stop(2.0, stop_event):
        close_tab(target_id)
        return {
            "success": False,
            "error": "stopped",
            "history_detail": "用户已请求停止",
            "skip_backoff": True,
        }, None

    apply_state_js = """
    (() => {
        const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
        const isVisible = el => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
        };

        const successPopup = document.querySelector('.success-popup-2');
        if (isVisible(successPopup)) {
            const successText = normalize(successPopup.innerText);
            return JSON.stringify({
                success: true,
                verified: true,
                status_text: successText || 'success-popup-2'
            });
        }

        const buttons = Array.from(document.querySelectorAll('button, a, [role="button"], .apply-btn-new')).filter(isVisible);
        const changedBtn = buttons.find(button =>
            /^(?:已申请|已投递|已沟通|沟通中|已申请该职位)$/.test(normalize(button.innerText))
        );
        if (changedBtn) {
            return JSON.stringify({
                success: true,
                verified: true,
                status_text: normalize(changedBtn.innerText)
            });
        }

        const hintDialog = Array.from(document.querySelectorAll('.apply-component-hint-dialog')).find(isVisible);
        if (hintDialog) {
            const hintText = normalize(hintDialog.innerText);
            if (/申请成功|投递成功|已申请|已投递/.test(hintText)) {
                return JSON.stringify({success: true, verified: true, status_text: hintText});
            }
            return JSON.stringify({
                success: false,
                error: 'job51_apply_rejected',
                history_detail: hintText || '前程无忧未接受本次申请',
                skip_backoff: true
            });
        }

        const resumeDialog = Array.from(document.querySelectorAll('.apply-component-resume-dialog')).find(isVisible);
        if (resumeDialog) {
            const applyButton = Array.from(resumeDialog.querySelectorAll('a.btn, button, [role="button"]'))
                .filter(isVisible)
                .find(button => normalize(button.innerText) === '立即申请');
            if (!applyButton) {
                return JSON.stringify({
                    success: false,
                    error: 'job51_resume_unavailable',
                    history_detail: '前程无忧要求选择简历，但未找到立即申请按钮',
                    skip_backoff: true
                });
            }
            applyButton.click();
            return JSON.stringify({success: true, verified: false, step: 'resume_confirmed'});
        }

        const attachmentDialog = Array.from(document.querySelectorAll('.attachment_resume_dialog')).find(isVisible);
        if (attachmentDialog) {
            const sendButton = Array.from(attachmentDialog.querySelectorAll('button, a, [role="button"]'))
                .filter(isVisible)
                .find(button => normalize(button.innerText) === '发送');
            if (!sendButton) {
                return JSON.stringify({
                    success: false,
                    error: 'job51_attachment_unavailable',
                    history_detail: '前程无忧附件简历弹窗缺少发送按钮',
                    skip_backoff: true
                });
            }
            sendButton.click();
            return JSON.stringify({success: true, verified: false, step: 'attachment_sent'});
        }

        const bodyText = normalize(document.body ? document.body.innerText : '');
        if (/申请成功|投递成功|发送成功|已成功申请/.test(bodyText)) {
            return JSON.stringify({success: true, verified: true, status_text: 'toast_success'});
        }

        return JSON.stringify({success: true, verified: false, step: 'waiting'});
    })()
    """
    state_attempts = max(int(throttle_config.get("_job51_apply_state_attempts", 12)), 1)
    state_res: dict = {}
    for attempt in range(state_attempts):
        state_res = _parse_js_result(evaluate(target_id, apply_state_js))
        if state_res.get("verified") or not state_res.get("success"):
            break
        if attempt + 1 < state_attempts and _sleep_or_stop(0.75, stop_event):
            close_tab(target_id)
            return {
                "success": False,
                "error": "stopped",
                "history_detail": "用户已请求停止",
                "skip_backoff": True,
            }, None

    close_tab(target_id)
    if not state_res.get("success"):
        return state_res, None
    if state_res.get("verified"):
        return {
            "success": True,
            "verified": True,
            "history_detail": f"前程无忧申请成功 ({state_res.get('status_text')})",
        }, None

    return {
        "success": False,
        "error": "job51_send_unverified",
        "history_detail": "前程无忧已完成立即投递和简历确认，但未检测到成功弹窗或已申请状态",
        "skip_backoff": True,
    }, None


def _send_liepin_greeting_once(
    job: dict,
    greeting: str,
    throttle_config: dict,
    stop_event: Event | None = None,
) -> tuple[dict, str | None]:
    """Execute Liepin-specific greeting and application flow for a single job."""
    access_guard = throttle_config.get("_platform_access_guard")
    if isinstance(access_guard, PlatformAccessGuard):
        try:
            access_guard.reserve("job_page")
        except PlatformSafetyStop as exc:
            return {
                "success": False,
                "error": exc.reason,
                "history_detail": "为了账户安全，已达到猎聘页面访问上限或仍处于风险冷却",
            }, None

    target_id = new_tab(job["url"], background=False)
    if not target_id:
        return {
            "success": False,
            "error": "open_page_failed",
            "history_detail": "无法打开猎聘岗位详情页",
            "skip_backoff": True,
        }, None

    if _stop_requested(stop_event):
        close_tab(target_id)
        return {
            "success": False,
            "error": "stopped",
            "history_detail": "用户已请求停止",
            "skip_backoff": True,
        }, None

    wait_for_load(target_id, timeout=15)

    if throttle_config.get("browse_before_greet", True):
        browse_min = float(throttle_config.get("browse_duration_min", 2))
        browse_max = float(throttle_config.get("browse_duration_max", 5))
        browse_time = random.uniform(min(browse_min, browse_max), max(browse_min, browse_max))
        scroll_js = """
        (() => {
            window.scrollBy({top: 270, behavior: 'smooth'});
            setTimeout(() => window.scrollBy({top: -110, behavior: 'smooth'}), 700);
        })()
        """
        try:
            evaluate(target_id, scroll_js)
        except Exception:
            pass
        if _sleep_or_stop(browse_time, stop_event):
            close_tab(target_id)
            return {
                "success": False,
                "error": "stopped",
                "history_detail": "用户已请求停止",
                "skip_backoff": True,
            }, None

    click_js = """
    (() => {
        const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
        const bodyText = normalize(document.body ? document.body.innerText : '');
        const pageText = `${bodyText} ${normalize(document.title)}`;
        const currentUrl = String(location.href || '');
        const currentHost = String(location.hostname || '');

        if (
            currentHost === 'safe.liepin.com' ||
            /captchaPage|安全中心/.test(currentUrl) ||
            /验证码|滑块|访问频繁|访问过于频繁|频率限制|账号异常|拒绝访问|安全验证|行为异常/.test(pageText)
        ) {
            return JSON.stringify({
                success: false,
                error: 'blocked',
                history_detail: '猎聘出现验证码或访问限制'
            });
        }

        const closedMarkers = [
            "职位已下线", "职位已下架", "该职位已关闭", "职位已关闭",
            "此职位已停止招聘", "该职位已暂停招聘", "职位不存在", "已停止招聘",
            "该职位暂不招人", "暂不招人", "访问的页面不存在", "页面不存在", "404"
        ];
        if (closedMarkers.some(m => pageText.includes(m))) {
            return JSON.stringify({
                success: false,
                error: 'job_page_unavailable',
                history_detail: '岗位已下线或关闭',
                skip_backoff: true
            });
        }

        if (
            currentHost.includes('wow.liepin.com') ||
            /请先登录|扫码登录|账号登录|登录后查看/.test(pageText)
        ) {
            return JSON.stringify({
                success: false,
                error: 'login_required',
                history_detail: '未登录猎聘岗位详情页或登录状态未同步',
                skip_backoff: true
            });
        }

        const isVisible = el => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' &&
                s.visibility !== 'hidden' && s.pointerEvents !== 'none';
        };
        const topActionSelector = [
            'section.job-apply-container',
            '.job-apply-operate',
            '.apply-box',
            '> a.btn-main[data-selector="chat-chat"]'
        ].join(' ');
        const topChatButton = document.querySelector(topActionSelector);
        if (!isVisible(topChatButton)) {
            const topActions = Array.from(document.querySelectorAll(
                'section.job-apply-container .job-apply-operate .apply-box > a'
            )).filter(isVisible).map(el => ({
                text: normalize(el.innerText || el.textContent),
                class_name: String(el.className || ''),
                data_selector: el.getAttribute('data-selector') || ''
            }));
            return JSON.stringify({
                success: false,
                error: 'action_button_waiting',
                history_detail: '等待猎聘右上角聊一聊按钮渲染',
                page_url: currentUrl,
                candidate_texts: topActions.map(item => item.text),
                top_actions: topActions
            });
        }

        const buttonText = normalize(topChatButton.innerText || topChatButton.textContent);
        const existingChat = /^(?:继续聊|继续沟通|已沟通|沟通中|已聊过)$/.test(buttonText);
        if (!existingChat && !/^(?:聊一聊|立即沟通|和TA聊聊|与TA聊聊|在线沟通|打招呼)$/.test(buttonText)) {
            return JSON.stringify({
                success: false,
                error: 'no_action_button',
                history_detail: `猎聘右上角主按钮文本异常: ${buttonText || '空'}`,
                skip_backoff: true,
                selector: topActionSelector
            });
        }

        const rect = topChatButton.getBoundingClientRect();
        topChatButton.scrollIntoView({block: 'center', inline: 'center'});
        topChatButton.click();
        return JSON.stringify({
            success: true,
            action: 'clicked',
            button_type: 'chat',
            button_text: buttonText,
            existing_chat: existingChat,
            selector: topActionSelector,
            element_tag: topChatButton.tagName,
            element_class: String(topChatButton.className || ''),
            element_x: Math.round(rect.x),
            element_y: Math.round(rect.y)
        });
    })()
    """
    action_attempts = max(int(throttle_config.get("_liepin_action_attempts", 12)), 1)
    click_res: dict = {}
    for attempt in range(action_attempts):
        click_res = _parse_js_result(evaluate(target_id, click_js))
        if click_res.get("success") or click_res.get("error") != "action_button_waiting":
            break
        if attempt + 1 < action_attempts and _sleep_or_stop(0.75, stop_event):
            close_tab(target_id)
            return {
                "success": False,
                "error": "stopped",
                "history_detail": "用户已请求停止",
                "skip_backoff": True,
            }, None

    if not click_res.get("success"):
        if click_res.get("error") == "action_button_waiting":
            click_res = {
                "success": False,
                "error": "no_action_button",
                "history_detail": "猎聘岗位页已加载，但等待后仍未找到沟通或应聘按钮",
                "skip_backoff": True,
            }
        close_tab(target_id)
        return click_res, None

    if click_res.get("already_sent"):
        close_tab(target_id)
        return click_res, None

    if _sleep_or_stop(2.0, stop_event):
        close_tab(target_id)
        return {
            "success": False,
            "error": "stopped",
            "history_detail": "用户已请求停止",
            "skip_backoff": True,
        }, None

    greeting_escaped = json.dumps(greeting or "", ensure_ascii=False)
    chat_state_js = f"""
    (() => {{
        const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
        const isVisible = el => {{
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
        }};
        const gText = {greeting_escaped};
        const normalizedGreeting = normalize(gText);
        const dialogs = Array.from(document.querySelectorAll(
            '.job-overseas-authorize-modal, .im-ui-basic-chat-modal, .im-ui-basic-chat-wrapper, [role="dialog"]'
        )).filter(isVisible);

        const overseasAuthorizationDialog = dialogs.find(dialog =>
            dialog.matches('.job-overseas-authorize-modal') ||
            /开启境外招聘方简历查阅授权/.test(normalize(dialog.innerText))
        );
        if (overseasAuthorizationDialog) {{
            return JSON.stringify({{
                success: false,
                error: 'liepin_cross_border_authorization_required',
                history_detail: '猎聘招聘方位于境外，需人工确认简历跨境查阅授权，已停止自动重试',
                skip_backoff: true
            }});
        }}

        const chatDialog = dialogs.find(dialog =>
            dialog.matches('.im-ui-basic-chat-modal, .im-ui-basic-chat-wrapper') ||
            !!dialog.querySelector('textarea.im-ui-textarea')
        );
        if (!chatDialog) {{
            return JSON.stringify({{success: true, verified: false, step: 'waiting_chat_dialog'}});
        }}

        const sentMessages = Array.from(chatDialog.querySelectorAll(
            '.im-ui-message-item-body.im-ui-message-item-send .im-ui-txt-content .text'
        ));
        const greetingMessage = sentMessages.find(message =>
            normalize(message.innerText || message.textContent) === normalizedGreeting
        );
        if (greetingMessage) {{
            return JSON.stringify({{
                success: true,
                verified: true,
                status_text: 'ai_greeting_message_present',
                sent_message: normalize(greetingMessage.innerText || greetingMessage.textContent)
            }});
        }}

        if (!normalizedGreeting) {{
            return JSON.stringify({{
                success: false,
                error: 'no_greeting',
                history_detail: '猎聘岗位缺少 AI 招呼语，不能完成聊天发送',
                skip_backoff: true
            }});
        }}

        const textarea = chatDialog.querySelector('textarea.im-ui-textarea');
        const sendButton = chatDialog.querySelector('button.im-ui-basic-send-btn');
        if (!isVisible(textarea) || !sendButton) {{
            return JSON.stringify({{success: true, verified: false, step: 'waiting_chat_controls'}});
        }}

        // “继续聊”和平台默认问候只代表会话已创建。点击发送后必须等待
        // 当前 AI 招呼语的完整发送方气泡出现，期间禁止再次填入或点击，避免重复发送。
        // 标记放在 window 上，避免聊天弹窗重渲染后 DOM dataset 丢失而二次点击发送。
        if (window.__allinPendingLiepinGreeting === normalizedGreeting) {{
            return JSON.stringify({{success: true, verified: false, step: 'waiting_message_verification'}});
        }}

        if (normalize(textarea.value) !== normalizedGreeting) {{
            const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
            if (setter) setter.call(textarea, gText);
            else textarea.value = gText;
            textarea.dispatchEvent(new Event('input', {{bubbles: true}}));
            textarea.dispatchEvent(new Event('change', {{bubbles: true}}));
            return JSON.stringify({{success: true, verified: false, step: 'greeting_filled'}});
        }}

        if (sendButton.disabled || !isVisible(sendButton)) {{
            return JSON.stringify({{success: true, verified: false, step: 'waiting_send_enabled'}});
        }}

        window.__allinPendingLiepinGreeting = normalizedGreeting;
        sendButton.click();
        return JSON.stringify({{success: true, verified: false, step: 'send_clicked'}});
    }})()
    """
    chat_attempts = max(int(throttle_config.get("_liepin_chat_state_attempts", 16)), 1)
    confirm_res: dict = {}
    for attempt in range(chat_attempts):
        confirm_res = _parse_js_result(evaluate(target_id, chat_state_js))
        if confirm_res.get("verified") or not confirm_res.get("success"):
            break
        if attempt + 1 < chat_attempts and _sleep_or_stop(0.5, stop_event):
            close_tab(target_id)
            return {
                "success": False,
                "error": "stopped",
                "history_detail": "用户已请求停止",
                "skip_backoff": True,
            }, None
    close_tab(target_id)
    if not confirm_res.get("success"):
        return confirm_res, None
    if confirm_res.get("verified"):
        return {
            "success": True,
            "verified": True,
            "history_detail": "猎聘 AI 招呼语已发送并在消息气泡中验证",
        }, None

    return {
        "success": False,
        "error": "liepin_send_unverified",
        "history_detail": f"猎聘聊天弹窗已打开，但 AI 招呼语未完成发送验证 ({confirm_res.get('step', 'unknown')})",
        "skip_backoff": True,
    }, None


class BaseSender(abc.ABC):
    """Abstract base sender handling common delivery orchestration across platforms."""

    platform_name: str = "base"

    def __init__(
        self,
        config: dict,
        *,
        force: bool = False,
        db_path: Path | str | None = None,
    ) -> None:
        self.config = config
        self.force = force
        self.db_path = db_path

    def _get_db(self):
        if self.db_path:
            return get_db(self.db_path)
        return get_db()

    def _get_throttle_config(self) -> dict:
        throttle_cfg = dict(self.config.get("throttle", {}))
        platform_cfg = self.config.get("platforms", {}).get(self.platform_name, {})
        if isinstance(platform_cfg, dict) and "throttle" in platform_cfg:
            throttle_cfg.update(platform_cfg["throttle"])
        if "_workbench_stop_event" in self.config:
            throttle_cfg["_workbench_stop_event"] = self.config["_workbench_stop_event"]
        return throttle_cfg

    @abc.abstractmethod
    def send_single_job(
        self,
        job: dict,
        greeting: str,
        throttle_config: dict,
        stop_event: Event | None = None,
        existing_target_ids: list[str] | None = None,
    ) -> tuple[dict, str | None]:
        """Perform platform-specific actions to deliver greeting/resume for a single job."""
        raise NotImplementedError

    def send_greetings(
        self,
        workbench_job_ids: list[str] | None = None,
    ) -> int:
        """Execute the delivery loop for this platform."""
        throttle_config = self._get_throttle_config()
        stop_event = throttle_config.get("_workbench_stop_event")
        send_report = self.config.setdefault("_workbench_send_report", {})
        for k, v in {
            "requested_count": len(workbench_job_ids) if workbench_job_ids else 0,
            "eligible_count": 0,
            "scheduled_count": 0,
            "attempted_count": 0,
            "sent_count": 0,
            "failed_count": 0,
            "deferred_count": len(workbench_job_ids) if workbench_job_ids else 0,
            "quota_deferred_count": 0,
            "already_sent": 0,
            "daily_limit": 0,
            "remaining_quota": 0,
            "unsupported_platform_ids": [],
            "stop_reason": None,
        }.items():
            send_report.setdefault(k, v)
        workbench_log = self.config.get("_workbench_log")

        def _log(msg: str) -> None:
            if workbench_log:
                workbench_log(msg)
            else:
                console.print(msg)

        if _stop_requested(stop_event):
            send_report["stop_reason"] = "stopped"
            return 0

        if not platform_supports(self.platform_name, "deliver"):
            _log(f"[yellow]平台 {self.platform_name} 暂不支持自动投递，跳过[/yellow]")
            send_report["stop_reason"] = "unsupported_platform"
            return 0

        db = self._get_db()
        access_guard = PlatformAccessGuard(db, self.config, "send", platform=self.platform_name)
        throttle_config["_platform_access_guard"] = access_guard

        try:
            access_guard.ensure_unlocked()
        except PlatformSafetyStop as exc:
            send_report["stop_reason"] = exc.reason
            _log(f"[yellow]为了账户安全，{self.platform_name} 平台风险冷却尚未结束，已停止投递[/yellow]")
            db.close()
            return 0

        day_off_prob = float(throttle_config.get("day_off_probability", 0.05))
        if not self.force and should_take_day_off(day_off_prob):
            _log(f"[yellow]🎲 今日 {self.platform_name} 随机休息（防检测），跳过发送[/yellow]")
            add_risk_event(db, "day_off", f"{self.platform_name} 随机休息日")
            send_report["stop_reason"] = "day_off"
            db.close()
            return 0

        send_windows = throttle_config.get("send_windows", [])
        window_checker = SendWindowChecker(send_windows)
        if not self.force and not window_checker.is_active():
            info = window_checker.next_window_info()
            _log(f"[yellow]⏰ 当前不在 {self.platform_name} 发送时间窗口内，暂不发送[/yellow]")
            _log(f"[dim]  {info}[/dim]")
            add_risk_event(db, "outside_window", f"{self.platform_name} {info}")
            send_report["stop_reason"] = "outside_window"
            db.close()
            return 0

        jobs = get_jobs_ready_to_send(db, platform=self.platform_name)
        if workbench_job_ids:
            jobs = [job for job in jobs if str(job["id"]) in workbench_job_ids]

        send_report["eligible_count"] = len(jobs)
        send_report["deferred_count"] = len(workbench_job_ids) if workbench_job_ids else len(jobs)

        if not jobs:
            _log(f"[yellow]没有已生成招呼语的待发送 {self.platform_name} 岗位[/yellow]")
            send_report["stop_reason"] = "no_ready_jobs"
            db.close()
            return 0

        daily_limit = int(throttle_config.get("daily_limit", 30))
        if self.platform_name == "boss":
            daily_limit = min(daily_limit, 50)

        interval_min = int(throttle_config.get("interval_min", 60))
        interval_max = int(throttle_config.get("interval_max", 180))

        already_sent = count_sent_today(db, platform=self.platform_name)
        remaining_quota = daily_limit - already_sent
        send_report["already_sent"] = already_sent
        send_report["daily_limit"] = daily_limit
        send_report["remaining_quota"] = max(remaining_quota, 0)

        if remaining_quota <= 0:
            _log(f"[yellow]今日已达 {self.platform_name} 发送上限 ({daily_limit})[/yellow]")
            send_report["quota_deferred_count"] = len(jobs)
            send_report["stop_reason"] = "daily_limit"
            db.close()
            return 0

        jobs_to_send = jobs[:remaining_quota]
        send_report["scheduled_count"] = len(jobs_to_send)
        send_report["quota_deferred_count"] = max(len(jobs) - len(jobs_to_send), 0)
        if send_report["quota_deferred_count"]:
            send_report["stop_reason"] = "daily_limit"

        throttle = RequestThrottle(delay_min=interval_min, delay_max=interval_max)
        backoff = ProgressiveBackoff()
        sent_count = 0

        _log(f"[bold]准备发送 {len(jobs_to_send)} 条 {self.platform_name} 招呼语[/bold] (今日已发 {already_sent}/{daily_limit})")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"[{self.platform_name}] 发送中", total=len(jobs_to_send))

            for index, job in enumerate(jobs_to_send):
                if _stop_requested(stop_event):
                    _log("[yellow]已请求停止，结束发送[/yellow]")
                    send_report["stop_reason"] = "stopped"
                    break

                greeting = job.get("greeting", "")
                if not greeting:
                    update_job_status(db, job["id"], "error")
                    update_job_last_error(db, job["id"], "该岗位没有已生成的招呼语，无法发送", "no_greeting")
                    send_report["attempted_count"] += 1
                    send_report["failed_count"] += 1
                    progress.update(task, advance=1)
                    continue

                current_job = f"{job.get('company') or '公司未知'}｜{job.get('title') or '职位未知'}"
                next_job = jobs_to_send[index + 1] if index + 1 < len(jobs_to_send) else None
                next_label = (
                    f"下一条：{next_job.get('company') or '公司未知'}｜{next_job.get('title') or '职位未知'}"
                    if next_job else "下一条：无"
                )

                if sent_count > 0:
                    if callable(workbench_log):
                        workbench_log(
                            f"招呼语进度 {index + 1}/{len(jobs_to_send)}\n等待发送：{current_job}\n{next_label}"
                        )
                    delay = throttle.wait(stop_event=stop_event)
                    if _stop_requested(stop_event):
                        send_report["stop_reason"] = "stopped"
                        break
                    _log(f"[dim]已等待 {delay:.0f} 秒[/dim]")

                if callable(workbench_log):
                    workbench_log(
                        f"招呼语进度 {index + 1}/{len(jobs_to_send)}\n正在发送：{current_job}\n{next_label}"
                    )
                _log(f"正在发送: {current_job} ({next_label})")
                send_report["attempted_count"] += 1

                existing_target_ids = [t["targetId"] for t in get_page_targets() if "targetId" in t]

                result_data, cleanup_target_id = self.send_single_job(
                    job,
                    greeting,
                    throttle_config,
                    stop_event,
                    existing_target_ids=existing_target_ids,
                )

                if result_data.get("error") == "no_chat_input" and cleanup_target_id:
                    _log("[yellow]    ! 未进入具体聊天会话，重新打开岗位页再试一次[/yellow]")
                    close_tab(cleanup_target_id)
                    cleanup_target_id = None
                    result_data, cleanup_target_id = self.send_single_job(
                        job,
                        greeting,
                        throttle_config,
                        stop_event,
                        existing_target_ids=existing_target_ids,
                    )
                    if result_data.get("error") == "stopped":
                        send_report["stop_reason"] = "stopped"
                        if cleanup_target_id:
                            close_tab(cleanup_target_id)
                        break

                if cleanup_target_id:
                    close_tab(cleanup_target_id)

                if result_data.get("success"):
                    update_job_status(db, job["id"], "sent")
                    update_job_last_error(db, job["id"], "")
                    matched_resume = job.get("matched_resume_name")
                    detail_prefix = f"[{matched_resume}] " if matched_resume else ""
                    add_history(db, job["id"], "sent", f"{detail_prefix}{greeting[:50]}")
                    sent_count += 1
                    send_report["sent_count"] = sent_count
                    throttle.mark()
                    backoff.record_success()
                    resume_tag = f" (简历: {matched_resume})" if matched_resume else ""
                    _log(f"[green]✓ 成功: {current_job}{resume_tag}[/green]")
                else:
                    error = result_data.get("error", "unknown")
                    if error == "stopped":
                        send_report["stop_reason"] = "stopped"
                        break

                    send_report["failed_count"] += 1
                    history_detail = result_data.get("history_detail", f"发送失败: {error}")
                    update_job_status(db, job["id"], "error")
                    update_job_last_error(db, job["id"], history_detail, error)
                    add_history(db, job["id"], "error", history_detail)

                    if result_data.get("skip_backoff"):
                        progress.update(task, advance=1)
                        continue

                    throttle.mark()
                    pause_duration = backoff.record_error()
                    add_risk_event(db, "send_error", f"{self.platform_name} {error} (连续{backoff._consecutive_errors}次)")

                    if error in ["captcha", "rate_limit", "blocked", "login_required"]:
                        _log(f"\n[red]⚠ 检测到 {self.platform_name} 风控信号: {error}，安全暂停[/red]")
                        add_risk_event(db, error, f"触发风控: {error}")
                        p_safety = self.config.get("platforms", {}).get(self.platform_name, {}).get("safety", {}) if isinstance(self.config.get("platforms"), dict) else {}
                        lock_minutes = p_safety.get("risk_lock_minutes") or self.config.get("safety", {}).get("risk_lock_minutes", 10)
                        try:
                            lock_minutes = max(int(lock_minutes), 1)
                        except (TypeError, ValueError):
                            lock_minutes = 10
                        set_platform_safety_lock(db, error, minutes=lock_minutes, platform=self.platform_name)
                        send_report["stop_reason"] = error
                        break

                    if backoff.should_pause_long:
                        _log(f"\n[red]⚠ 连续错误过多，暂停 {int(pause_duration/60)} 分钟[/red]")
                        add_risk_event(db, "backoff_pause", f"暂停{int(pause_duration)}秒")
                        p_safety = self.config.get("platforms", {}).get(self.platform_name, {}).get("safety", {}) if isinstance(self.config.get("platforms"), dict) else {}
                        lock_minutes = p_safety.get("risk_lock_minutes") or self.config.get("safety", {}).get("risk_lock_minutes", 10)
                        try:
                            lock_minutes = max(int(lock_minutes), 1)
                        except (TypeError, ValueError):
                            lock_minutes = 10
                        set_platform_safety_lock(db, "consecutive_errors", minutes=lock_minutes, platform=self.platform_name)
                        send_report["stop_reason"] = "consecutive_errors"
                        break
                    elif pause_duration > 0:
                        _log(f"\n[yellow]  错误退避: 额外等待 {int(pause_duration)}秒[/yellow]")
                        if _sleep_or_stop(pause_duration, stop_event):
                            send_report["stop_reason"] = "stopped"
                            break

                progress.update(task, advance=1)

        _log(f"\n[green]✓ {self.platform_name} 成功发送 {sent_count} 条[/green]")
        report_total = len(workbench_job_ids) if workbench_job_ids else len(jobs)
        send_report["sent_count"] = sent_count
        send_report["deferred_count"] = max(
            report_total - sent_count - send_report["failed_count"],
            0,
        )
        db.close()
        return sent_count


class BossSender(BaseSender):
    platform_name = "boss"

    def send_single_job(
        self,
        job: dict,
        greeting: str,
        throttle_config: dict,
        stop_event: Event | None = None,
        existing_target_ids: list[str] | None = None,
    ) -> tuple[dict, str | None]:
        return _send_greeting_once(job, greeting, throttle_config)


class ZhilianSender(BaseSender):
    platform_name = "zhilian"

    def send_single_job(
        self,
        job: dict,
        greeting: str,
        throttle_config: dict,
        stop_event: Event | None = None,
        existing_target_ids: list[str] | None = None,
    ) -> tuple[dict, str | None]:
        return _send_zhilian_greeting_once(job, greeting, throttle_config, stop_event)


class Job51Sender(BaseSender):
    platform_name = "51job"

    def send_single_job(
        self,
        job: dict,
        greeting: str,
        throttle_config: dict,
        stop_event: Event | None = None,
        existing_target_ids: list[str] | None = None,
    ) -> tuple[dict, str | None]:
        return _send_job51_greeting_once(job, greeting, throttle_config, stop_event)


class LiepinSender(BaseSender):
    platform_name = "liepin"

    def send_single_job(
        self,
        job: dict,
        greeting: str,
        throttle_config: dict,
        stop_event: Event | None = None,
        existing_target_ids: list[str] | None = None,
    ) -> tuple[dict, str | None]:
        return _send_liepin_greeting_once(job, greeting, throttle_config, stop_event)


PLATFORM_SENDERS: dict[str, type[BaseSender]] = {
    "boss": BossSender,
    "zhilian": ZhilianSender,
    "51job": Job51Sender,
    "liepin": LiepinSender,
}


def get_sender(
    platform: str,
    config: dict,
    force: bool = False,
    db_path: Path | str | None = None,
) -> BaseSender:
    """Instantiate a BaseSender for the given platform."""
    sender_cls = PLATFORM_SENDERS.get(platform)
    if not sender_cls:
        raise ValueError(f"Unsupported sender platform: {platform}")
    return sender_cls(config, force=force, db_path=db_path)


def send_greetings(
    config: dict,
    force: bool = False,
    db_path: Path | str | None = None,
    platform: str | None = None,
) -> int:
    """Send generated greetings across platforms. Returns total count of successfully sent."""
    workbench_job_ids = [str(job_id) for job_id in config.get("_workbench_job_ids", []) if str(job_id)]
    target_platform = platform or config.get("_platform")

    # Scenario A: Explicit target platform requested
    if target_platform:
        sender = get_sender(target_platform, config, force=force, db_path=db_path)
        return sender.send_greetings(workbench_job_ids=workbench_job_ids or None)

    # Scenario B: Explicit workbench_job_ids supplied (dispatch by each job's source_platform)
    if workbench_job_ids:
        db = get_db(db_path)
        try:
            placeholders = ",".join("?" for _ in workbench_job_ids)
            rows = db.execute(
                f"SELECT id, COALESCE(source_platform, 'boss') as platform FROM jobs WHERE id IN ({placeholders})",
                workbench_job_ids,
            ).fetchall()
            jobs_by_platform: dict[str, list[str]] = {}
            for row in rows:
                p = str(row["platform"] or "boss")
                jobs_by_platform.setdefault(p, []).append(str(row["id"]))
        finally:
            db.close()

        total_sent = 0
        send_report = config.setdefault("_workbench_send_report", {})
        for k, v in {
            "requested_count": len(workbench_job_ids),
            "eligible_count": 0,
            "scheduled_count": 0,
            "attempted_count": 0,
            "sent_count": 0,
            "failed_count": 0,
            "deferred_count": len(workbench_job_ids),
            "quota_deferred_count": 0,
            "already_sent": 0,
            "daily_limit": 0,
            "remaining_quota": 0,
            "unsupported_platform_ids": [],
            "stop_reason": None,
        }.items():
            send_report.setdefault(k, v)

        for plat, plat_job_ids in jobs_by_platform.items():
            if not platform_supports(plat, "deliver") or plat not in PLATFORM_SENDERS:
                send_report.setdefault("unsupported_platform_ids", []).extend(plat_job_ids)
                console.print(f"[yellow]平台 {plat} 暂未提供投递适配器，跳过 {len(plat_job_ids)} 个岗位[/yellow]")
                continue

            plat_config = dict(config)
            plat_config["_workbench_send_report"] = {}
            sender = get_sender(plat, plat_config, force=force, db_path=db_path)
            sent = sender.send_greetings(workbench_job_ids=plat_job_ids)
            total_sent += sent
            sub_report = plat_config.get("_workbench_send_report", {})
            send_report["eligible_count"] += int(sub_report.get("eligible_count", 0) or 0)
            send_report["scheduled_count"] += int(sub_report.get("scheduled_count", 0) or 0)
            send_report["attempted_count"] += int(sub_report.get("attempted_count", 0) or 0)
            send_report["sent_count"] += int(sub_report.get("sent_count", sent) or 0)
            send_report["failed_count"] += int(sub_report.get("failed_count", 0) or 0)
            send_report["quota_deferred_count"] += int(sub_report.get("quota_deferred_count", 0) or 0)
            send_report["already_sent"] += int(sub_report.get("already_sent", 0) or 0)
            send_report["daily_limit"] += int(sub_report.get("daily_limit", 0) or 0)
            send_report["remaining_quota"] += int(sub_report.get("remaining_quota", 0) or 0)
            if sub_report.get("stop_reason") and not send_report.get("stop_reason"):
                send_report["stop_reason"] = sub_report["stop_reason"]

        send_report["deferred_count"] = max(
            send_report["requested_count"] - send_report["sent_count"] - send_report["failed_count"],
            0,
        )
        return total_sent

    # Scenario C: Full run (CLI allin send or pipeline) without explicit job IDs
    platforms_cfg = config.get("platforms", {})
    candidate_platforms: list[str] = []
    for plat in ["boss", "zhilian", "51job", "liepin"]:
        plat_cfg = platforms_cfg.get(plat, {})
        is_enabled = plat_cfg.get("enabled", True if plat == "boss" and not platforms_cfg else False)
        if is_enabled and platform_supports(plat, "deliver") and plat in PLATFORM_SENDERS:
            candidate_platforms.append(plat)

    if not candidate_platforms:
        candidate_platforms = ["boss"]

    total_sent = 0
    send_report = config.setdefault("_workbench_send_report", {})
    for k, v in {
        "requested_count": 0,
        "eligible_count": 0,
        "scheduled_count": 0,
        "attempted_count": 0,
        "sent_count": 0,
        "failed_count": 0,
        "deferred_count": 0,
        "quota_deferred_count": 0,
        "already_sent": 0,
        "daily_limit": 0,
        "remaining_quota": 0,
        "unsupported_platform_ids": [],
        "stop_reason": None,
    }.items():
        send_report.setdefault(k, v)

    for plat in candidate_platforms:
        plat_config = dict(config)
        plat_config["_workbench_send_report"] = {}
        sender = get_sender(plat, plat_config, force=force, db_path=db_path)
        sent = sender.send_greetings()
        total_sent += sent
        sub_report = plat_config.get("_workbench_send_report", {})
        send_report["eligible_count"] += int(sub_report.get("eligible_count", 0) or 0)
        send_report["scheduled_count"] += int(sub_report.get("scheduled_count", 0) or 0)
        send_report["attempted_count"] += int(sub_report.get("attempted_count", 0) or 0)
        send_report["sent_count"] += int(sub_report.get("sent_count", sent) or 0)
        send_report["failed_count"] += int(sub_report.get("failed_count", 0) or 0)
        send_report["quota_deferred_count"] += int(sub_report.get("quota_deferred_count", 0) or 0)
        send_report["already_sent"] += int(sub_report.get("already_sent", 0) or 0)
        send_report["daily_limit"] += int(sub_report.get("daily_limit", 0) or 0)
        send_report["remaining_quota"] += int(sub_report.get("remaining_quota", 0) or 0)
        if sub_report.get("stop_reason") and not send_report.get("stop_reason"):
            send_report["stop_reason"] = sub_report["stop_reason"]

    return total_sent

