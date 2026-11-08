/**
 * Single-series Recharts charts in the app style (dataviz rules: one series = one colour and no
 * legend; 2px line, 8px markers, 4px rounded bar ends, recessive grid, hover tooltip).
 * SERIES is indigo-600, validated against the card surface with the dataviz palette script.
 */
import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const SERIES = "#4f39f6"; // indigo-600
const GRID = "#e2e8f0"; // slate-200
const AXIS = "#62748e"; // slate-500
const tick = { fill: AXIS, fontSize: 12 };

function TooltipBox({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-lg border bg-card px-3 py-2 text-xs shadow-md">
      <p className="font-medium text-foreground">{title}</p>
      <div className="text-muted-foreground">{children}</div>
    </div>
  );
}

export interface TrendPoint {
  label: string;
  value: number;
  detail: string;
}

/** Percent over time (y fixed to 0-100). */
export function PercentLineChart({ data, ariaLabel }: { data: TrendPoint[]; ariaLabel: string }) {
  return (
    <div className="h-64 w-full" role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="label" tick={tick} tickLine={false} axisLine={{ stroke: GRID }} minTickGap={16} />
          <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={tick} tickLine={false} axisLine={false} unit="%" />
          <Tooltip
            cursor={{ stroke: AXIS, strokeDasharray: "3 3" }}
            content={({ active, payload }) => {
              const p = active && payload?.[0] ? (payload[0].payload as TrendPoint) : null;
              return p ? (
                <TooltipBox title={`${Math.round(p.value)}%`}>
                  <p>{p.detail}</p>
                </TooltipBox>
              ) : null;
            }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={SERIES}
            strokeWidth={2}
            dot={{ r: 4, fill: SERIES, stroke: "#fff", strokeWidth: 2 }}
            activeDot={{ r: 6, stroke: "#fff", strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Vertical bars for a count or percent per category. */
export function SimpleBarChart({
  data,
  xKey,
  yKey,
  ariaLabel,
  unit,
  maxY,
}: {
  data: Record<string, string | number>[];
  xKey: string;
  yKey: string;
  ariaLabel: string;
  unit?: string;
  maxY?: number;
}) {
  return (
    <div className="h-56 w-full" role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }} barCategoryGap="25%">
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey={xKey} tick={tick} tickLine={false} axisLine={{ stroke: GRID }} interval={0} tickFormatter={(v: string) => (v.length > 14 ? `${v.slice(0, 13)}…` : v)} />
          <YAxis domain={[0, maxY ?? "auto"]} allowDecimals={false} tick={tick} tickLine={false} axisLine={false} unit={unit} />
          <Tooltip
            cursor={{ fill: "#f1f5f9" }}
            content={({ active, payload }) => {
              const p = active && payload?.[0] ? payload[0].payload : null;
              return p ? (
                <TooltipBox title={String(p[xKey])}>
                  <p>
                    {typeof p[yKey] === "number" ? Math.round(p[yKey] as number) : p[yKey]}
                    {unit ?? ""}
                  </p>
                </TooltipBox>
              ) : null;
            }}
          />
          <Bar dataKey={yKey} fill={SERIES} radius={[4, 4, 0, 0]} maxBarSize={48} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
