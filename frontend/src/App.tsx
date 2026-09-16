import DocumentSidebar from './components/DocumentSidebar'
import ChatPanel from './components/ChatPanel'

export default function App() {
  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <aside style={{ width: 280, borderRight: '1px solid #ddd', padding: 16 }}>
        <DocumentSidebar />
      </aside>
      <main style={{ flex: 1, padding: 16 }}>
        <ChatPanel />
      </main>
    </div>
  )
}
