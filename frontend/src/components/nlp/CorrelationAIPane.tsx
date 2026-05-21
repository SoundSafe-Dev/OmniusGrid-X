import React, { useState, useRef, useEffect } from 'react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { Badge } from '../ui/Badge';
import { nlpCorrelationApi, ChatMessage } from '../../api/nlpCorrelation';
import { Send, Loader2, CheckCircle } from 'lucide-react';

interface CorrelationAIPaneProps {
  className?: string;
}

export const CorrelationAIPane: React.FC<CorrelationAIPaneProps> = ({ className }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [autoIntegrate, setAutoIntegrate] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSendMessage = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: ChatMessage = {
      role: 'user',
      content: input,
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await nlpCorrelationApi.chat(
        userMessage.content,
        messages
      );

      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: response.content,
        analysis: response.analysis,
        risk_score: response.risk_score,
        domains: response.domains,
        actions: response.actions,
        timestamp: response.timestamp
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage: ChatMessage = {
        role: 'assistant',
        content: 'Sorry, I encountered an error processing your request. Please try again.',
        timestamp: new Date().toISOString()
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const getRiskScoreVariant = (score: number) => {
    if (score > 75) return 'error';
    if (score > 50) return 'warning';
    if (score > 25) return 'info';
    return 'success';
  };

  const getRiskScoreLabel = (score: number) => {
    if (score > 75) return 'Critical';
    if (score > 50) return 'High';
    if (score > 25) return 'Medium';
    return 'Low';
  };

  return (
    <Card
      className={className}
      title="Correlation AI Assistant"
      action={
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={autoIntegrate}
              onChange={(e) => setAutoIntegrate(e.target.checked)}
              className="rounded"
            />
            Auto-integrate with Kanban
          </label>
        </div>
      }
    >
      <div className="flex flex-col h-[600px]">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-4 mb-4 p-4 bg-gray-50 rounded-lg">
          {messages.length === 0 && (
            <div className="text-center text-gray-500 py-8">
              <p className="text-lg font-medium mb-2">Ask me anything about your operations</p>
              <p className="text-sm">
                I can analyze operational data, identify correlations, and recommend actions.
                Try asking about production issues, logistics delays, maintenance needs, or compliance concerns.
              </p>
            </div>
          )}

          {messages.map((message, index) => (
            <div
              key={index}
              className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[80%] rounded-lg p-4 ${
                  message.role === 'user'
                    ? 'bg-blue-500 text-white'
                    : 'bg-white border border-gray-200 shadow-sm'
                }`}
              >
                {message.role === 'assistant' && message.risk_score !== undefined && (
                  <div className="mb-3">
                    <Badge variant={getRiskScoreVariant(message.risk_score)}>
                      {getRiskScoreLabel(message.risk_score)} Risk: {message.risk_score.toFixed(1)}/100
                    </Badge>
                  </div>
                )}

                {message.domains && message.domains.length > 0 && (
                  <div className="mb-2 flex flex-wrap gap-1">
                    {message.domains.map((domain) => (
                      <Badge key={domain} variant="info" className="text-xs">
                        {domain}
                      </Badge>
                    ))}
                  </div>
                )}

                <p className="text-sm whitespace-pre-wrap">{message.content}</p>

                {message.actions && message.actions.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-gray-200">
                    <p className="text-xs font-medium text-gray-700 mb-2">Recommended Actions:</p>
                    <ul className="text-xs space-y-1">
                      {message.actions.map((action, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <CheckCircle className="w-3 h-3 mt-0.5 text-green-500" />
                          <span>{action.description || action.command || JSON.stringify(action)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <p className="text-xs mt-2 opacity-70">
                  {new Date(message.timestamp).toLocaleTimeString()}
                </p>
              </div>
            </div>
          ))}

          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-white border border-gray-200 shadow-sm rounded-lg p-4">
                <div className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
                  <span className="text-sm text-gray-600">Analyzing...</span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Ask about operational issues, correlations, or recommendations..."
            disabled={isLoading}
            className="flex-1"
          />
          <Button
            onClick={handleSendMessage}
            disabled={isLoading || !input.trim()}
            className="px-4"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </div>
      </div>
    </Card>
  );
};
