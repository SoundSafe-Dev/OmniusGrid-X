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
  // A failed load rendered "No items in the inbox" above "Upload data to get started" — an
  // invitation to re-upload work that may already be there.
  const [loadError, setLoadError] = useState<string | null>(null);
  // A failed UPLOAD or ANALYSE reached only the console (FS-478). The user pressed a
  // button on purpose, so the absence of any response is indistinguishable from the
  // moment before the list refreshes — and for analyse it is worse, because the spinner
  // stops and the row simply stays as it was, which is what "nothing to analyse" looks
  // like. Same class the useMutation sweep covers; this page does not use useMutation, so
  // the sweep could not see it.
  const [actionError, setActionError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [loadingResults, setLoadingResults] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [dataType, setDataType] = useState<'spreadsheet' | 'report' | 'image' | 'document'>('document');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  useEffect(() => {
    // P3 (page-enhancement review): this effect ran once with `[]` while the status
    // select wrote state the request had already captured — the dropdown APPEARED to
    // filter and did nothing. `loadIntakeItems` reads `statusFilter` from the closure,
    // so the filter is the dependency that makes the request follow the control.
    loadIntakeItems();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- loadIntakeItems is stable per render; statusFilter is the real input
  }, [statusFilter]);

  const loadIntakeItems = async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const response = await nlpCorrelationApi.listIntakeItems(50, 0, statusFilter === 'all' ? undefined : statusFilter);
      setItems(response.items);
    } catch (error) {
      console.error('Error loading intake items:', error);
      setLoadError('Could not load the inbox.');
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
    setActionError(null);
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
      setActionError(
        `Could not upload ${selectedFile.name}. The file was not added to the inbox.`,
      );
    } finally {
      setUploading(false);
    }
  };

  const handleAnalyze = async (itemId: string) => {
    setAnalyzing(itemId);
    setActionError(null);
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
      // Names the item: the inbox shows many rows and a bare "analysis failed" leaves the
      // operator guessing which button they pressed.
      const failed = items.find((item) => item.id === itemId);
      setActionError(
        `Could not analyse ${failed?.title ?? 'that item'}. It has not been analysed.`,
      );
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
              <label htmlFor="intakeinbox-data-type" className="block text-sm font-medium text-opsgrid-text mb-1">Data Type</label>
              <select
              id="intakeinbox-data-type"
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
        {/* A failed upload or analysis, said out loud (FS-478). Above the list rather than
            beside the button, because the analyse buttons are per-row and the failure has
            to survive the row re-rendering. */}
        {actionError && (
          <div
            role="alert"
            className="mb-4 rounded border border-status-alarm/40 bg-status-alarm/10 px-3 py-2 text-sm text-status-alarm"
          >
            {actionError}
          </div>
        )}
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-8 h-8 animate-spin text-opsgrid-primary" />
          </div>
        ) : loadError ? (
          <div className="text-center py-8 text-status-alarm" role="alert">
            <p>{loadError}</p>
            <p className="text-sm text-opsgrid-text-secondary">
              This is a loading failure, not an empty inbox.
            </p>
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
                    {item.status === 'analyzed' && !item.analysis_result && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={loadingResults === item.id}
                            onClick={async () => {
                              // P3: this button had NO onClick — and the list endpoint
                              // never sends analysis_result, so for any item analysed
                              // before the last reload this dead button was the only
                              // path to results that only GET /intake/{id} carries.
                              setActionError(null);
                              setLoadingResults(item.id);
                              try {
                                const full = await nlpCorrelationApi.getIntakeItem(item.id);
                                setItems((prev) =>
                                  prev.map((existing) =>
                                    existing.id === item.id
                                      ? { ...existing, analysis_result: full.analysis_result }
                                      : existing,
                                  ),
                                );
                              } catch {
                                setActionError(
                                  `Could not load results for "${item.title}".`,
                                );
                              } finally {
                                setLoadingResults(null);
                              }
                            }}
                          >
                            {loadingResults === item.id ? (
                              <>
                                <Loader2 className="w-3 h-3 mr-2 animate-spin" />
                                Loading…
                              </>
                            ) : (
                              'View Results'
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Load the detailed analysis results</TooltipContent>
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
                    {/* The analysis was built from part of the document (FS-456).

                        The parser caps pages, and caps text within each page. Both caps
                        already reached this component and neither was rendered — so a risk
                        score derived from the first 20k characters of a 90k-character page
                        read exactly like one derived from the whole thing. A confident
                        number over a partial reading is worse than no number, because
                        nothing about it looks partial. */}
                    {(item.analysis_result.truncated ||
                      item.analysis_result.pages_text_truncated > 0) && (
                      <div className="mb-3 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2">
                        <p className="text-xs text-amber-300">
                          Analysed from part of the document
                          {item.analysis_result.truncated && ' — some pages were not read'}
                          {item.analysis_result.pages_text_truncated > 0 &&
                            ` — text was cut on ${item.analysis_result.pages_text_truncated} page(s)` +
                              (item.analysis_result.text_chars_dropped
                                ? ` (${item.analysis_result.text_chars_dropped.toLocaleString()} characters dropped)`
                                : '')}
                          . Findings below may be incomplete.
                        </p>
                      </div>
                    )}
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
