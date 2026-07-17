import { FC, useMemo } from 'react';
import Plot from 'react-plotly.js';
import type { Config, Layout, PlotData } from 'plotly.js';
import { Card } from '../ui';

interface HeatmapDataPoint {
  x: number;
  y: number;
  value: number;
  label?: string;
}

interface FacilityHeatmapProps {
  data: HeatmapDataPoint[];
  height?: number;
  title?: string;
  colorScale?: string[];
  showColorbar?: boolean;
}

export const FacilityHeatmap: FC<FacilityHeatmapProps> = ({
  data,
  height = 600,
  title = 'Facility Heatmap',
  colorScale = ['#00ff00', '#ffff00', '#ff0000'],
  showColorbar = true
}) => {
  const plotData = useMemo(() => {
    // Extract x, y, z values for heatmap
    const xValues = [...new Set(data.map(d => d.x))].sort((a, b) => a - b);
    const yValues = [...new Set(data.map(d => d.y))].sort((a, b) => a - b);
    
    // Create z matrix
    const zMatrix = yValues.map(y => 
      xValues.map(x => {
        const point = data.find(d => d.x === x && d.y === y);
        return point ? point.value : 0;
      })
    );
    
    // Create text matrix for hover labels
    const textMatrix = yValues.map(y =>
      xValues.map(x => {
        const point = data.find(d => d.x === x && d.y === y);
        return point?.label || `${x},${y}: ${point?.value || 0}`;
      })
    );
    
    const trace: Partial<PlotData> = {
      type: 'heatmap',
      x: xValues,
      y: yValues,
      z: zMatrix,
      // Plotly heatmaps accept a 2D text matrix at runtime, but @types/plotly.js
      // only declares string | string[] for PlotData.text.
      text: textMatrix as unknown as string[],
      texttemplate: '%{text}',
      colorscale: colorScale,
      showscale: showColorbar,
      // 'text+z' is a valid runtime flag combination (order-insensitive), but the
      // typed hoverinfo union only enumerates axis-first permutations.
      hoverinfo: 'text+z' as unknown as PlotData['hoverinfo'],
      colorbar: {
        title: { text: 'Value', side: 'right' }
      }
    };

    return [trace];
  }, [data, colorScale, showColorbar]);

  const layout: Partial<Layout> = {
    title: {
      text: title,
      font: { size: 18, color: '#94a3b8' }
    },
    xaxis: {
      title: { text: 'X Position' },
      color: '#94a3b8',
      gridcolor: '#334155'
    },
    yaxis: {
      title: { text: 'Y Position' },
      color: '#94a3b8',
      gridcolor: '#334155'
    },
    plot_bgcolor: '#1e293b',
    paper_bgcolor: '#0f172a',
    font: { color: '#94a3b8' },
    margin: { l: 60, r: 100, t: 60, b: 60 }
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

export default FacilityHeatmap;
