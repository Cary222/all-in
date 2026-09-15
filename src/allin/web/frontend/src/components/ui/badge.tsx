import { cn } from '@/lib/utils'
import { cva, type VariantProps } from 'class-variance-authority'
import { HTMLAttributes } from 'react'

// Business states remain explicit in text; color communicates only the semantic group.
const badgeVariants = cva(
  'inline-flex items-center rounded-md border border-transparent px-2 py-0.5 text-[11px] font-medium leading-5',
  {
    variants: {
      variant: {
        default: 'bg-status-processing text-status-processing-foreground',
        pending: 'bg-status-neutral text-status-neutral-foreground',
        scored: 'bg-status-processing text-status-processing-foreground',
        ready: 'bg-status-processing text-status-processing-foreground',
        approved: 'bg-status-attention text-status-attention-foreground',
        skipped: 'bg-status-neutral text-status-neutral-foreground',
        sent: 'bg-status-success text-status-success-foreground',
        replied: 'bg-status-success text-status-success-foreground',
        resume_sent: 'bg-status-success text-status-success-foreground',
        needs_resume: 'bg-status-attention text-status-attention-foreground',
        follow_up_sent: 'bg-status-processing text-status-processing-foreground',
        reply_pending: 'bg-status-attention text-status-attention-foreground',
        auto_replied: 'bg-status-success text-status-success-foreground',
        rejected: 'bg-status-danger text-status-danger-foreground',
        error: 'bg-status-danger text-status-danger-foreground',
        filtered: 'bg-status-neutral text-status-neutral-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
)

export interface BadgeProps extends HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}
