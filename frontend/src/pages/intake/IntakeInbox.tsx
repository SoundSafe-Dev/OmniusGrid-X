import React, { useState, useEffect } from 'react';
import { Card } from '../../components/ui/Card';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Badge } from '../../components/ui/Badge';
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui';
import { nlpCorrelationApi, IntakeItem } from '../../api/nlpCorrelation';
import { Upload, FileText, Image, FileSpreadsheet, Loader2, CheckCircle, Search } from 'lucide-react';

export const IntakeInbox: React.FC = () => {
  const [items, setItems] = useState<IntakeItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [dataType, setDataType] = useState<'spreadsheet' | 'report' | 'image' | 'document'>('document');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  useEffect(() => {
    loadIntakeItems();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing; adding deps changes retrigger behavior (FS-54)
  }, []);

  const loadIntakeItems = async () => {
    setIsLoading(true);
    try {
      const response = await nlpCorrelationApi.listIntakeItems(50, 0, statusFilter === 'all' ? undefined : statusFilter);
      setItems(response.items);
    } catch (error) {
      console.error('Error loading intake items:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
      // Auto-detect data type from file extension
      const ext = e.target.files[0].name.split('.').pop()?.toLowerCase();
      if (ext === 'csv' || ext === 'xlsx' || ext === 'xls') {
        setDataType('spreadsheet');
      } else if (ext === 'pdf' || ext === 'docx' || ext === 'doc') {
        setDataType('report');
      } else if (ext === 'png' || ext === 'jpg' || ext === 'jpeg') {
        setDataType('image');
      }
    }
  };

  const handleUpload = async () => {
    if (!selectedFile || !title) return;

    setUploading(true);
    try {
      const response = await nlpCorrelationApi.uploadToIntake(
        selectedFile,
        title,
        description,
        dataType
      );
      setItems([response, ...items]);
      setSelectedFile(null);
      setTitle('');
      setDescription('');
    } catch (error) {
      console.error('Error uploading file:', error);
    } finally {
      setUploading(false);
    }
  };

  const handleAnalyze = async (itemId: string) => {
    setAnalyzing(itemId);
    try {
      const response = await nlpCorrelationApi.analyzeIntake(itemId);
      // Update the item with analysis results
      setItems(items.map(item =>
        item.id === itemId
          ? { ...item, analysis_result: response, analyzed_at: new Date().toISOString(), status: 'analyzed' }
          : item
      ));
    } catch (error) {
      console.error('Error analyzing item:', error);
    } finally {
      setAnalyzing(null);
    }
  };

  const getFileIcon = (dataType: string) => {
    switch (dataType) {
      case 'spreadsheet':
        return <FileSpreadsheet className="w-5 h-5 text-green-600" />;
      case 'report':
        return <FileText className="w-5 h-5 text-blue-600" />;
      case 'image':
        return <Image className="w-5 h-5 text-purple-600" />;
      default:
        return <FileText className="w-5 h-5 text-gray-600" />;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'analyzed':
        return <Badge variant="success">Analyzed</Badge>;
      case 'analyzing':
        return <Badge variant="warning">Analyzing</Badge>;
      case 'error':
        return <Badge variant="error">Error</Badge>;
      default:
        return <Badge variant="neutral">Pending</Badge>;
    }
  };

  const filteredItems = items.filter(item =>
    (item.title ?? '').toLowerCase().includes(searchQuery.toLowerCase()) ||
    (item.description ?? '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-opsgrid-text">Intake Inbox</h1>
        <p className="text-opsgrid-text-secondary mt-1">
          Upload spreadsheets, reports, and images for correlation AI analysis
        </p>
      </div>

      {/* Upload Section */}
      <Card title="Upload Data for Analysis">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-opsgrid-text mb-1">Title *</label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Enter a descriptive title"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-opsgrid-text mb-1">Data Type</label>
              <select
                value={dataType}
                onChange={(e) => setDataType(e.target.value as any)}
                className="w-full px-3 py-2 border border-opsgrid-border rounded-md bg-opsgrid-bg text-opsgrid-text"
              >
                <option value="document">Document</option>
                <option value="spreadsheet">Spreadsheet (CSV, Excel)</option>
                <option value="report">Report (PDF, Word)</option>
                <option value="image">Image (PNG, JPG)</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-opsgrid-text mb-1">Description</label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional description of the data"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-opsgrid-text mb-1">File *</label>
            <div className="border-2 border-dashed border-opsgrid-border rounded-lg p-6 text-center hover:border-opsgrid-border-emphasis transition-colors">
              {selectedFile ? (
                <div className="flex items-center justify-center gap-2">
                  {getFileIcon(dataType)}
                  <span className="text-sm text-opsgrid-text">{selectedFile.name}</span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setSelectedFile(null)}
                  >
                    Remove
                  </Button>
                </div>
              ) : (
                <div>
                  <Upload className="w-8 h-8 mx-auto text-opsgrid-text-secondary mb-2" />
                  <p className="text-sm text-opsgrid-text-secondary mb-2">
                    Drag and drop a file here, or click to select
                  </p>
                  <input
                    type="file"
                    onChange={handleFileSelect}
                    className="hidden"
                    id="file-upload"
                    accept=".csv,.xlsx,.xls,.pdf,.docx,.doc,.png,.jpg,.jpeg,.txt,.md"
                  />
                  <label htmlFor="file-upload">
                    <Button variant="outline" size="sm" onClick={() => document.getElementById('file-upload')?.click()}>
                      Select File
                    </Button>
                  </label>
                </div>
              )}
            </div>
          </div>

          <div className="flex justify-end">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={handleUpload}
                  disabled={!selectedFile || !title || uploading}
                  className="min-w-[120px]"
                >
                  {uploading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Uploading...
                    </>
                  ) : (
                    <>
                      <Upload className="w-4 h-4 mr-2" />
                      Upload
                    </>
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>Upload file for AI analysis</TooltipContent>
            </Tooltip>
          </div>
        </div>
      </Card>

      {/* Items List */}
      <Card
        title="Intake Items"
        action={
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 transform -translate-y-1/2 text-opsgrid-text-secondary" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search items..."
                className="pl-9 w-64"
              />
            </div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2 border border-opsgrid-border rounded-md bg-opsgrid-bg text-opsgrid-text text-sm"
            >
              <option value="all">All Status</option>
              <option value="pending">Pending</option>
              <option value="analyzed">Analyzed</option>
              <option value="error">Error</option>
            </select>
          </div>
        }
      >
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-8 h-8 animate-spin text-opsgrid-primary" />
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="text-center py-8 text-opsgrid-text-secondary">
            <FileText className="w-12 h-12 mx-auto mb-2 opacity-50" />
            <p>No items in the inbox</p>
            <p className="text-sm">Upload data to get started with AI analysis</p>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredItems.map((item) => (
              <div
                key={item.id}
                className="border border-opsgrid-border rounded-lg p-4 hover:border-opsgrid-border-emphasis transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3 flex-1">
                    <div className="mt-1">
                      {getFileIcon(item.data_type)}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="font-medium text-opsgrid-text">{item.title}</h3>
                        {getStatusBadge(item.status)}
                      </div>
                      <p className="text-sm text-opsgrid-text-secondary mb-2">{item.description}</p>
                      <div className="flex items-center gap-2 text-xs text-opsgrid-text-secondary">
                        <span>{item.data_type}</span>
                        <span>•</span>
                        <span>{new Date(item.created_at).toLocaleString()}</span>
                        {item.file_name && (
                          <>
                            <span>•</span>
                            <span>{item.file_name}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-col gap-2 ml-4">
                    {item.status === 'pending' && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            size="sm"
                            onClick={() => handleAnalyze(item.id)}
                            disabled={analyzing === item.id}
                          >
                            {analyzing === item.id ? (
                              <>
                                <Loader2 className="w-3 h-3 mr-2 animate-spin" />
                                Analyzing...
                              </>
                            ) : (
                              <>
                                <CheckCircle className="w-3 h-3 mr-2" />
                                Analyze
                              </>
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Run AI correlation analysis on this item</TooltipContent>
                      </Tooltip>
                    )}
                    {item.analysis_result && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="outline" size="sm">
                            View Results
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>View detailed analysis results</TooltipContent>
                      </Tooltip>
                    )}
                  </div>
                </div>

                {/* Analysis Results */}
                {item.analysis_result && (
                  <div className="mt-4 pt-4 border-t border-opsgrid-border">
                    <div className="grid grid-cols-2 gap-4 mb-3">
                      <div>
                        <p className="text-xs font-medium text-opsgrid-text-secondary mb-1">Risk Score</p>
                        <Badge variant={item.analysis_result.risk_score > 50 ? 'warning' : 'success'}>
                          {item.analysis_result.risk_score.toFixed(1)}/100
                        </Badge>
                      </div>
                      <div>
                        <p className="text-xs font-medium text-opsgrid-text-secondary mb-1">Domains</p>
                        <div className="flex flex-wrap gap-1">
                          {item.analysis_result.domains_analyzed?.map((domain: string) => (
                            <Badge key={domain} variant="info" className="text-xs">
                              {domain}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    </div>
                    <div>
                      <p className="text-xs font-medium text-opsgrid-text-secondary mb-1">Analysis</p>
                      <p className="text-sm text-opsgrid-text">{item.analysis_result.analysis}</p>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};
