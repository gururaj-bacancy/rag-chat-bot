from sqlalchemy import text

from app.db.models import Chunk, Document
from app.retrieval.hybrid_search import SearchResult, hybrid_search


def _make_embedding(hot_index: int, dim: int = 1024) -> list[float]:
    vec = [0.0] * dim
    vec[hot_index] = 1.0
    return vec


def _populate_search_vectors(session, document_id: int) -> None:
    session.execute(text(
        "UPDATE chunks SET search_vector = to_tsvector('english', chunk_text) "
        "WHERE document_id = :doc_id"
    ), {"doc_id": document_id})
    session.commit()


def test_hybrid_search_ranks_matching_chunk_first(db_session):
    document = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    db_session.add(document)
    db_session.commit()

    room_rent_chunk = Chunk(
        document_id=document.id,
        chunk_text="Room rent is capped at one percent of the sum insured per day.",
        contextual_text="Room rent is capped at one percent of the sum insured per day.",
        page_number=1,
        embedding=_make_embedding(0),
    )
    copay_chunk = Chunk(
        document_id=document.id,
        chunk_text="The co-payment percentage applicable for senior citizens is ten percent.",
        contextual_text="The co-payment percentage applicable for senior citizens is ten percent.",
        page_number=2,
        embedding=_make_embedding(1023),
    )
    db_session.add_all([room_rent_chunk, copay_chunk])
    db_session.commit()

    _populate_search_vectors(db_session, document.id)

    query_embedding = _make_embedding(0)
    results = hybrid_search(
        db_session,
        query_text="room rent capped sum insured",
        query_embedding=query_embedding,
        top_k=8,
    )

    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    assert results[0].chunk_id == room_rent_chunk.id
    assert results[0].document_id == document.id
    assert results[0].chunk_text == room_rent_chunk.chunk_text
    assert results[0].page_number == 1
    assert results[0].score > results[1].score
    assert results[1].chunk_id == copay_chunk.id


def test_hybrid_search_respects_top_k(db_session):
    document = Document(doc_type="policy", filename="policy2.pdf", status="indexed")
    db_session.add(document)
    db_session.commit()

    chunks = []
    for i in range(5):
        chunk = Chunk(
            document_id=document.id,
            chunk_text=f"Clause number {i} about hospital cash benefit coverage.",
            contextual_text=f"Clause number {i} about hospital cash benefit coverage.",
            page_number=i + 1,
            embedding=_make_embedding(i),
        )
        chunks.append(chunk)
    db_session.add_all(chunks)
    db_session.commit()

    _populate_search_vectors(db_session, document.id)

    results = hybrid_search(
        db_session,
        query_text="hospital cash benefit coverage",
        query_embedding=_make_embedding(0),
        top_k=2,
    )

    assert len(results) == 2
