import { useEffect, useState } from 'react'
import type { ChatMessage } from '../types'
import { getChatHistory, streamChatMessage } from '../api/client'

const FAILED_TURN_TEXT = 'Sorry, something went wrong.'

function SendIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 12h16M13 5l7 7-7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

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
    <div className="chat-container">
      <div className="chat-header">
        <h2 className="section-heading">Chat</h2>
      </div>
      {error && (
        <p role="alert" className="alert" style={{ margin: '0 24px 16px' }}>
          {error}
        </p>
      )}
      <div className="message-list">
        {messages.length === 0 && (
          <p className="chat-empty-state">
            Upload your bill, policy, and settlement letter, then ask a question about your claim
            to get started.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`message message--${m.role}`}>
            <span className="message-role">{m.role === 'user' ? 'You' : 'Assistant'}</span>
            {m.role === 'assistant' && m.content === '' ? (
              <span className="typing-indicator">
                <span />
                <span />
                <span />
              </span>
            ) : (
              <span className="message-text">{m.content}</span>
            )}
            {m.citations && m.citations.length > 0 && (
              <ul className="citation-list">
                {m.citations.map((c) => (
                  <li key={c.chunk_id} className="citation-chip">
                    [{c.number}] {c.filename} ({c.doc_type}), page {c.page_number}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <div className="chat-input-bar">
        <input
          className="chat-input"
          placeholder="Ask a question about your claim"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
        />
        <button className="send-button" onClick={send}>
          Send
          <SendIcon />
        </button>
      </div>
    </div>
  )
}
