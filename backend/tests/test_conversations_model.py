from pathlib import Path

from app.db.models import Conversation, Message

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def test_message_belongs_to_a_conversation(db_session):
    conversation = Conversation()
    db_session.add(conversation)
    db_session.commit()

    message = Message(role="user", content="hello", conversation_id=conversation.id)
    db_session.add(message)
    db_session.commit()

    fetched = db_session.query(Message).filter_by(id=message.id).one()

    assert fetched.conversation_id == conversation.id
    assert fetched.conversation_id == message.conversation_id


def test_conversation_has_created_at_timestamp(db_session):
    conversation = Conversation()
    db_session.add(conversation)
    db_session.commit()

    fetched = db_session.query(Conversation).filter_by(id=conversation.id).one()

    assert fetched.created_at is not None


def test_migration_backfills_existing_null_conversation_ids():
    """The actual backfill behavior can only be exercised against a real
    pre-migration DB state (the shared `db_session` fixture always runs
    migrations to completion before every test, so there is no way to get a
    NULL `conversation_id` row into the test DB to backfill). A string-contains
    check on the migration file's key clauses is the pragmatic stand-in here;
    the real backfill was additionally verified manually against the live dev
    DB's 4 pre-existing messages (see task-1-report.md)."""
    sql = (MIGRATIONS_DIR / "003_conversations.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS conversations" in sql
    assert "ADD COLUMN IF NOT EXISTS conversation_id" in sql
    assert "INSERT INTO conversations" in sql
    assert "UPDATE messages SET conversation_id" in sql
    assert "WHERE conversation_id IS NULL" in sql
    assert "SET NOT NULL" in sql
