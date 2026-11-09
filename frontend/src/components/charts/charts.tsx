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

/**
 * Categorical slots 1-3 of the dataviz reference palette (blue, orange, aqua), validated as a set
 * on the white card surface with scripts/validate_palette.js (--pairs all: CVD ΔE 9.2, normal 24.0).
 * Aqua is below 3:1 contrast on white, so every chart using it ships a legend AND a table view.
 * Colour follows the series (fixed order), never its rank.
 */
const CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a"] as const;

export interface SeriesSpec {
  key: string;
  label: string;
}

function Legend({ series }: { series: SeriesSpec[] }) {
  return (
    <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-hidden="true">
      {series.map((s, i) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm" style={{ backgroundColor: CATEGORICAL[i] }} />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

/**
 * Up to 3 series per category, grouped side by side (e.g. p50 vs p95) or stacked (parts of a
 * whole). Legend above, hover tooltip with every series, 2px gaps, rounded data ends.
 */
export function MultiBarChart({
  data,
  xKey,
  series,
  ariaLabel,
  stacked = false,
  format = (v: number) => String(Math.round(v)),
  height = 256,
}: {
  data: Record<string, string | number>[];
  xKey: string;
  series: SeriesSpec[];
  ariaLabel: string;
  stacked?: boolean;
  format?: (v: number) => string;
  height?: number;
}) {
  const shown = series.slice(0, CATEGORICAL.length);
  return (
    <div className="w-full">
      {shown.length > 1 && <Legend series={shown} />}
      <div className="w-full" style={{ height }} role="img" aria-label={ariaLabel}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }} barGap={2} barCategoryGap="22%">
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis
              dataKey={xKey}
              tick={tick}
              tickLine={false}
              axisLine={{ stroke: GRID }}
              interval={0}
              tickFormatter={(v: string) => (v.length > 16 ? `${v.slice(0, 15)}…` : v)}
            />
            <YAxis tick={tick} tickLine={false} axisLine={false} tickFormatter={(v: number) => format(v)} width={64} />
            <Tooltip
              cursor={{ fill: "#f1f5f9" }}
              content={({ active, payload }) => {
                const p = active && payload?.[0] ? payload[0].payload : null;
                return p ? (
                  <TooltipBox title={String(p[xKey])}>
                    {shown.map((s, i) => (
                      <p key={s.key} className="flex items-center gap-1.5">
                        <span className="inline-block size-2 rounded-sm" style={{ backgroundColor: CATEGORICAL[i] }} />
                        {s.label}: <span className="text-foreground tabular-nums">{format(Number(p[s.key] ?? 0))}</span>
                      </p>
                    ))}
                  </TooltipBox>
                ) : null;
              }}
            />
            {shown.map((s, i) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.label}
                fill={CATEGORICAL[i]}
                stackId={stacked ? "stack" : undefined}
                stroke={stacked ? "#ffffff" : undefined}
                strokeWidth={stacked ? 1 : 0}
                radius={!stacked || i === shown.length - 1 ? [4, 4, 0, 0] : 0}
                maxBarSize={40}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
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
