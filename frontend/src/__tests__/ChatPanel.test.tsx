import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ChatPanel from '../components/ChatPanel'
import * as api from '../api/client'
import type { Citation } from '../types'

beforeEach(() => {
  vi.spyOn(api, 'getChatHistory').mockResolvedValue([])
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
    vi.spyOn(api, 'streamChatMessage').mockImplementation((_msg, onToken, onDone) => {
      capturedOnToken = onToken
      capturedOnDone = onDone
      return new Promise<void>((resolve) => {
        resolveStream = resolve
      })
    })
    render(<ChatPanel />)
    // Let the mount-time getChatHistory() promise settle before interacting, so its
    // resolution doesn't land after send()'s synchronous state updates and stomp on them.
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
})
