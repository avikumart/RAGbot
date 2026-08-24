from app.retrieval import identify_people, reformulate_query, hybrid_retrieve
from app.store import Chunk, Store


def test_identify_people_with_explicit_and_direct_names():
    known_people = [
        {"name": "Jordan Lee", "normalized": "jordan lee"},
        {"name": "Maya Patel", "normalized": "maya patel"},
    ]
    # Explicit override
    assert identify_people("What is their role?", known_people, explicit="Jordan Lee") == ["Jordan Lee"]

    # Direct full name in question
    assert identify_people("What does Maya Patel review?", known_people) == ["Maya Patel"]

    # First name match
    assert identify_people("What does Jordan own?", known_people) == ["Jordan Lee"]


def test_identify_people_resolves_from_conversational_history():
    known_people = [
        {"name": "Jordan Lee", "normalized": "jordan lee"},
        {"name": "Maya Patel", "normalized": "maya patel"},
    ]
    history = [
        {"role": "user", "content": "What does Jordan Lee own?"},
        {"role": "assistant", "content": "Jordan Lee leads the Phoenix migration and owns the rollout plan [1]."},
    ]

    # Follow-up question with pronoun resolves to Jordan Lee from history
    assert identify_people("When did they join the company?", known_people, history=history) == ["Jordan Lee"]
    assert identify_people("Who was his manager?", known_people, history=history) == ["Jordan Lee"]

    # If new question names a different person, that new person is identified
    assert identify_people("What about Maya Patel?", known_people, history=history) == ["Maya Patel"]


def test_reformulate_query_pronoun_anaphora_resolution():
    known_people = [
        {"name": "Jordan Lee", "normalized": "jordan lee"},
    ]
    history = [
        {"role": "user", "content": "What does Jordan Lee own?"},
        {"role": "assistant", "content": "Jordan Lee leads the Phoenix migration [1]."},
    ]

    query, people = reformulate_query(
        "When did they join the rollout?",
        history=history,
        known_people=known_people,
    )
    assert people == ["Jordan Lee"]
    assert "Jordan Lee" in query
    assert "When did they join the rollout?" in query


def test_reformulate_query_short_followup():
    known_people = [
        {"name": "Jordan Lee", "normalized": "jordan lee"},
    ]
    history = [
        {"role": "user", "content": "What projects does Jordan Lee manage?"},
        {"role": "assistant", "content": "Jordan Lee manages the database migration [1]."},
    ]

    query, people = reformulate_query(
        "What else?",
        history=history,
        known_people=known_people,
    )
    assert people == ["Jordan Lee"]
    assert "Jordan Lee" in query
    assert "What else?" in query


def test_reformulate_query_independent_question_preserves_standalone():
    known_people = [
        {"name": "Jordan Lee", "normalized": "jordan lee"},
        {"name": "Maya Patel", "normalized": "maya patel"},
    ]
    history = [
        {"role": "user", "content": "What does Jordan Lee own?"},
        {"role": "assistant", "content": "Jordan Lee leads the Phoenix migration [1]."},
    ]

    query, people = reformulate_query(
        "What does Maya Patel review?",
        history=history,
        known_people=known_people,
    )
    assert people == ["Maya Patel"]
    assert query == "What does Maya Patel review?"


def test_hybrid_retrieve_multi_turn_pronoun_resolution(tmp_path):
    store = Store(tmp_path)
    store.initialize()

    path = store.upload_dir / "team.txt"
    path.write_text("team")
    store.add_document(
        document_id="team",
        filename="team.txt",
        content_type="text/plain",
        stored_path=path,
        digest="digest",
        size_bytes=4,
        chunks=[
            Chunk(0, None, "Jordan Lee owns the rollout plan for Phoenix.", ("Jordan Lee",)),
            Chunk(1, None, "Jordan Lee joined the engineering initiative in March 2023.", ("Jordan Lee",)),
            Chunk(2, None, "Maya Patel coordinates security and access review.", ("Maya Patel",)),
        ],
        people={"Jordan Lee": 2, "Maya Patel": 1},
    )

    history = [
        {"role": "user", "content": "What does Jordan Lee own?"},
        {"role": "assistant", "content": "Jordan Lee owns the rollout plan for Phoenix [1]."},
    ]

    # Follow-up: "When did they join the initiative?"
    people, sources, mode = hybrid_retrieve(
        store,
        "When did they join the initiative?",
        document_ids=["team"],
        explicit_person=None,
        top_k=2,
        history=history,
    )

    assert people == ["Jordan Lee"]
    assert len(sources) > 0
    # Top source excerpt should mention joining in March 2023
    assert "March 2023" in sources[0]["excerpt"]
