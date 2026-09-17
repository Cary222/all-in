export const PLATFORM_LABELS: Record<string, string> = {
  boss: 'BOSS 直聘',
  zhilian: '智联招聘',
  '51job': '前程无忧',
  liepin: '猎聘',
}

export const PLATFORM_SHORT_LABELS: Record<string, string> = {
  boss: 'BOSS',
  zhilian: '智联',
  '51job': '51job',
  liepin: '猎聘',
}

export const FULL_FLOW_SUPPORTED_PLATFORMS = new Set(['boss', 'zhilian', '51job', 'liepin'])

export function platformSupportsFullFlow(platform: string): boolean {
  return FULL_FLOW_SUPPORTED_PLATFORMS.has(platform)
}

// Platforms whose HR conversations are readable from the web UI. 51job has no web
// IM at all (verified live: the job page only offers "微信扫码与HR沟通"), so its
// replies can only be read in the WeChat service account or the app — monitoring
// cannot see them and must say so instead of appearing to work.
const WEB_REPLY_MONITORING_PLATFORMS = new Set(['boss', 'zhilian', 'liepin'])

export function platformSupportsReplyMonitoring(platform: string): boolean {
  return WEB_REPLY_MONITORING_PLATFORMS.has(platform)
}

// Short, user-facing reason shown where monitoring limitations matter.
export function platformReplyMonitoringNote(platform: string): string {
  if (platformSupportsReplyMonitoring(platform)) return ''
  if (platform === '51job') return '前程无忧网页端没有聊天窗口，HR 回复只能在微信服务号或 APP 中查看，无法自动监测。'
  return '该平台暂不支持网页端回复监测。'
}

