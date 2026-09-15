import { ResumeDualPreview } from '@/components/config/ResumeDualPreview'
import { ResumeFileCard } from '@/components/config/ResumeFileCard'
import { Button } from '@/components/ui/button'
import {
  afterDropOutside,
  afterResumeLoadFailure,
  afterSuccessfulResumeLoad,
  afterUploadAttempt,
  emptyResumePanelMessages,
  resumeDropOutsideTip,
  resumeLoadErrorMessage,
  resumePanelVisibleMessage,
  shouldSyncResumePath,
  type ResumeInfo,
  type ResumePanelMessages,
} from '@/lib/resumeDisplay'
import { Loader2, Plus, Upload } from 'lucide-react'
import { useCallback, useEffect, useState, type ChangeEvent, type DragEvent } from 'react'

type ResumeUploadSectionProps = {
  currentResumePath?: string
  updateConfig: (path: string, value: unknown, options?: { markDirty?: boolean }) => void
}

/** Multi-resume management and upload section for the config page. */
export function ResumeUploadSection({ currentResumePath = '', updateConfig }: ResumeUploadSectionProps) {
  const [resumes, setResumes] = useState<ResumeInfo[]>([])
  const [panelMessages, setPanelMessages] = useState<ResumePanelMessages>(emptyResumePanelMessages)
  const [resumeDragActive, setResumeDragActive] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadDirection, setUploadDirection] = useState('')
  const [expandedPreviewId, setExpandedPreviewId] = useState<string | null>(null)
  const [editingResumeId, setEditingResumeId] = useState<string | null>(null)

  const panelMessage = resumePanelVisibleMessage(panelMessages)

  // Fetch all resumes from /api/resumes with fallback to /api/resume
  const loadResumes = useCallback(async () => {
    try {
      const res = await fetch('/api/resumes')
      if (res.ok) {
        const data = await res.json()
        if (data && Array.isArray(data.resumes) && data.resumes.length > 0) {
          setResumes(data.resumes)
          setPanelMessages((prev) => afterSuccessfulResumeLoad(prev))
          const defaultResume = data.resumes.find((r: ResumeInfo) => r.is_default) || data.resumes[0]
          if (defaultResume && shouldSyncResumePath(currentResumePath, defaultResume.path)) {
            updateConfig('profile.resume_path', defaultResume.path, { markDirty: false })
          }
          return
        }
      }

      // Fallback to single-resume endpoint /api/resume
      const singleRes = await fetch('/api/resume')
      const singleData = await singleRes.json().catch(() => null)
      if (singleRes.ok && singleData && singleData.filename) {
        setResumes([singleData])
        setPanelMessages((prev) => afterSuccessfulResumeLoad(prev))
        if (shouldSyncResumePath(currentResumePath, singleData.path)) {
          updateConfig('profile.resume_path', singleData.path, { markDirty: false })
        }
      } else {
        setResumes([])
        setPanelMessages((prev) => afterSuccessfulResumeLoad(prev))
      }
    } catch {
      setPanelMessages((prev) => afterResumeLoadFailure(prev, '网络错误，无法读取简历列表'))
    }
  }, [currentResumePath, updateConfig])

  useEffect(() => {
    loadResumes()
  }, [loadResumes])

  useEffect(() => {
    const preventBrowserNavigation = (event: globalThis.DragEvent) => {
      event.preventDefault()
    }
    const tipWhenDroppedOutsideZone = (event: globalThis.DragEvent) => {
      event.preventDefault()
      setResumeDragActive(false)
      if (event.dataTransfer?.files?.length) {
        setPanelMessages((prev) => afterDropOutside(prev, resumeDropOutsideTip()))
      }
    }
    window.addEventListener('dragover', preventBrowserNavigation)
    window.addEventListener('drop', tipWhenDroppedOutsideZone)
    return () => {
      window.removeEventListener('dragover', preventBrowserNavigation)
      window.removeEventListener('drop', tipWhenDroppedOutsideZone)
    }
  }, [])

  // Upload one or multiple files
  const uploadResumeFiles = useCallback(
    async (files: FileList | File[]) => {
      if (!files || files.length === 0) return
      setUploading(true)
      setPanelMessages(afterUploadAttempt(emptyResumePanelMessages()))

      let errorCount = 0
      let lastErrorMessage = ''

      for (let i = 0; i < files.length; i++) {
        const file = files[i]
        const form = new FormData()
        form.append('file', file)
        if (uploadDirection.trim()) {
          form.append('target_direction', uploadDirection.trim())
        }
        // If no resumes exist yet, make the first uploaded resume default
        if (resumes.length === 0 && i === 0) {
          form.append('is_default', 'true')
        }

        try {
          const res = await fetch('/api/resumes/upload', { method: 'POST', body: form })
          const data = await res.json()
          if (!res.ok || !data.success) {
            errorCount++
            lastErrorMessage = data.error || `${file.name} 上传失败`
          }
        } catch {
          errorCount++
          lastErrorMessage = `${file.name} 上传发生网络错误`
        }
      }

      setUploading(false)
      if (errorCount > 0) {
        setPanelMessages((prev) =>
          afterResumeLoadFailure(prev, `共 ${files.length} 个文件，${errorCount} 个上传失败: ${lastErrorMessage}`),
        )
      } else {
        setPanelMessages(emptyResumePanelMessages())
      }
      await loadResumes()
    },
    [loadResumes, resumes.length, uploadDirection],
  )

  const handleResumeFileInput = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    try {
      await uploadResumeFiles(files)
    } finally {
      e.target.value = ''
    }
  }

  const handleResumeDragOver = (e: DragEvent<HTMLElement>) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
    setResumeDragActive(true)
  }

  const handleResumeDragLeave = (e: DragEvent<HTMLElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setResumeDragActive(false)
  }

  const handleResumeDrop = async (e: DragEvent<HTMLElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setResumeDragActive(false)
    const files = e.dataTransfer.files
    if (!files || files.length === 0) return
    await uploadResumeFiles(files)
  }

  // Delete resume
  const handleDeleteResume = async (resume: ResumeInfo) => {
    const resumeId = resume.id
    const confirmName = resume.name || resume.filename
    if (!window.confirm(`确定要删除简历「${confirmName}」吗？`)) {
      return
    }
    try {
      const url = resumeId ? `/api/resumes/${resumeId}` : '/api/resume'
      const res = await fetch(url, { method: 'DELETE' })
      const data = await res.json().catch(() => null)
      if (!res.ok || !data?.success) {
        setPanelMessages((prev) =>
          afterResumeLoadFailure(prev, (data && data.error) || '删除简历失败'),
        )
        return
      }
      if (expandedPreviewId === resumeId) {
        setExpandedPreviewId(null)
      }
      await loadResumes()
    } catch {
      setPanelMessages((prev) => afterResumeLoadFailure(prev, '网络错误，删除简历失败'))
    }
  }

  // Set default resume
  const handleSetDefault = async (resumeId?: string) => {
    if (!resumeId) return
    try {
      const res = await fetch(`/api/resumes/${resumeId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_default: true }),
      })
      const data = await res.json().catch(() => null)
      if (!res.ok || !data?.success) {
        setPanelMessages((prev) =>
          afterResumeLoadFailure(prev, (data && data.error) || '设为默认简历失败'),
        )
        return
      }
      await loadResumes()
    } catch {
      setPanelMessages((prev) => afterResumeLoadFailure(prev, '网络错误，无法更新默认简历'))
    }
  }

  // Save metadata edit
  const handleSaveEdit = async (resumeId?: string, name?: string, targetDirection?: string) => {
    if (!resumeId) return
    try {
      const res = await fetch(`/api/resumes/${resumeId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, target_direction: targetDirection }),
      })
      const data = await res.json().catch(() => null)
      if (!res.ok || !data?.success) {
        setPanelMessages((prev) =>
          afterResumeLoadFailure(prev, (data && data.error) || '更新简历信息失败'),
        )
        return
      }
      setEditingResumeId(null)
      await loadResumes()
    } catch {
      setPanelMessages((prev) => afterResumeLoadFailure(prev, '网络错误，无法更新简历信息'))
    }
  }

  // Toggle preview and fetch detail content if needed
  const handleTogglePreview = async (resume: ResumeInfo) => {
    const resumeId = resume.id || resume.path
    if (expandedPreviewId === resumeId) {
      setExpandedPreviewId(null)
      return
    }

    if (resume.id && !resume.content) {
      try {
        const res = await fetch(`/api/resumes/${resume.id}`)
        if (res.ok) {
          const detail = await res.json()
          if (detail && detail.content) {
            setResumes((prev) =>
              prev.map((r) => (r.id === resume.id ? { ...r, content: detail.content } : r)),
            )
          }
        }
      } catch {
        // ignore content load error; markdown panel will show fallback
      }
    }
    setExpandedPreviewId(resumeId)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <label className="block text-xs font-semibold text-foreground">
          简历文件与多版本管理
        </label>
        <span className="text-xs text-muted">
          已上传 {resumes.length} 份简历（支持多份简历自适应匹配）
        </span>
      </div>

      {/* Resume Cards List */}
      {resumes.length > 0 ? (
        <div className="space-y-2.5">
          {resumes.map((resume, idx) => {
            const resumeKey = resume.id || resume.path || String(idx)
            const isPreviewOpen = expandedPreviewId === resumeKey
            const isEditing = editingResumeId === resumeKey

            return (
              <ResumeFileCard
                key={resumeKey}
                info={resume}
                previewExpanded={isPreviewOpen}
                isEditing={isEditing}
                onDelete={() => handleDeleteResume(resume)}
                onSetDefault={resume.id ? () => handleSetDefault(resume.id) : undefined}
                onTogglePreview={() => handleTogglePreview(resume)}
                onStartEdit={resume.id ? () => setEditingResumeId(resumeKey) : undefined}
                onCancelEdit={() => setEditingResumeId(null)}
                onSaveEdit={(name, dir) => handleSaveEdit(resume.id, name, dir)}
                footer={
                  isPreviewOpen ? (
                    <ResumeDualPreview
                      key={`${resume.path}:${resume.cache_buster || ''}`}
                      info={resume}
                    />
                  ) : null
                }
              />
            )
          })}
        </div>
      ) : null}

      {/* Always-visible Upload Area */}
      <div
        className={`rounded-lg border-2 border-dashed p-4 transition-colors ${
          resumeDragActive ? 'border-primary bg-primary/5' : 'border-card-border bg-slate-50/70 hover:border-primary/50'
        }`}
        onDragEnter={handleResumeDragOver}
        onDragOver={handleResumeDragOver}
        onDragLeave={handleResumeDragLeave}
        onDrop={handleResumeDrop}
      >
        <div className="flex flex-col items-center justify-center text-center">
          {uploading ? (
            <div className="flex items-center gap-2 py-4 text-xs font-medium text-primary">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span>简历正在解析与上传中...</span>
            </div>
          ) : (
            <>
              <div className="mb-2 flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-muted">
                <Upload className="h-4 w-4 text-slate-600" />
              </div>
              <div className="text-xs font-medium text-foreground">
                拖拽或点击上传简历文件（支持多份）
              </div>
              <p className="mt-1 text-[11px] text-muted">
                支持 .pdf、.docx、.md 文件，AI 评分与一键投递将根据求职方向智能匹配
              </p>

              {/* Optional Quick Tagging for Upload */}
              <div className="mt-3 flex max-w-sm items-center gap-2">
                <input
                  type="text"
                  placeholder="预设求职方向 (可选，如: 后端开发)"
                  value={uploadDirection}
                  onChange={(e) => setUploadDirection(e.target.value)}
                  className="rounded border border-card-border bg-white px-2.5 py-1 text-xs text-foreground placeholder:text-muted focus:border-primary focus:outline-none"
                />
                <label className="inline-flex cursor-pointer items-center rounded bg-primary px-3 py-1 text-xs font-medium text-white shadow-sm hover:bg-primary/90">
                  <Plus className="mr-1 h-3.5 w-3.5" />
                  选择文件
                  <input
                    type="file"
                    multiple
                    accept=".md,.docx,.pdf,application/pdf"
                    onChange={handleResumeFileInput}
                    className="hidden"
                  />
                </label>
              </div>
            </>
          )}
        </div>
      </div>

      {panelMessage ? (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{panelMessage}</p>
      ) : null}
    </div>
  )
}

