import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  listDocuments,
  deleteDocument,
  getChatHistory,
  listConversations,
  createConversation,
  streamChatMessage,
} from '../api/client'

/**
 * These exercise the one thing the component tests can't: the real client
 * functions against the real `fetch`. Every other frontend test mocks the
 * `api/client` module wholesale, so a client that happily returned a FastAPI
 * `{"detail": "..."}` error body as if it were a success payload would go
 * unnoticed until a component tried to `.map` over it at runtime.
 */
function mockFetch(response: Partial<Response>) {
  const fetchMock = vi.fn().mockResolvedValue(response as Response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api client error handling', () => {
  it('listDocuments rejects with the detail message on a non-2xx response', async () => {
    mockFetch({ ok: false, status: 500, statusText: 'Internal Server Error', json: async () => ({ detail: 'db is down' }) })
    await expect(listDocuments()).rejects.toThrow('db is down')
  })

  it('deleteDocument rejects with the detail message on a non-2xx response', async () => {
    mockFetch({ ok: false, status: 404, statusText: 'Not Found', json: async () => ({ detail: 'Document not found' }) })
    await expect(deleteDocument(7)).rejects.toThrow('Document not found')
  })

  it('getChatHistory rejects with the detail message on a non-2xx response', async () => {
    mockFetch({ ok: false, status: 503, statusText: 'Service Unavailable', json: async () => ({ detail: 'unavailable' }) })
    await expect(getChatHistory()).rejects.toThrow('unavailable')
  })

  it('falls back to statusText when the error body is not JSON', async () => {
    mockFetch({
      ok: false,
      status: 502,
      statusText: 'Bad Gateway',
      json: async () => {
        throw new Error('Unexpected token < in JSON')
      },
    })
    await expect(listDocuments()).rejects.toThrow('Bad Gateway')
  })

  it('returns the parsed body on a successful response', async () => {
    const docs = [{ id: 1, doc_type: 'bill', filename: 'bill.pdf', status: 'indexed' }]
    mockFetch({ ok: true, status: 200, statusText: 'OK', json: async () => docs })
    await expect(listDocuments()).resolves.toEqual(docs)
  })
})

describe('listConversations', () => {
  it('parses the conversation array on a successful response', async () => {
    const conversations = [
      { id: 2, title: 'Second chat', created_at: '2026-09-24T10:00:00Z' },
      { id: 1, title: 'New conversation', created_at: '2026-09-23T10:00:00Z' },
    ]
    const fetchMock = mockFetch({ ok: true, status: 200, statusText: 'OK', json: async () => conversations })
    await expect(listConversations()).resolves.toEqual(conversations)
    expect(fetchMock).toHaveBeenCalledWith('/chat/conversations')
  })

  it('rejects with the detail message on a non-2xx response', async () => {
    mockFetch({ ok: false, status: 500, statusText: 'Internal Server Error', json: async () => ({ detail: 'db is down' }) })
    await expect(listConversations()).rejects.toThrow('db is down')
  })
})

describe('createConversation', () => {
  it('posts with no body and returns the parsed conversation', async () => {
    const conversation = { id: 3, title: 'New conversation', created_at: '2026-09-24T12:00:00Z' }
    const fetchMock = mockFetch({ ok: true, status: 200, statusText: 'OK', json: async () => conversation })
    await expect(createConversation()).resolves.toEqual(conversation)
    expect(fetchMock).toHaveBeenCalledWith('/chat/conversations', { method: 'POST' })
  })

  it('rejects with the detail message on a non-2xx response', async () => {
    mockFetch({ ok: false, status: 500, statusText: 'Internal Server Error', json: async () => ({ detail: 'db is down' }) })
    await expect(createConversation()).rejects.toThrow('db is down')
  })
})

describe('getChatHistory', () => {
  it('sends conversation_id as a query param', async () => {
    const fetchMock = mockFetch({ ok: true, status: 200, statusText: 'OK', json: async () => [] })
    await getChatHistory(5)
    expect(fetchMock).toHaveBeenCalledWith('/chat/history?conversation_id=5')
  })
})

describe('streamChatMessage', () => {
  /** Builds a fake fetch Response whose body streams the given SSE frames. */
  function mockSseFetch(events: Array<Record<string, unknown>>) {
    const encoder = new TextEncoder()
    const frames = events.map((event) => encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
    let index = 0
    const reader = {
      read: async () => {
        if (index < frames.length) {
          return { done: false, value: frames[index++] }
        }
        return { done: true, value: undefined }
      },
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: { getReader: () => reader },
    } as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('sends conversation_id and message in the POST body', async () => {
    const fetchMock = mockSseFetch([{ type: 'done', content: 'hi there', citations: [] }])
    const onToken = vi.fn()
    const onDone = vi.fn()

    await streamChatMessage(5, 'Why?', onToken, onDone)

    expect(fetchMock).toHaveBeenCalledWith('/chat/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: 5, message: 'Why?' }),
    })
  })

  it('invokes onToken for each token event and onDone with the final content/citations', async () => {
    const citations = [{ number: 1, chunk_id: 42, doc_type: 'policy', filename: 'policy.pdf', page_number: 4 }]
    mockSseFetch([
      { type: 'token', text: 'Your room ' },
      { type: 'token', text: 'rent was capped' },
      { type: 'done', content: 'Your room rent was capped', citations },
    ])
    const onToken = vi.fn()
    const onDone = vi.fn()

    await streamChatMessage(5, 'Why?', onToken, onDone)

    expect(onToken).toHaveBeenNthCalledWith(1, 'Your room ')
    expect(onToken).toHaveBeenNthCalledWith(2, 'rent was capped')
    expect(onDone).toHaveBeenCalledWith('Your room rent was capped', citations)
  })

  it('invokes onError when the stream reports an error event', async () => {
    mockSseFetch([{ type: 'error', message: 'upstream API error: connection reset' }])
    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()

    await streamChatMessage(5, 'Why?', onToken, onDone, onError)

    expect(onError).toHaveBeenCalledWith('upstream API error: connection reset')
    expect(onDone).not.toHaveBeenCalled()
  })
})
