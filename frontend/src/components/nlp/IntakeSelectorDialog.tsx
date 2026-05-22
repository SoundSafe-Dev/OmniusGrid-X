import React, { useState, useEffect } from 'react';
import { nlpCorrelationApi, IntakeItem } from '../../api/nlpCorrelation';
import { X, Search, FileText, Image, FileSpreadsheet } from 'lucide-react';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Badge } from '../ui/Badge';

interface IntakeSelectorDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (intakeId: string) => void;
}

export const IntakeSelectorDialog: React.FC<IntakeSelectorDialogProps> = ({
  isOpen,
  onClose,
  onSelect
}) => {
  const [items, setItems] = useState<IntakeItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  useEffect(() => {
    if (isOpen) {
      loadIntakeItems();
    }
  }, [isOpen, statusFilter]);

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

  const handleSelect = (intakeId: string) => {
    onSelect(intakeId);
    onClose();
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
    item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-opsgrid-panel rounded-lg shadow-xl w-full max-w-3xl max-h-[80vh] flex flex-col">
        <div className="p-4 border-b border-opsgrid-border flex items-center justify-between">
          <h2 className="text-lg font-semibold text-opsgrid-text">Select from Intake Inbox</h2>
          <Button variant="outline" size="sm" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
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
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <div className="text-center text-opsgrid-text-secondary py-8">Loading...</div>
          ) : filteredItems.length === 0 ? (
            <div className="text-center text-opsgrid-text-secondary py-8">
              No items found
            </div>
          ) : (
            <div className="space-y-3">
              {filteredItems.map((item) => (
                <div
                  key={item.id}
                  className="border border-opsgrid-border rounded-lg p-4 hover:border-opsgrid-border-emphasis cursor-pointer transition-colors"
                  onClick={() => handleSelect(item.id)}
                >
                  <div className="flex items-start gap-3">
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
