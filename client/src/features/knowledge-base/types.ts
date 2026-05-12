export interface KnowledgeItem {
  id: string;
  title: string;
  resume: string;
  content: string;
  source_block_ids?: string[];
  source_file?: string;
}

export type KnowledgeDocumentStatus = 'pending' | 'copying' | 'converting' | 'analyzing' | 'saving' | 'success' | 'error';

export interface KnowledgeFolder {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: string;
  folder_id: string;
  file_name: string;
  status: KnowledgeDocumentStatus;
  progress: number;
  message: string;
  item_count: number;
  created_at: string;
  updated_at: string;
  error?: string;
}

export interface KnowledgeBaseIndex {
  folders: KnowledgeFolder[];
  documents: KnowledgeDocument[];
}

export interface KnowledgeBaseUploadResult {
  success: boolean;
  message: string;
  documents?: KnowledgeDocument[];
}

export interface KnowledgeBaseEvent {
  document: KnowledgeDocument;
}
