import React, { useState, useEffect } from 'react';
import { ErrorState } from '../ui';
import { Link } from 'react-router-dom';
import { nlpCorrelationApi, IntakeItem } from '../../api/nlpCorrelation';
import { X, Search, FileText, Image, FileSpreadsheet, Loader2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Badge } from '../ui/Badge';

interface IntakeSelectorDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (intakeId: string) => Promise<void>;
}

export const IntakeSelectorDialog: React.FC<IntakeSelectorDialogProps> = ({
  isOpen,
  onClose,
  onSelect
}) => {
  const [items, setItems] = useState<IntakeItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  // A failed fetch rendered "No items found", which is how the dialog says a user has
  // nothing to select from.
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [addingId, setAddingId] = useState<string | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setSelectionError(null);
      setAddingId(null);
      loadIntakeItems();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing; adding deps changes retrigger behavior (FS-54)
  }, [isOpen, statusFilter]);

  const loadIntakeItems = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await nlpCorrelationApi.listIntakeItems(50, 0, statusFilter === 'all' ? undefined : statusFilter);
      setItems(response.items);
    } catch (err) {
      console.error('Error loading intake items:', err);
      setError('Could not load intake items.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelect = async (intakeId: string) => {
    if (addingId) return;
    setAddingId(intakeId);
    setSelectionError(null);
    try {
      await onSelect(intakeId);
      onClose();
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setSelectionError(
        typeof detail === 'string'
          ? detail
          : detail?.message || error?.message || 'Could not add this item to the chat session.'
      );
    } finally {
      setAddingId(null);
    }
  };

  const getFileIcon = (dataType: string) => {
    switch (dataType) {
      case 'spreadsheet':
        return <FileSpreadsheet className="w-5 h-5 text-green-600" />;
      case 'image':
        return <Image className="w-5 h-5 text-purple-600" />;
      default:
        return <FileText className="w-5 h-5 text-blue-600" />;
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

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-opsgrid-panel rounded-lg shadow-xl w-full max-w-3xl max-h-[80vh] flex flex-col">
        <div className="p-4 border-b border-opsgrid-border flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-opsgrid-text">Add an uploaded Intake item</h2>
            <p className="mt-1 text-xs text-opsgrid-text-secondary">
              This list contains files already uploaded to the Intake Inbox.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Link
              to="/intake"
              onClick={onClose}
              className="inline-flex h-8 items-center rounded-md border border-gray-300 bg-white px-3 text-xs font-medium text-gray-900 hover:bg-gray-100"
            >
              Upload to Intake Inbox
            </Link>
            <Button variant="outline" size="sm" onClick={onClose} aria-label="Close Intake Inbox selector">
              <X className="w-4 h-4" />
            </Button>
          </div>
        </div>

        <div className="p-4 border-b border-opsgrid-border">
          <div className="flex gap-3">
            <div className="relative flex-1">
              <Search className="w-4 h-4 absolute left-3 top-1/2 transform -translate-y-1/2 text-opsgrid-text-secondary" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search items..."
                className="pl-9"
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
          {selectionError && (
            <p className="mt-3 rounded border border-status-alarm/50 bg-status-alarm/10 p-2 text-xs text-status-alarm">
              {selectionError}
            </p>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <div className="text-center text-opsgrid-text-secondary py-8">Loading...</div>
          ) : error ? (
            <ErrorState
              message={error}
              onRetry={() => loadIntakeItems()}
              retrying={isLoading}
            />
          ) : filteredItems.length === 0 ? (
            <div className="text-center text-opsgrid-text-secondary py-8">
              <p>No items found in the Intake Inbox.</p>
              <Link
                to="/intake"
                onClick={onClose}
                className="mt-3 inline-flex text-sm font-medium text-opsgrid-primary hover:underline"
              >
                Upload files to Intake Inbox
              </Link>
            </div>
          ) : (
            <div className="space-y-3">
              {filteredItems.map((item) => (
                <div
                  key={item.id}
                  className={`border border-opsgrid-border rounded-lg p-4 transition-colors ${
                    addingId ? 'cursor-wait opacity-70' : 'cursor-pointer hover:border-opsgrid-border-emphasis'
                  }`}
                  onClick={() => void handleSelect(item.id)}
                >
                  <div className="flex items-start gap-3">
                    <div className="mt-1">
                      {getFileIcon(item.data_type)}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="font-medium text-opsgrid-text">{item.title}</h3>
                        {getStatusBadge(item.status)}
                        {addingId === item.id && (
                          <span className="inline-flex items-center gap-1 text-xs text-opsgrid-text-secondary">
                            <Loader2 className="h-3 w-3 animate-spin" /> Adding to chat…
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-opsgrid-text-secondary mb-2">{item.description}</p>
                      <div className="flex items-center gap-2 text-xs text-opsgrid-text-secondary">
                        <span>{item.data_type}</span>
                        <span>•</span>
                        <span>{new Date(item.created_at).toLocaleString()}</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
