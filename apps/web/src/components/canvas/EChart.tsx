import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import type { ECharts, EChartsOption } from 'echarts';

/** 轻量 ECharts React 封装：init/dispose 生命周期 + 容器尺寸变化自动 resize */
export default function EChart({ option, height = 300 }: { option: EChartsOption; height?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ECharts | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = echarts.init(el);
    chartRef.current = chart;

    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
    const ro = new ResizeObserver(onResize);
    ro.observe(el);

    return () => {
      window.removeEventListener('resize', onResize);
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

  return <div ref={containerRef} style={{ height, width: '100%' }} />;
}
