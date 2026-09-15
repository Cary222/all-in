import { cn } from '@/lib/utils'
import type { CSSProperties } from 'react'

interface SliderProps {
  value: number
  onChange: (value: number) => void
  min?: number
  max?: number
  step?: number
  className?: string
  ariaLabel?: string
}

export function Slider({ value, onChange, min = 0, max = 100, step = 1, className, ariaLabel = '数值' }: SliderProps) {
  const pct = Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100))
  const sliderStyle = { '--slider-progress': `${pct}%` } as CSSProperties

  return (
    <div className={cn('relative flex items-center', className)}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-label={ariaLabel}
        onChange={e => onChange(Number(e.target.value))}
        className="allin-slider h-2 w-full cursor-pointer appearance-none rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        style={sliderStyle}
      />
      <span className="ml-3 min-w-[3ch] text-right font-mono text-sm font-semibold tabular-nums text-foreground">{value}</span>
    </div>
  )
}
