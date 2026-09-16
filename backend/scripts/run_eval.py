"""Run a small golden set of questions against the ingested sample claim and
report whether each answer contains the expected figure/keyword. Requires
sample documents already ingested (see Task 21) and real API keys set."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.session import get_engine, get_session
from app.config import settings
from app.agent.chat import stream_agent_response

GOLDEN_SET = [
    ("What is my room rent limit per day?", "5,000"),
    ("Why was my claim approved for less than I claimed?", "room rent"),
    ("Is my settlement amount correct according to my policy?", "75,937"),
]

def main():
    get_engine(settings.database_url)
    session = get_session()
    passed = 0
    for question, expected_fragment in GOLDEN_SET:
        answer = "".join(stream_agent_response(session, [], question))
        ok = expected_fragment.lower() in answer.lower()
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {question}\n  -> {answer[:200]}\n")
    print(f"{passed}/{len(GOLDEN_SET)} passed")
    session.close()

if __name__ == "__main__":
    main()
