import { useMemo } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import type { ActivityData } from '@/hooks/useDashboard'

interface TrendChartProps {
  data: ActivityData[]
}

export function TrendChart({ data }: TrendChartProps) {
  const chartData = useMemo(() => {
    const dayMap: Record<string, { day: string; send: number; reply: number }> = {}

    // Generate last 7 days
    for (let i = 6; i >= 0; i--) {
      const d = new Date()
      d.setDate(d.getDate() - i)
      const key = d.toISOString().split('T')[0]
      dayMap[key] = { day: key.slice(5), send: 0, reply: 0 }
    }

    // Fill in actual data
    data.forEach(item => {
      const key = item.day
      if (!dayMap[key]) dayMap[key] = { day: key.slice(5), send: 0, reply: 0 }
      if (item.action === 'sent') dayMap[key].send += item.cnt
      else if (item.action === 'replied' || item.action === 'auto_replied') dayMap[key].reply += item.cnt
    })

    return Object.values(dayMap).sort((a, b) => a.day.localeCompare(b.day))
  }, [data])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-black text-foreground">7 日趋势</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[200px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="day" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip
                cursor={{ stroke: 'hsl(var(--border))', strokeDasharray: '3 3' }}
                contentStyle={{
                  background: 'hsl(var(--popover))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '8px',
                  boxShadow: '0 12px 32px rgba(24, 33, 29, 0.10)',
                }}
                labelStyle={{ color: 'hsl(var(--foreground))', fontWeight: 600 }}
                itemStyle={{ color: 'hsl(var(--muted-foreground))', fontSize: '12px' }}
              />
              <Legend wrapperStyle={{ fontSize: '12px', color: 'hsl(var(--muted-foreground))' }} />
              <Line type="monotone" dataKey="send" name="发送" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
              <Line type="monotone" dataKey="reply" name="回复" stroke="hsl(var(--status-success-foreground))" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
