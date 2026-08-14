import React, { useState, useEffect, useRef, useImperativeHandle } from 'react';
import { analysisSessionsApi, DataSource } from '../../api/analysisSessions';
import { Upload, FileText, Trash2, Loader2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { PlatformDataSourcePicker } from './PlatformDataSourcePicker';

const STRUCTURED_DATA_EXTENSIONS = new Set([
  'zip', 'csv', 'tsv', 'tab', 'xlsx', 'xls', 'xlsm', 'xlsb', 'ods', 'numbers',
  'parquet', 'pq', 'arrow', 'feather', 'json', 'jsonl', 'ndjson', 'xml',
]);

const UPLOAD_FILE_ACCEPT = [
  '.zip', 'application/zip', '.csv', '.tsv', '.tab', '.xlsx', '.xls', '.xlsm',
  '.xlsb', '.ods', '.numbers', '.parquet', '.pq', '.arrow', '.feather', '.json',
  '.jsonl', '.ndjson', '.xml', '.pdf', '.docx', '.doc', '.rtf', '.odt', '.html',
  '.htm', '.eml', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff',
  '.tif', '.txt', '.md', '.yaml', '.yml',
].join(',');

interface DataSourcesPanelProps {
  sessionId: string;
  onDataSourceAdded?: () => void;
  onSessionMissing?: () => Promise<string | null>;
  className?: string;
}

export type DataSourcesPanelHandle = {
  openFilePicker: () => void;
};

export const DataSourcesPanel = React.forwardRef<DataSourcesPanelHandle, DataSourcesPanelProps>(
  function DataSourcesPanel(
    {
      sessionId,
      onDataSourceAdded,
      onSessionMissing,
      className = '',
    },
    ref
  ) {
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isCorrelating, setIsCorrelating] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  // Distinct from `uploadError`, which is about a file the user just added. This one is
  // about the LIST: a failed load left it empty and the panel said "No data sources added
  // yet", telling the user they had added nothing.
  const [loadError, setLoadError] = useState<string | null>(null);
  // A removal that did not happen (FS-481). Separate from `uploadError` because the two
  // point opposite ways: one is a file that never arrived, this is one that never left.
  const [removeError, setRemoveError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useImperativeHandle(ref, () => ({
    openFilePicker: () => fileInputRef.current?.click(),
  }));

  useEffect(() => {
    if (sessionId) {
      loadDataSources();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing; adding deps changes retrigger behavior (FS-54)
  }, [sessionId]);

  const isSessionNotFound = (error: any) =>
    error?.response?.status === 404 &&
    String(error?.response?.data?.detail || '').toLowerCase().includes('session not found');

  const loadDataSources = async (targetSessionId = sessionId) => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const sources = await analysisSessionsApi.listSessionData(targetSessionId);
      setDataSources(sources);
    } catch (error) {
      console.error('Error loading data sources:', error);
      setLoadError(
        isSessionNotFound(error)
          ? 'This session no longer exists.'
          : 'Could not load data sources.',
      );
    } finally {
      setIsLoading(false);
    }
  };

  const inferDataType = (fileName: string) => {
    const ext = fileName.split('.').pop()?.toLowerCase();
    if (ext && STRUCTURED_DATA_EXTENSIONS.has(ext)) {
      return 'spreadsheet';
    }
    if (['pdf', 'docx', 'doc', 'rtf', 'odt', 'html', 'htm', 'eml'].includes(ext || '')) {
      return 'report';
    }
    if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff', 'tif'].includes(ext || '')) {
      return 'image';
    }
    return 'document';
  };

  const uploadFiles = async (files: File[]) => {
    if (!files.length || !sessionId || isUploading) return;

    setIsUploading(true);
    setUploadError(null);
    setUploadStatus(`Uploading ${files.length} file${files.length === 1 ? '' : 's'}...`);

    try {
      let activeSessionId = sessionId;

      for (const file of files) {
        const dataType = inferDataType(file.name);
        setUploadStatus(`Uploading ${file.name}...`);
        try {
          await analysisSessionsApi.uploadDataToSession(activeSessionId, file, dataType);
        } catch (error: any) {
          if (isSessionNotFound(error) && onSessionMissing) {
            setUploadStatus('Session expired. Creating a fresh session and retrying upload...');
            const replacementSessionId = await onSessionMissing();
            if (replacementSessionId) {
              activeSessionId = replacementSessionId;
              await analysisSessionsApi.uploadDataToSession(activeSessionId, file, dataType);
              continue;
            }
          }

          throw error;
        }
      }

      setUploadStatus(`Added ${files.length} data source${files.length === 1 ? '' : 's'} to this session.`);
      await loadDataSources(activeSessionId);
      onDataSourceAdded?.();
    } catch (error: any) {
      console.error('Error uploading file:', error);
      const detail =
        error?.response?.data?.detail ||
        error?.message ||
        'Upload failed. Check SSH tunnel, backend health, and file format.';
      setUploadError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    uploadFiles(files);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    uploadFiles(Array.from(e.dataTransfer.files || []));
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleCorrelate = async () => {
    if (!sessionId || dataSources.length < 2 || isCorrelating) return;
    setIsCorrelating(true);
    setUploadError(null);
    setUploadStatus('Correlating files across shared assets and date ranges...');
    try {
      const result = await analysisSessionsApi.correlateSession(sessionId);
      const multi = result.multi_spreadsheet_analysis;
      const shared = multi?.shared_assets ? Object.keys(multi.shared_assets).length : 0;
      setUploadStatus(
        shared > 0
          ? `Linked ${dataSources.length} files. ${shared} shared asset(s) found. Ask: "What trends do you see across all files?"`
          : result.analysis || 'Correlation complete. Re-upload files if assets use different ID formats.'
      );
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || 'Correlation failed';
      setUploadError(String(detail));
      setUploadStatus(null);
    } finally {
      setIsCorrelating(false);
    }
  };

  const handleRemove = async (sourceId: string) => {
    try {
      await analysisSessionsApi.removeDataSource(sessionId, sourceId);
      setDataSources(dataSources.filter(ds => ds.id !== sourceId));
      setRemoveError(null);
    } catch (error) {
      console.error('Error removing data source:', error);
      // FS-481. The row stays exactly where it was, which is also what a click that never
      // registered looks like — so the reasonable second reading is that it worked and the
      // list is stale. It did not: the file is still attached, and still feeding answers.
      setRemoveError('That file could not be removed — it is still attached to this session.');
    }
  };

  const getDataTypeIcon = (dataType: string | null) => {
    switch (dataType) {
      case 'spreadsheet':
        return <FileText className="w-4 h-4 text-green-600" />;
      case 'report':
        return <FileText className="w-4 h-4 text-blue-600" />;
      case 'image':
        return <FileText className="w-4 h-4 text-purple-600" />;
      default:
        return <FileText className="w-4 h-4 text-gray-600" />;
    }
  };

  return (
    <div className={`flex flex-col h-full ${className}`}>
      <div className="p-4 border-b border-opsgrid-border shrink-0">
        <h3 className="text-sm font-semibold text-opsgrid-text mb-1">Upload data for AI</h3>
        <p className="text-xs text-opsgrid-text-secondary mb-3">
          Drop spreadsheets, supporting files, or a <strong>ZIP batch</strong> here, or use <strong>Upload files</strong> in the chat header.
        </p>
        
        <div className="space-y-3">
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            className={`border-2 border-dashed rounded-lg p-4 text-center transition-colors ${
              isDragging
                ? 'border-blue-500 bg-blue-50'
                : 'border-opsgrid-border bg-opsgrid-bg'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileSelect}
              className="hidden"
              id={`file-upload-${sessionId}`}
              accept={UPLOAD_FILE_ACCEPT}
              multiple
              disabled={isUploading}
            />
            <Upload className="w-6 h-6 mx-auto mb-2 text-opsgrid-text-secondary" />
            <p className="text-sm font-medium text-opsgrid-text">
              Drop files or a ZIP batch here
            </p>
            <p className="text-xs text-opsgrid-text-secondary mt-1">
              ZIP, Excel, CSV, JSON, Parquet, reports, images, and notes are supported.
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3 w-full bg-white text-gray-900 border-gray-300 hover:bg-gray-100"
              disabled={isUploading}
              onClick={() => fileInputRef.current?.click()}
            >
              {isUploading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Uploading...
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4 mr-2" />
                  Select files or ZIP
                </>
              )}
            </Button>
          </div>

          {dataSources.length >= 2 && (
            <Button
              variant="outline"
              size="sm"
              className="w-full bg-white text-gray-900 border-gray-300 hover:bg-gray-100"
              disabled={isCorrelating || isUploading}
              onClick={handleCorrelate}
            >
              {isCorrelating ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Correlating...
                </>
              ) : (
                <>Correlate {dataSources.length} files</>
              )}
            </Button>
          )}

          {uploadStatus && (
            <p className="text-xs text-opsgrid-text-secondary">
              {uploadStatus}
            </p>
          )}

          {uploadError && (
            <p className="text-xs text-red-600">
              {uploadError}
            </p>
          )}

          {removeError && (
            <p role="alert" className="text-xs text-red-600">
              {removeError}
            </p>
          )}

          {isUploading && (
            <Button
              disabled
              className="w-full"
              size="sm"
            >
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Processing data sources
            </Button>
          )}
        </div>
      </div>

      {/* Attach live platform data (sensor/asset telemetry, yard, transportation)
          as correlation sources — flows through the existing correlate engine. */}
      <PlatformDataSourcePicker
        sessionId={sessionId}
        onAttached={() => { loadDataSources(); onDataSourceAdded?.(); }}
      />

      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="text-center text-opsgrid-text-secondary text-sm py-4">
            Loading data sources...
          </div>
        ) : loadError ? (
          <div className="text-center text-status-alarm text-sm py-4">{loadError}</div>
        ) : dataSources.length === 0 ? (
          <div className="text-center text-opsgrid-text-secondary text-sm py-4">
            No data sources added yet
          </div>
        ) : (
          <div className="space-y-2">
            {dataSources.map((source) => (
              <div
                key={source.id}
                className="p-3 bg-opsgrid-bg rounded border border-opsgrid-border"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-start gap-2 flex-1 min-w-0">
                    {getDataTypeIcon(source.data_type)}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-opsgrid-text truncate">
                        {source.file_name || 'Unnamed Data Source'}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <Badge
                          variant="info"
                          className="text-xs bg-white text-gray-900 border border-gray-300"
                        >
                          {source.source_type}
                        </Badge>
                        {source.data_type && (
                          <Badge
                            variant="neutral"
                            className="text-xs bg-white text-gray-900 border border-gray-300"
                          >
                            {source.data_type}
                          </Badge>
                        )}
                      </div>
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleRemove(source.id)}
                    className="px-2 ml-2 flex-shrink-0 bg-white text-gray-900 border-gray-300 hover:bg-gray-100"
                  >
                    <Trash2 className="w-3 h-3" />
                  </Button>
                </div>
                <p className="text-xs text-opsgrid-text-secondary">
                  Added {new Date(source.added_at).toLocaleString()}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
  }
);

DataSourcesPanel.displayName = 'DataSourcesPanel';
