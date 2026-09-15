import { cn } from '@/lib/utils'
import { forwardRef, InputHTMLAttributes } from 'react'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      className={cn(
        'flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm text-foreground transition-[border-color,box-shadow,background-color] duration-150 placeholder:text-muted/75 hover:border-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/15 disabled:cursor-not-allowed disabled:bg-muted-surface disabled:text-muted',
        className
      )}
      ref={ref}
      {...props}
    />
  )
)
Input.displayName = 'Input'
