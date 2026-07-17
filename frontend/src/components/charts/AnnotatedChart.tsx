import { FC, useState, useCallback, useMemo } from 'react';
import Plot from 'react-plotly.js';
import type { Config, ModeBarDefaultButtons } from 'plotly.js';
import { Card } from '../ui';
import { Button } from '../ui';

interface Annotation {
  x: number | string;
  y: number;
  text: string;
  arrowhead?: number;
  ax?: number;
  ay?: number;
  bgcolor?: string;
  bordercolor?: string;
}

interface AnnotatedChartProps {
  data: any[];
  layout?: any;
  title?: string;
  annotations?: Annotation[];
  onAnnotationAdd?: (annotation: Annotation) => void;
  editable?: boolean;
}

export const AnnotatedChart: FC<AnnotatedChartProps> = ({
  data,
  layout,
  title = 'Annotated Chart',
  annotations = [],
  onAnnotationAdd,
  editable = false
}) => {
  const [localAnnotations, setLocalAnnotations] = useState<Annotation[]>(annotations);
  const [isAddingAnnotation, setIsAddingAnnotation] = useState(false);
  const [newAnnotationText, setNewAnnotationText] = useState('');
  
  const plotLayout = useMemo(() => ({
    ...layout,
    title: {
      text: title,
      font: { size: 18, color: '#94a3b8' }
    },
    annotations: localAnnotations.map(ann => ({
      ...ann,
      font: { color: '#94a3b8' },
      arrowcolor: '#94a3b8'
    })),
    plot_bgcolor: '#1e293b',
    paper_bgcolor: '#0f172a',
    font: { color: '#94a3b8' },
    margin: { l: 60, r: 60, t: 60, b: 60 }
  }), [layout, title, localAnnotations]);
  
  const handleAddAnnotation = useCallback(() => {
    if (newAnnotationText.trim()) {
      const newAnnotation: Annotation = {
        x: 0.5, // Default to center
        y: 0.5,
        text: newAnnotationText,
        arrowhead: 2,
        ax: 0,
        ay: -40,
        bgcolor: 'rgba(0,0,0,0.7)',
        bordercolor: '#94a3b8'
      };
      
      const updatedAnnotations = [...localAnnotations, newAnnotation];
      setLocalAnnotations(updatedAnnotations);
      onAnnotationAdd?.(newAnnotation);
      setNewAnnotationText('');
      setIsAddingAnnotation(false);
    }
  }, [newAnnotationText, localAnnotations, onAnnotationAdd]);
  
  const handleRemoveAnnotation = useCallback((index: number) => {
    const updatedAnnotations = localAnnotations.filter((_, i) => i !== index);
    setLocalAnnotations(updatedAnnotations);
  }, [localAnnotations]);
  
  // Download the visible traces as CSV: one row per point index, one x/y
  // column pair per trace (traces may have different lengths).
  const handleExport = useCallback(() => {
    const traces = data.filter((t) => Array.isArray(t?.x) && Array.isArray(t?.y));
    if (traces.length === 0) return;

    const escape = (v: unknown) => {
      if (v === null || v === undefined) return '';
      const s = String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };

    const header = traces.flatMap((t, i) => {
      const name = t.name || `trace_${i + 1}`;
      return [`${name}_x`, `${name}_y`];
    });
    const rowCount = Math.max(...traces.map((t) => t.x.length));
    const rows = Array.from({ length: rowCount }, (_, r) =>
      traces.flatMap((t) => [escape(t.x[r]), escape(t.y[r])]).join(',')
    );
    const csv = [header.map(escape).join(','), ...rows].join('\n');

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${title.toLowerCase().replace(/[^a-z0-9]+/g, '_')}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [data, title]);
  
  // These shape-drawing buttons exist in plotly.js at runtime but are missing
  // from the ModeBarDefaultButtons union in @types/plotly.js.
  const drawButtons: string[] = ['drawline', 'drawopenpath', 'drawclosedpath', 'drawcircle', 'drawrect', 'eraseshape'];

  const config: Partial<Config> = {
    responsive: true,
    displayModeBar: true,
    modeBarButtonsToAdd: drawButtons as ModeBarDefaultButtons[],
    displaylogo: false,
    editable: editable
  };
  
  return (
    <Card title={title} className="w-full">
      <div className="mb-4 flex gap-2 items-center">
        {editable && (
          <>
            {isAddingAnnotation ? (
              <>
                <input
                  type="text"
                  value={newAnnotationText}
                  onChange={(e) => setNewAnnotationText(e.target.value)}
                  placeholder="Enter annotation text..."
                  className="px-3 py-1.5 bg-opsgrid-bg border border-opsgrid-border rounded-lg text-opsgrid-text flex-1"
                />
                <Button onClick={handleAddAnnotation}>Add</Button>
                <Button onClick={() => setIsAddingAnnotation(false)} variant="outline">Cancel</Button>
              </>
            ) : (
              <Button onClick={() => setIsAddingAnnotation(true)}>Add Annotation</Button>
            )}
          </>
        )}
        <Button onClick={handleExport} variant="outline">Export CSV</Button>
      </div>
      
      {localAnnotations.length > 0 && (
        <div className="mb-4">
          <h4 className="text-sm font-medium text-opsgrid-text mb-2">Annotations</h4>
          <div className="flex flex-wrap gap-2">
            {localAnnotations.map((ann, index) => (
              <div
                key={index}
                className="px-3 py-1.5 bg-opsgrid-bg border border-opsgrid-border rounded-lg flex items-center gap-2"
              >
                <span className="text-xs text-opsgrid-text">{ann.text}</span>
                {editable && (
                  <button
                    onClick={() => handleRemoveAnnotation(index)}
                    className="text-opsgrid-text-secondary hover:text-red-500"
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      
      <Plot
        data={data}
        layout={plotLayout}
        config={config}
        style={{ width: '100%', height: '500px' }}
        useResizeHandler={true}
      />
    </Card>
  );
};

export default AnnotatedChart;
