import { describe, it, expect, vi, afterEach } from 'vitest'
import { listDocuments, deleteDocument, getChatHistory } from '../api/client'

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
