import type { DocumentRecord, ChatMessage, Citation } from '../types'

export async function listDocuments(): Promise<DocumentRecord[]> {
  const res = await fetch('/documents')
  return res.json()
}

export async function uploadDocument(file: File, docType: string): Promise<DocumentRecord> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('doc_type', docType)
  const res = await fetch('/documents', { method: 'POST', body: formData })
  if (!res.ok) throw new Error((await res.json()).detail ?? 'Upload failed')
  return res.json()
}

export async function deleteDocument(id: number): Promise<void> {
  await fetch(`/documents/${id}`, { method: 'DELETE' })
}

export async function getChatHistory(): Promise<ChatMessage[]> {
  const res = await fetch('/chat/history')
  return res.json()
}

export async function streamChatMessage(
  message: string,
  onToken: (text: string) => void,
  onDone: (content: string, citations: Citation[]) => void,
): Promise<void> {
  const res = await fetch('/chat/message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const event = JSON.parse(line.slice('data: '.length))
      if (event.type === 'token') onToken(event.text)
      if (event.type === 'done') onDone(event.content, event.citations)
    }
  }
}
