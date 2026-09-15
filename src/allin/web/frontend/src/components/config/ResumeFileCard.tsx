import { Button } from '@/components/ui/button'
import { resumeSizeLabel, type ResumeInfo } from '@/lib/resumeDisplay'
import { Check, Eye, EyeOff, Pencil, Star, Trash2, X } from 'lucide-react'
import { useState, type DragEvent, type ReactNode } from 'react'

type ResumeFileCardProps = {
  info: ResumeInfo
  dragActive?: boolean
  isEditing?: boolean
  previewExpanded?: boolean
  onDelete: () => void
  onSetDefault?: () => void
  onTogglePreview?: () => void
  onStartEdit?: () => void
  onCancelEdit?: () => void
  onSaveEdit?: (name: string, targetDirection: string) => void
  onDragEnter?: (e: DragEvent<HTMLElement>) => void
  onDragOver?: (e: DragEvent<HTMLElement>) => void
  onDragLeave?: (e: DragEvent<HTMLElement>) => void
  onDrop?: (e: DragEvent<HTMLElement>) => void
  footer?: ReactNode
}

/** Uploaded resume status card with multi-resume management actions. */
export function ResumeFileCard({
  info,
  dragActive = false,
  isEditing = false,
  previewExpanded = false,
  onDelete,
  onSetDefault,
  onTogglePreview,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onDragEnter,
  onDragOver,
  onDragLeave,
  onDrop,
  footer,
}: ResumeFileCardProps) {
  const [editName, setEditName] = useState(info.name || '')
  const [editDirection, setEditDirection] = useState(info.target_direction || '')

  const displayName = info.name && info.name.trim() ? info.name : info.filename

  return (
    <div
      className={`rounded-lg border bg-white p-3.5 shadow-sm transition-colors ${
        info.is_default ? 'border-emerald-300 ring-1 ring-emerald-100' : 'border-card-border'
      } ${dragActive ? 'border-primary ring-2 ring-primary/20' : ''}`}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-semibold text-foreground" title={displayName}>
              {displayName}
            </span>
            {info.is_default ? (
              <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 border border-emerald-200">
                <Star className="h-3 w-3 fill-emerald-500 text-emerald-500" />
                默认简历
              </span>
            ) : null}
            {info.target_direction ? (
              <span className="inline-flex items-center rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 border border-blue-200">
                方向: {info.target_direction}
              </span>
            ) : null}
            {info.has_original_pdf ? (
              <span className="inline-flex items-center rounded bg-purple-50 px-1.5 py-0.5 text-xs text-purple-700 border border-purple-200">
                含原 PDF
              </span>
            ) : null}
          </div>

          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
            <span className="font-mono">{info.filename}</span>
            <span>{info.size_label || resumeSizeLabel(info)}</span>
            {info.uploaded_at ? <span>上传于 {info.uploaded_at}</span> : null}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-1.5 self-end sm:self-auto">
          {!info.is_default && onSetDefault ? (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={onSetDefault}
              className="h-7 px-2 text-xs text-slate-700 hover:text-emerald-700"
              title="设为投递默认简历"
            >
              <Star className="mr-1 h-3 w-3" />
              设为默认
            </Button>
          ) : null}

          {onTogglePreview ? (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={onTogglePreview}
              className="h-7 px-2 text-xs text-slate-700"
              title={previewExpanded ? '收起预览' : '查看原件与转换内容'}
            >
              {previewExpanded ? (
                <>
                  <EyeOff className="mr-1 h-3 w-3 text-muted" />
                  收起预览
                </>
              ) : (
                <>
                  <Eye className="mr-1 h-3 w-3 text-muted" />
                  预览
                </>
              )}
            </Button>
          ) : null}

          {onStartEdit ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setEditName(info.name || '')
                setEditDirection(info.target_direction || '')
                onStartEdit()
              }}
              className="h-7 w-7 p-0 text-slate-600 hover:text-primary"
              title="编辑简历名称与方向"
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          ) : null}

          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onDelete}
            className="h-7 w-7 p-0 text-slate-400 hover:bg-red-50 hover:text-red-600"
            title="删除这份简历"
            aria-label="删除简历"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Inline Edit Form */}
      {isEditing && onSaveEdit ? (
        <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">简历自定义名称</label>
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="例如: 资深后端工程师简历"
                className="w-full rounded border border-card-border bg-white px-2.5 py-1 text-xs text-foreground focus:border-primary focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">求职 / 投递方向</label>
              <input
                type="text"
                value={editDirection}
                onChange={(e) => setEditDirection(e.target.value)}
                placeholder="例如: Go / Python 后端"
                className="w-full rounded border border-card-border bg-white px-2.5 py-1 text-xs text-foreground focus:border-primary focus:outline-none"
              />
            </div>
          </div>
          <div className="mt-2.5 flex justify-end gap-2">
            {onCancelEdit ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={onCancelEdit}
                className="h-6 px-2 text-xs"
              >
                <X className="mr-1 h-3 w-3" />
                取消
              </Button>
            ) : null}
            <Button
              type="button"
              variant="default"
              size="sm"
              onClick={() => onSaveEdit(editName, editDirection)}
              className="h-6 px-2.5 text-xs"
            >
              <Check className="mr-1 h-3 w-3" />
              保存
            </Button>
          </div>
        </div>
      ) : null}

      {footer}
    </div>
  )
}
