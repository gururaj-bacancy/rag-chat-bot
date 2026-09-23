export interface DocumentRecord {
  id: number
  doc_type: 'bill' | 'policy' | 'settlement'
  filename: string
  status: 'processing' | 'indexed' | 'failed'
}

export interface Citation {
  number: number
  chunk_id: number
  doc_type: string
  filename: string
  page_number: number | null
}

export interface ChatMessage {
  id?: number
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}

export interface Conversation {
  id: number
  title: string
  created_at: string
}
