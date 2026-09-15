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

