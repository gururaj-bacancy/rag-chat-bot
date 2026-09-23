import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ChatPanel from '../components/ChatPanel'
import * as api from '../api/client'
import type { Citation, Conversation } from '../types'

const DEFAULT_CONVERSATION: Conversation = {
  id: 1,
  title: 'New conversation',
  created_at: '2026-09-24T12:00:00Z',
}

beforeEach(() => {
  vi.spyOn(api, 'listConversations').mockResolvedValue([DEFAULT_CONVERSATION])
  vi.spyOn(api, 'getChatHistory').mockResolvedValue([])
  vi.spyOn(api, 'createConversation').mockResolvedValue({
    id: 2,
    title: 'New conversation',
    created_at: '2026-09-24T12:05:00Z',
  })
})

describe('ChatPanel', () => {
  it('sends a message and renders the streamed response with citations', async () => {
    // Capture the onToken/onDone callbacks and drive them ourselves (rather than having
    // the mock fire them all in one synchronous burst) so each step's DOM effect can be
    // observed in isolation via act(). This proves onToken genuinely appends into the
    // assistant message at the right index — a broken onToken (wrong index, overwrite
    // instead of append, no-op) would fail the intermediate assertions below even though
    // onDone's own final content argument would otherwise mask the bug.
    let capturedOnToken!: (text: string) => void
    let capturedOnDone!: (content: string, citations: Citation[]) => void
    let resolveStream!: () => void
    vi.spyOn(api, 'streamChatMessage').mockImplementation((_conversationId, _msg, onToken, onDone) => {
      capturedOnToken = onToken
      capturedOnDone = onDone
      return new Promise<void>((resolve) => {
        resolveStream = resolve
      })
    })
    render(<ChatPanel />)
    // Let the mount-time listConversations()/getChatHistory() promises settle before
    // interacting, so their resolution doesn't land after send()'s synchronous state
    // updates and stomp on them.
    await screen.findByPlaceholderText(/ask a question/i)

    fireEvent.change(screen.getByPlaceholderText(/ask a question/i), { target: { value: 'Why?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    // streamChatMessage was invoked synchronously as part of the click handler, so the
    // callbacks are already captured.
    expect(capturedOnToken).toBeDefined()
    expect(capturedOnDone).toBeDefined()

    // Intermediate state after the first token: only onToken's contribution should be
    // visible, and it must be anchored at the end of the (whitespace-trimmed) text so it
    // doesn't also match once later tokens or citations arrive.
    act(() => capturedOnToken('Your room rent was capped '))
    expect(screen.getByText(/Your room rent was capped$/)).toBeInTheDocument()
    expect(screen.queryByText(/\[1\]\./)).not.toBeInTheDocument()
    expect(screen.queryByText(/policy\.pdf/i)).not.toBeInTheDocument()

    // Intermediate state after the second token: both tokens appended (not overwritten),
    // still no citations — those only arrive with onDone.
    act(() => capturedOnToken('[1].'))
    expect(screen.getByText(/Your room rent was capped \[1\]\.$/)).toBeInTheDocument()
    expect(screen.queryByText(/policy\.pdf/i)).not.toBeInTheDocument()

    // Final state: onDone's content/citations finalize the message.
    act(() => {
      capturedOnDone('Your room rent was capped [1].', [
        { number: 1, chunk_id: 42, doc_type: 'policy', filename: 'policy.pdf', page_number: 4 },
      ])
      resolveStream()
    })
    expect(screen.getByText(/Your room rent was capped \[1\]\./)).toBeInTheDocument()
    expect(screen.getByText(/policy.pdf.*page 4/i)).toBeInTheDocument()
  })

  it('shows an error message when streaming the response fails', async () => {
    vi.spyOn(api, 'streamChatMessage').mockRejectedValue(new Error('Stream failed: connection reset'))
    render(<ChatPanel />)
    await screen.findByPlaceholderText(/ask a question/i)

    fireEvent.change(screen.getByPlaceholderText(/ask a question/i), { target: { value: 'Why?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Stream failed: connection reset')
    expect(await screen.findByText(/Sorry, something went wrong\./)).toBeInTheDocument()
  })

  it('renders an error and replaces the empty assistant bubble when the stream reports a failure', async () => {
    // The backend terminates a stream that died mid-flight with an `error`
    // event rather than a `done` event, so streamChatMessage's promise still
    // resolves normally — onError is the only signal the answer never arrived.
    let capturedOnToken!: (text: string) => void
    let capturedOnError!: (message: string) => void
    vi.spyOn(api, 'streamChatMessage').mockImplementation(
      async (_conversationId, _msg, onToken, _onDone, onError) => {
        capturedOnToken = onToken
        capturedOnError = onError!
      },
    )
    render(<ChatPanel />)
    await screen.findByPlaceholderText(/ask a question/i)

    fireEvent.change(screen.getByPlaceholderText(/ask a question/i), { target: { value: 'Why?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    // A partial answer had already started streaming before the failure.
    act(() => capturedOnToken('Let me check your policy'))
    expect(screen.getByText(/Let me check your policy/)).toBeInTheDocument()

    act(() => capturedOnError('upstream API error: connection reset'))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('upstream API error: connection reset')
    // The half-finished bubble is replaced rather than left dangling forever.
    expect(screen.getByText(/Sorry, something went wrong\./)).toBeInTheDocument()
    expect(screen.queryByText(/Let me check your policy/)).not.toBeInTheDocument()
    // The user's own question stays in the transcript.
    expect(screen.getByText(/Why\?/)).toBeInTheDocument()
  })

  it('loads and renders chat history on mount', async () => {
    vi.spyOn(api, 'getChatHistory').mockResolvedValue([
      { id: 1, role: 'user', content: 'What is my deductible?' },
      { id: 2, role: 'assistant', content: 'Your deductible is $500.' },
    ])

    render(<ChatPanel />)

    expect(await screen.findByText(/What is my deductible\?/)).toBeInTheDocument()
    expect(await screen.findByText(/Your deductible is \$500\./)).toBeInTheDocument()
  })

  it('starts a new conversation, clearing the transcript', async () => {
    vi.spyOn(api, 'getChatHistory').mockResolvedValueOnce([
      { id: 1, role: 'user', content: 'Old question' },
      { id: 2, role: 'assistant', content: 'Old answer' },
    ])
    const created: Conversation = { id: 7, title: 'New conversation', created_at: '2026-09-24T13:00:00Z' }
    const createConversationMock = vi.spyOn(api, 'createConversation').mockResolvedValue(created)

    render(<ChatPanel />)
    expect(await screen.findByText(/Old question/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /new chat/i }))

    await waitFor(() => expect(createConversationMock).toHaveBeenCalled())
    expect(screen.queryByText(/Old question/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Old answer/)).not.toBeInTheDocument()
    expect(screen.getByText(/upload your bill/i)).toBeInTheDocument()
  })

  it('opens history and switches to a selected conversation', async () => {
    const conversations: Conversation[] = [
      { id: 1, title: 'Current chat', created_at: '2026-09-24T12:00:00Z' },
      { id: 5, title: 'Deductible question', created_at: '2026-09-20T09:00:00Z' },
    ]
    vi.spyOn(api, 'listConversations').mockResolvedValue(conversations)
    const getChatHistoryMock = vi.spyOn(api, 'getChatHistory').mockImplementation((id: number) =>
      Promise.resolve(
        id === 5 ? [{ id: 10, role: 'assistant' as const, content: 'Your deductible is $500.' }] : [],
      ),
    )

    render(<ChatPanel />)
    await screen.findByPlaceholderText(/ask a question/i)

    fireEvent.click(screen.getByRole('button', { name: /history/i }))
    const historyRow = await screen.findByText(/Deductible question/i)
    fireEvent.click(historyRow)

    await waitFor(() => expect(getChatHistoryMock).toHaveBeenCalledWith(5))
    expect(await screen.findByText(/Your deductible is \$500\./)).toBeInTheDocument()
  })

  it('passes the currently selected conversation id to streamChatMessage', async () => {
    const created: Conversation = { id: 9, title: 'New conversation', created_at: '2026-09-24T14:00:00Z' }
    vi.spyOn(api, 'createConversation').mockResolvedValue(created)
    const streamChatMessageMock = vi.spyOn(api, 'streamChatMessage').mockResolvedValue(undefined)

    render(<ChatPanel />)
    await screen.findByPlaceholderText(/ask a question/i)

    fireEvent.click(screen.getByRole('button', { name: /new chat/i }))
    await waitFor(() => expect(screen.getByPlaceholderText(/ask a question/i)).toBeInTheDocument())

    fireEvent.change(screen.getByPlaceholderText(/ask a question/i), { target: { value: 'Why?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => expect(streamChatMessageMock).toHaveBeenCalled())
    expect(streamChatMessageMock.mock.calls[0][0]).toBe(9)
  })
})
