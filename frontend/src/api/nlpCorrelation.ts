import { api } from './client';
import { USE_MOCK } from './mockMode';
import { mockIntakeItems, mockIntakeList } from './mocks/nlpMocks';

export interface NLPQueryRequest {
  query: string;
  context?: Record<string, any>;
  include_domains?: string[];
  auto_integrate?: boolean;
}

export interface NLPQueryResponse {
  query: string;
  analysis: string;
  domains_analyzed: string[];
  risk_score: number;
  recommended_actions: any[];
  kanban_tasks: any[];
  compliance_implications?: string[];
  integration_result?: { [key: string]: string[] };
}

export interface IntakeUploadRequest {
  title: string;
  description?: string;
  data_type: 'spreadsheet' | 'report' | 'image' | 'document';
  category?: string;
}

export interface IntakeAnalysisRequest {
  intake_id: string;
  query?: string;
  auto_integrate?: boolean;
}

export interface IntakeItem {
  id: string;
  title: string;
  description: string;
  data_type: string;
  category: string;
  file_name?: string;
  status: string;
  analysis_result?: any;
  created_at: string;
  analyzed_at?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  analysis?: string;
  risk_score?: number;
  domains?: string[];
  actions?: any[];
  timestamp: string;
}

export const nlpCorrelationApi = {
  // NLP Query
  async queryNLP(request: NLPQueryRequest): Promise<NLPQueryResponse> {
    const response = await api.post(`/api/v1/nlp/correlation/query`, request);
    return response.data;
  },

  // Chat interface
  async chat(message: string, conversationHistory?: ChatMessage[]): Promise<ChatMessage> {
    // `conversation_history` is a BODY parameter, not a query parameter. The handler
    // declares it `Optional[List[Dict[str, str]]]`, and FastAPI reads complex types
    // from the body — so sending it in `params` with a `null` body meant the server
    // received `None` every time. The endpoint's docstring promises it "maintains
    // conversation context for multi-turn queries"; it never received any context to
    // maintain. `message` genuinely is a query parameter and stays there.
    const response = await api.post(
      `/api/v1/nlp/correlation/chat`,
      conversationHistory ?? null,
      { params: { message } }
    );
    return response.data;
  },

  // Intake Inbox
  async uploadToIntake(
    file: File,
    title: string,
    description: string = '',
    data_type: 'spreadsheet' | 'report' | 'image' | 'document' = 'document',
    category: string = 'general'
  ): Promise<IntakeItem> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', title);
    formData.append('description', description);
    formData.append('data_type', data_type);
    formData.append('category', category);

    const response = await api.post(`/api/v1/nlp/correlation/intake/upload`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
    return response.data;
  },

  async analyzeIntake(
    intake_id: string,
    query?: string,
    auto_integrate: boolean = true
  ): Promise<any> {
    const response = await api.post(`/api/v1/nlp/correlation/intake/analyze`, null, {
      params: {
        intake_id,
        query,
        auto_integrate
      }
    });
    return response.data;
  },

  async listIntakeItems(limit: number = 50, offset: number = 0, status?: string): Promise<{ items: IntakeItem[]; total: number }> {
    if (USE_MOCK) {
      return mockIntakeList(status);
    }
    const response = await api.get(`/api/v1/nlp/correlation/intake/list`, {
      params: { limit, offset, status }
    });
    return response.data;
  },

  async getIntakeItem(intake_id: string): Promise<IntakeItem> {
    if (USE_MOCK) {
      const match = mockIntakeItems.find((i) => i.id === intake_id);
      if (match) return match;
      throw new Error(`Mock intake item not found: ${intake_id}`);
    }
    const response = await api.get(`/api/v1/nlp/correlation/intake/${intake_id}`);
    return response.data;
  }
};
