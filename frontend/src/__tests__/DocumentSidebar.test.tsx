import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import DocumentSidebar from '../components/DocumentSidebar'
import * as api from '../api/client'

beforeEach(() => {
  vi.spyOn(api, 'listDocuments').mockResolvedValue([
    { id: 1, doc_type: 'bill', filename: 'bill.pdf', status: 'indexed' },
  ])
})

describe('DocumentSidebar', () => {
  it('lists uploaded documents and deletes on click', async () => {
    const deleteSpy = vi.spyOn(api, 'deleteDocument').mockResolvedValue(undefined)
    render(<DocumentSidebar />)

    expect(await screen.findByText('bill.pdf')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /delete bill.pdf/i }))

    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith(1))
  })

  it('shows an error message when upload fails', async () => {
    vi.spyOn(api, 'uploadDocument').mockRejectedValue(
      new Error("An active 'policy' document already exists..."),
    )
    render(<DocumentSidebar />)

    await screen.findByText('bill.pdf')

    const file = new File(['dummy content'], 'policy.pdf', { type: 'application/pdf' })
    const input = screen.getByLabelText(/policy/i) as HTMLInputElement

    fireEvent.change(input, { target: { files: [file] } })

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("An active 'policy' document already exists...")
  })
})
