import { FC, useMemo } from 'react';
import Plot from 'react-plotly.js';
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
    
    return [{
      type: 'heatmap' as const,
      x: xValues,
      y: yValues,
      z: zMatrix,
      text: textMatrix,
      texttemplate: '%{text}',
      colorscale: colorScale,
      showscale: showColorbar,
      hoverinfo: 'text+z',
      colorbar: {
        title: 'Value',
        titleside: 'right'
      }
    }];
  }, [data, colorScale, showColorbar]);
  
  const layout = {
    title: {
      text: title,
      font: { size: 18, color: '#94a3b8' }
    },
    xaxis: {
      title: 'X Position',
      color: '#94a3b8',
      gridcolor: '#334155'
    },
    yaxis: {
      title: 'Y Position',
      color: '#94a3b8',
      gridcolor: '#334155'
    },
    plot_bgcolor: '#1e293b',
    paper_bgcolor: '#0f172a',
    font: { color: '#94a3b8' },
    margin: { l: 60, r: 100, t: 60, b: 60 }
  };
  
  const config = {
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
