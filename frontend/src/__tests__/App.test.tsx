import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import App from '../App'

describe('App', () => {
  it('renders the document sidebar and chat panel regions', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: /documents/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /chat/i })).toBeInTheDocument()
  })
})
