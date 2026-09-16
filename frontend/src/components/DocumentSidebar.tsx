import { useEffect, useState } from 'react'
import type { DocumentRecord } from '../types'
import { listDocuments, uploadDocument, deleteDocument } from '../api/client'

const DOC_TYPES: DocumentRecord['doc_type'][] = ['bill', 'policy', 'settlement']

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
      <h2>Documents</h2>
      {error && <p role="alert" style={{ color: 'red' }}>{error}</p>}
      {DOC_TYPES.map((docType) => (
        <div key={docType} style={{ marginBottom: 12 }}>
          <label>
            {docType}
            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => e.target.files?.[0] && handleUpload(docType, e.target.files[0])}
            />
          </label>
        </div>
      ))}
      <ul>
        {documents.map((doc) => (
          <li key={doc.id}>
            <span>{doc.filename}</span> ({doc.status})
            <button aria-label={`delete ${doc.filename}`} onClick={() => handleDelete(doc.id)}>
              Delete
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
