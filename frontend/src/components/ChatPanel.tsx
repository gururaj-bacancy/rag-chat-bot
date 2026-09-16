import { useEffect, useState } from 'react'
import type { ChatMessage } from '../types'
import { getChatHistory, streamChatMessage } from '../api/client'

const FAILED_TURN_TEXT = 'Sorry, something went wrong.'

export default function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getChatHistory()
      .then(setMessages)
      .catch((e) => setError((e as Error).message))
  }, [])

  const send = async () => {
    if (!input.trim()) return
    const userMessage: ChatMessage = { role: 'user', content: input }
    const assistantIndex = messages.length + 1
    setMessages((prev) => [...prev, userMessage, { role: 'assistant', content: '' }])
    setInput('')

    // A failed turn surfaces in two places: the `error` alert (the same one the
    // mount-time history fetch uses) and, in the transcript itself, the
    // in-progress assistant bubble is replaced with a short apology. The bubble
    // is rewritten rather than removed so the transcript keeps its turn
    // structure — the failure stays attached to the question that caused it,
    // and the indices the streaming callbacks close over stay valid.
    const failTurn = (reason: string) => {
      setError(reason)
      setMessages((prev) => {
        const next = [...prev]
        if (next[assistantIndex]) {
          next[assistantIndex] = { role: 'assistant', content: FAILED_TURN_TEXT }
        }
        return next
      })
    }

    try {
      await streamChatMessage(
        userMessage.content,
        (token) => {
          setMessages((prev) => {
            const next = [...prev]
            next[assistantIndex] = { ...next[assistantIndex], content: next[assistantIndex].content + token }
            return next
          })
        },
        (content, citations) => {
          setMessages((prev) => {
            const next = [...prev]
            next[assistantIndex] = { role: 'assistant', content, citations }
            return next
          })
        },
        // The stream itself reported a mid-flight failure (backend `error`
        // event) — the promise still resolves normally, so this is the only
        // signal that the answer will never arrive.
        (streamError) => failTurn(streamError),
      )
    } catch (e) {
      // The request never got off the ground (network failure, non-2xx).
      failTurn((e as Error).message)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <h2>Chat</h2>
      {error && <p role="alert" style={{ color: 'red' }}>{error}</p>}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 8 }}>
            <strong>{m.role === 'user' ? 'You' : 'Assistant'}:</strong> {m.content}
            {m.citations && m.citations.length > 0 && (
              <ul>
                {m.citations.map((c) => (
                  <li key={c.chunk_id}>
                    [{c.number}] {c.filename} ({c.doc_type}), page {c.page_number}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <div>
        <input
          placeholder="Ask a question about your claim"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
        />
        <button onClick={send}>Send</button>
      </div>
    </div>
  )
}
