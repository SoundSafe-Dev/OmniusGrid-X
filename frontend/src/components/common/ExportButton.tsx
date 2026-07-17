import { FC, useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { api } from '../../api/client';

type ExportFormat = 'csv' | 'xlsx' | 'pdf';

interface ExportButtonProps {
  /** API path relative to the configured base URL, e.g. "/api/v1/exports/kanban/tasks". */
  endpoint: string;
  /** Query params (columns, date range, status, ...). */
  params?: Record<string, string | number | boolean | undefined | null>;
  /** Fallback filename if the server omits a Content-Disposition header. */
  filename?: string;
  /** Button label (default "Export"). */
  label?: string;
  /** Format hint, used for the default filename extension and the tooltip. */
  format?: ExportFormat;
  className?: string;
  disabled?: boolean;
  /** Called with a human-readable message when an export fails. */
  onError?: (message: string) => void;
}

const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function filenameFromDisposition(header: string | undefined, fallback: string): string {
  if (!header) return fallback;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  return match ? decodeURIComponent(match[1]) : fallback;
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function blobToJson(blob: Blob): Promise<any> {
  return JSON.parse(await blob.text());
}

/**
 * Reusable download button for the Task 5 export endpoints. Requests the file as a
 * blob through the shared axios client (so auth + refresh apply), reads the
 * filename from Content-Disposition, and saves it. Large telemetry exports come
 * back as a 202 + job id; the button then polls the job and downloads on completion.
 */
export const ExportButton: FC<ExportButtonProps> = ({
  endpoint,
  params,
  filename,
  label = 'Export',
  format,
  className,
  disabled,
  onError,
}) => {
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);

  const fallbackName = filename || `export.${format ?? 'csv'}`;

  const pollAndDownload = async (jobId: string, fallback: string) => {
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    while (Date.now() < deadline) {
      const { data } = await api.get(`/api/v1/exports/jobs/${jobId}`);
      if (data.total) {
        setProgress(Math.min(100, Math.round((data.processed / data.total) * 100)));
      }
      if (data.status === 'completed') {
        const file = await api.get(`/api/v1/exports/jobs/${jobId}/download`, {
          responseType: 'blob',
        });
        const name = filenameFromDisposition(
          file.headers['content-disposition'],
          data.filename || fallback,
        );
        triggerDownload(file.data as Blob, name);
        return;
      }
      if (data.status === 'failed') {
        throw new Error(data.errors?.[0]?.error || 'Export job failed');
      }
      await sleep(POLL_INTERVAL_MS);
    }
    throw new Error('Export timed out');
  };

  const handleClick = async () => {
    setLoading(true);
    setProgress(null);
    try {
      const res = await api.get(endpoint, { params, responseType: 'blob' });

      // Large telemetry pulls return 202 + a job descriptor (as a blob body).
      if (res.status === 202) {
        const job = await blobToJson(res.data as Blob);
        await pollAndDownload(job.job_id, fallbackName);
        return;
      }

      const name = filenameFromDisposition(res.headers['content-disposition'], fallbackName);
      triggerDownload(res.data as Blob, name);
    } catch (err: any) {
      // With responseType 'blob', error bodies arrive as a Blob too.
      let message = 'Export failed';
      const data = err?.response?.data;
      if (data instanceof Blob) {
        try {
          message = (await blobToJson(data))?.detail ?? message;
        } catch {
          /* keep default message */
        }
      } else if (typeof err?.message === 'string') {
        message = err.message;
      }
      if (onError) onError(message);
      else console.error('Export failed:', message);
    } finally {
      setLoading(false);
      setProgress(null);
    }
  };

  const text = loading
    ? progress !== null
      ? `Exporting… ${progress}%`
      : 'Exporting…'
    : label;

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled || loading}
      title={format ? `Export ${format.toUpperCase()}` : 'Export'}
      className={
        className ??
        'inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60'
      }
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Download className="h-4 w-4" />
      )}
      <span>{text}</span>
    </button>
  );
};

export default ExportButton;
