import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ChatPanel from '../components/ChatPanel'
import * as api from '../api/client'

beforeEach(() => {
  vi.spyOn(api, 'getChatHistory').mockResolvedValue([])
})

describe('ChatPanel', () => {
  it('sends a message and renders the streamed response with citations', async () => {
    vi.spyOn(api, 'streamChatMessage').mockImplementation(async (_msg, onToken, onDone) => {
      onToken('Your room rent was capped ')
      onToken('[1].')
      onDone('Your room rent was capped [1].', [
        { number: 1, chunk_id: 42, doc_type: 'policy', filename: 'policy.pdf', page_number: 4 },
      ])
    })
    render(<ChatPanel />)
    // Let the mount-time getChatHistory() promise settle before interacting, so its
    // resolution doesn't land after send()'s synchronous state updates and stomp on them.
    await screen.findByPlaceholderText(/ask a question/i)

    fireEvent.change(screen.getByPlaceholderText(/ask a question/i), { target: { value: 'Why?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => expect(screen.getByText(/Your room rent was capped \[1\]\./)).toBeInTheDocument())
    expect(screen.getByText(/policy.pdf.*page 4/i)).toBeInTheDocument()
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
