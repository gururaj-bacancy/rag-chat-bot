import { useEffect, useState } from 'react'
import type { DocumentRecord } from '../types'
import { listDocuments, uploadDocument, deleteDocument } from '../api/client'

const DOC_TYPES: DocumentRecord['doc_type'][] = ['bill', 'policy', 'settlement']

const DOC_TYPE_HINTS: Record<DocumentRecord['doc_type'], string> = {
  bill: 'Hospital final bill',
  policy: 'Mediclaim policy',
  settlement: 'Claim settlement letter',
}

function DocumentIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M6 2h9l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Z"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path d="M14 2v6h6" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 7h16M9 7V4h6v3m-8 0 1 14a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1l1-14"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export default function DocumentSidebar() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [error, setError] = useState<string | null>(null)

  const refresh = () =>
    listDocuments()
      .then(setDocuments)
      .catch((e) => setError((e as Error).message))

  useEffect(() => {
    refresh()
  }, [])

  const handleUpload = async (docType: DocumentRecord['doc_type'], file: File) => {
    setError(null)
    try {
      await uploadDocument(file, docType)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await deleteDocument(id)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div>
      <h2 className="section-heading">Documents</h2>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}

      <div className="upload-grid">
        {DOC_TYPES.map((docType) => (
          <label key={docType} className="upload-card">
            <input
              type="file"
              accept="application/pdf"
              className="visually-hidden"
              onChange={(e) => e.target.files?.[0] && handleUpload(docType, e.target.files[0])}
            />
            <span className="upload-icon">
              <DocumentIcon />
            </span>
            <span className="upload-label-text">
              <span className="upload-label-title">{docType}</span>
              <span className="upload-label-hint">{DOC_TYPE_HINTS[docType]}</span>
            </span>
          </label>
        ))}
      </div>

      {documents.length === 0 ? (
        <p className="empty-hint">No documents uploaded yet.</p>
      ) : (
        <ul className="document-list">
          {documents.map((doc) => (
            <li key={doc.id} className="document-item">
              <span className="document-name">{doc.filename}</span>
              <span className={`status-badge status-badge--${doc.status}`}>{doc.status}</span>
              <button
                aria-label={`delete ${doc.filename}`}
                className="icon-button"
                onClick={() => handleDelete(doc.id)}
              >
                <TrashIcon />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
