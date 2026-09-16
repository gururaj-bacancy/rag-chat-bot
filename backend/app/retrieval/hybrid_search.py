from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

RRF_K = 60


@dataclass
class SearchResult:
    chunk_id: int
    document_id: int
    chunk_text: str
    page_number: int | None
    score: float


def hybrid_search(session: Session, query_text: str, query_embedding: list[float], top_k: int = 8) -> list[SearchResult]:
    fetch_n = max(top_k * 5, 20)
    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    dense_rows = session.execute(text(
        "SELECT id, document_id, chunk_text, page_number "
        "FROM chunks ORDER BY embedding <=> :query_vector LIMIT :n"
    ), {"query_vector": embedding_str, "n": fetch_n}).fetchall()

    sparse_rows = session.execute(text(
        "SELECT id, document_id, chunk_text, page_number "
        "FROM chunks WHERE search_vector @@ plainto_tsquery('english', :q) "
        "ORDER BY ts_rank(search_vector, plainto_tsquery('english', :q)) DESC LIMIT :n"
    ), {"q": query_text, "n": fetch_n}).fetchall()

    fused_scores: dict[int, float] = {}
    row_by_id: dict[int, tuple] = {}
    for rank, row in enumerate(dense_rows):
        fused_scores[row.id] = fused_scores.get(row.id, 0.0) + 1.0 / (RRF_K + rank + 1)
        row_by_id[row.id] = row
    for rank, row in enumerate(sparse_rows):
        fused_scores[row.id] = fused_scores.get(row.id, 0.0) + 1.0 / (RRF_K + rank + 1)
        row_by_id[row.id] = row

    ranked_ids = sorted(fused_scores, key=lambda cid: fused_scores[cid], reverse=True)[:top_k]
    return [
        SearchResult(
            chunk_id=cid, document_id=row_by_id[cid].document_id,
            chunk_text=row_by_id[cid].chunk_text, page_number=row_by_id[cid].page_number,
            score=fused_scores[cid],
        )
        for cid in ranked_ids
    ]
