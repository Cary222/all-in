import { cn } from '@/lib/utils'
import { forwardRef, SelectHTMLAttributes } from 'react'

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select
      className={cn(
        'flex h-9 w-full appearance-none rounded-md border border-input bg-card px-3 py-1 pr-9 text-sm text-foreground transition-[border-color,box-shadow,background-color] duration-150 hover:border-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/15 disabled:cursor-not-allowed disabled:bg-muted-surface disabled:text-muted',
        className
      )}
      ref={ref}
      {...props}
    >
      {children}
    </select>
  )
)
Select.displayName = 'Select'
