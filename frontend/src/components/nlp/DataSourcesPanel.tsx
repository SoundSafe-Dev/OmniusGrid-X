import React, { useState, useEffect } from 'react';
import { analysisSessionsApi, DataSource } from '../../api/analysisSessions';
import { Upload, FileText, Trash2, X } from 'lucide-react';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';

interface DataSourcesPanelProps {
  sessionId: string;
  onDataSourceAdded?: () => void;
  className?: string;
}

export const DataSourcesPanel: React.FC<DataSourcesPanelProps> = ({
  sessionId,
  onDataSourceAdded,
  className = ''
}) => {
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  useEffect(() => {
    if (sessionId) {
      loadDataSources();
    }
  }, [sessionId, onDataSourceAdded]);

  const loadDataSources = async () => {
    setIsLoading(true);
    try {
      const sources = await analysisSessionsApi.listSessionData(sessionId);
      setDataSources(sources);
    } catch (error) {
      console.error('Error loading data sources:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile || !sessionId) return;

    setIsUploading(true);
    try {
      // Determine data type from file extension
      const ext = selectedFile.name.split('.').pop()?.toLowerCase();
      let dataType = 'document';
      if (ext === 'csv' || ext === 'xlsx' || ext === 'xls') {
        dataType = 'spreadsheet';
      } else if (ext === 'pdf' || ext === 'docx' || ext === 'doc') {
        dataType = 'report';
      } else if (ext === 'png' || ext === 'jpg' || ext === 'jpeg') {
        dataType = 'image';
      }

      await analysisSessionsApi.uploadDataToSession(sessionId, selectedFile, dataType);
      setSelectedFile(null);
      loadDataSources();
      onDataSourceAdded?.();
    } catch (error) {
      console.error('Error uploading file:', error);
    } finally {
      setIsUploading(false);
    }
  };

  const handleRemove = async (sourceId: string) => {
    try {
      await analysisSessionsApi.removeDataSource(sessionId, sourceId);
      setDataSources(dataSources.filter(ds => ds.id !== sourceId));
    } catch (error) {
      console.error('Error removing data source:', error);
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
      <div className="p-4 border-b border-opsgrid-border">
        <h3 className="text-sm font-semibold text-opsgrid-text mb-3">Data Sources</h3>
        
        {/* Upload Section */}
        <div className="space-y-2">
          {selectedFile ? (
            <div className="flex items-center justify-between p-2 bg-opsgrid-bg rounded border border-opsgrid-border">
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <FileText className="w-4 h-4 text-opsgrid-text-secondary flex-shrink-0" />
                <span className="text-xs text-opsgrid-text truncate">{selectedFile.name}</span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setSelectedFile(null)}
                className="px-2"
              >
                <X className="w-3 h-3" />
              </Button>
            </div>
          ) : (
            <div className="border-2 border-dashed border-opsgrid-border rounded-lg p-3 text-center">
              <input
                type="file"
                onChange={handleFileSelect}
                className="hidden"
                id="file-upload"
                accept=".csv,.xlsx,.xls,.pdf,.docx,.doc,.png,.jpg,.jpeg,.txt,.md"
              />
              <label htmlFor="file-upload">
                <Button variant="outline" size="sm" className="w-full">
                  <Upload className="w-4 h-4 mr-2" />
                  Upload File
                </Button>
              </label>
            </div>
          )}
          
          {selectedFile && (
            <Button
              onClick={handleUpload}
              disabled={isUploading}
              className="w-full"
              size="sm"
            >
              {isUploading ? 'Uploading...' : 'Add to Session'}
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="text-center text-opsgrid-text-secondary text-sm py-4">
            Loading data sources...
          </div>
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
                        <Badge variant="info" className="text-xs">
                          {source.source_type}
                        </Badge>
                        {source.data_type && (
                          <Badge variant="neutral" className="text-xs">
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
                    className="px-2 ml-2 flex-shrink-0"
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
};
