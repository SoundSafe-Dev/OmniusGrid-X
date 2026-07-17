import { FC, useMemo } from 'react';
import Plot from 'react-plotly.js';
import type { Config, Layout, PlotData } from 'plotly.js';
import { Card } from '../ui';

interface Spatial3DPoint {
  x: number;
  y: number;
  z: number;
  value: number;
  label?: string;
  color?: string;
}

interface Spatial3DChartProps {
  data: Spatial3DPoint[];
  height?: number;
  title?: string;
  colorScale?: string[];
  showColorbar?: boolean;
  markerSize?: number;
}

export const Spatial3DChart: FC<Spatial3DChartProps> = ({
  data,
  height = 600,
  title = '3D Spatial Visualization',
  colorScale = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444'],
  showColorbar = true,
  markerSize = 8
}) => {
  const plotData = useMemo(() => {
    const xValues = data.map(d => d.x);
    const yValues = data.map(d => d.y);
    const zValues = data.map(d => d.z);
    const textValues = data.map(d => d.label || `(${d.x}, ${d.y}, ${d.z}): ${d.value}`);
    const colorValues = data.map(d => d.color || d.value);
    
    const trace: Partial<PlotData> = {
      type: 'scatter3d',
      mode: 'markers',
      x: xValues,
      y: yValues,
      z: zValues,
      text: textValues,
      marker: {
        size: markerSize,
        color: colorValues,
        colorscale: colorScale,
        showscale: showColorbar,
        colorbar: {
          title: { text: 'Value', side: 'right' }
        },
        opacity: 0.8,
        line: {
          color: 'rgba(217, 217, 217, 0.14)',
          width: 0.5
        }
      },
      // Same flags as the previous 'text+x+y+z'; plotly treats the combination as
      // order-insensitive and the typed union only lists this permutation.
      hoverinfo: 'x+y+z+text',
      hovertemplate: '<b>%{text}</b><br>' +
                    'X: %{x}<br>' +
                    'Y: %{y}<br>' +
                    'Z: %{z}<br>' +
                    'Value: %{marker.color}<extra></extra>'
    };

    return [trace];
  }, [data, colorScale, showColorbar, markerSize]);

  const layout: Partial<Layout> = {
    title: {
      text: title,
      font: { size: 18, color: '#94a3b8' }
    },
    scene: {
      xaxis: {
        title: { text: 'X' },
        color: '#94a3b8',
        gridcolor: '#334155',
        backgroundcolor: '#1e293b'
      },
      yaxis: {
        title: { text: 'Y' },
        color: '#94a3b8',
        gridcolor: '#334155',
        backgroundcolor: '#1e293b'
      },
      zaxis: {
        title: { text: 'Z' },
        color: '#94a3b8',
        gridcolor: '#334155',
        backgroundcolor: '#1e293b'
      },
      camera: {
        eye: { x: 1.5, y: 1.5, z: 1.5 }
      }
    },
    plot_bgcolor: '#1e293b',
    paper_bgcolor: '#0f172a',
    font: { color: '#94a3b8' },
    margin: { l: 0, r: 100, t: 60, b: 0 }
  };

  const config: Partial<Config> = {
    responsive: true,
    displayModeBar: true,
    modeBarButtonsToRemove: ['lasso2d', 'select2d'],
    displaylogo: false
  };
  
  return (
    <Card title={title} className="w-full">
      <Plot
        data={plotData}
        layout={layout}
        config={config}
        style={{ width: '100%', height: `${height}px` }}
        useResizeHandler={true}
      />
    </Card>
  );
};

export default Spatial3DChart;
