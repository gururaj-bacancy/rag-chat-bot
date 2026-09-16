import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, beforeEach } from 'vitest'
import App from '../App'

beforeEach(() => {
  localStorage.clear()
})

describe('App', () => {
  it('renders the document sidebar and chat panel regions', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: /documents/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /chat/i })).toBeInTheDocument()
  })

  it('defaults to light mode and toggles to dark mode on click, persisting the choice', () => {
    render(<App />)

    expect(document.documentElement.dataset.theme).toBe('light')
    const toggle = screen.getByRole('button', { name: /switch to dark mode/i })

    fireEvent.click(toggle)

    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('theme')).toBe('dark')
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toBeInTheDocument()
  })

  it('reads a previously persisted theme choice on mount', () => {
    localStorage.setItem('theme', 'dark')

    render(<App />)

    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toBeInTheDocument()
  })
})
