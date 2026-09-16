import type { DocumentRecord, ChatMessage, Citation } from '../types'

/**
 * Throws on any non-2xx response instead of handing the caller an error body.
 *
 * FastAPI serves errors as `{"detail": "..."}`, which does not match any of
 * the shapes below — without this, a 4xx/5xx would flow into `.json()` and
 * then into `.map(...)` in a component, crashing the React tree (or, for
 * fire-and-forget calls, failing completely silently).
 */
async function handleResponse(res: Response): Promise<Response> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? res.statusText)
  }
  return res
}

export async function listDocuments(): Promise<DocumentRecord[]> {
  const res = await handleResponse(await fetch('/documents'))
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
  await handleResponse(await fetch(`/documents/${id}`, { method: 'DELETE' }))
}

export async function getChatHistory(): Promise<ChatMessage[]> {
  const res = await handleResponse(await fetch('/chat/history'))
  return res.json()
}

export async function streamChatMessage(
  message: string,
  onToken: (text: string) => void,
  onDone: (content: string, citations: Citation[]) => void,
  onError?: (message: string) => void,
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
      // The backend terminates a stream that died mid-flight with an `error`
      // event in place of `done` (see app/api/chat.py). Without handling it,
      // the caller is left with a half-filled assistant bubble and no signal
      // that anything went wrong.
      if (event.type === 'error') onError?.(event.message)
    }
  }
}
