import pytest
from app.temporal_extraction import (
    extract_dates_from_sentence,
    parse_date_sort_key,
    extract_timeline_events,
)


def test_parse_date_sort_key_chronological_order():
    dates = [
        "2023",
        "January 2021",
        "2018-2022",
        "March 15, 2020",
        "1995",
        "Fall 2021",
        "2021-05-12",
        "Q3 2022",
    ]
    sorted_dates = sorted(dates, key=parse_date_sort_key)
    expected = [
        "1995",
        "2018-2022",
        "March 15, 2020",
        "January 2021",
        "2021-05-12",
        "Fall 2021",
        "Q3 2022",
        "2023",
    ]
    assert sorted_dates == expected


def test_extract_dates_patterns():
    # Year range
    assert "2018-2022" in extract_dates_from_sentence("Maya Patel was at Stanford during 2018-2022.")
    # Month Year
    assert "September 2020" in extract_dates_from_sentence("In September 2020, Robert joined Acme Corp.")
    # Month Day, Year
    assert "July 4, 2019" in extract_dates_from_sentence("The announcement was made on July 4, 2019.")
    # Contextual Year
    assert "2015" in extract_dates_from_sentence("Acme Corp was founded in 2015.")
    # Season Year
    assert "Spring 2021" in extract_dates_from_sentence("She delivered the keynote in Spring 2021.")


def test_extract_timeline_events_people_and_organizations():
    text = (
        "Maya Patel graduated from Stanford University in 2018. "
        "In September 2020, Maya joined Acme Corp as Principal AI Architect. "
        "Acme Corp acquired DataWave in 2022. "
        "Robert Smith partnered with Maya Patel in 2023 to publish a new benchmark."
    )
    events = extract_timeline_events(text, known_people={"Maya Patel", "Robert Smith"})

    # Chronologically sorted
    dates = [ev.event_date for ev in events]
    sort_keys = [parse_date_sort_key(d) for d in dates]
    assert sort_keys == sorted(sort_keys)

    # People milestones
    maya_events = [ev for ev in events if ev.entity_name == "Maya Patel"]
    assert len(maya_events) >= 3
    assert any("2018" in ev.event_date for ev in maya_events)
    assert any("September 2020" in ev.event_date for ev in maya_events)
    assert any("2023" in ev.event_date for ev in maya_events)

    # Organization milestones
    acme_events = [ev for ev in events if ev.entity_name == "Acme Corp"]
    assert len(acme_events) >= 2
    assert any("September 2020" in ev.event_date for ev in acme_events)
    assert any("2022" in ev.event_date for ev in acme_events)


def test_extract_timeline_events_empty_and_no_dates():
    assert extract_timeline_events("") == []
    assert extract_timeline_events("Maya Patel is a software engineer with no dates mentioned.") == []


def test_extract_dates_various_formats():
    assert "2015 to 2019" in extract_dates_from_sentence("He served as Director from 2015 to 2019.")
    assert "2020-08-25" in extract_dates_from_sentence("The filing date was 2020-08-25.")
    assert "Jan. 2022" in extract_dates_from_sentence("Effective Jan. 2022, she took over as CEO.")
    assert "Q2 2021" in extract_dates_from_sentence("Revenue doubled in Q2 2021.")


def test_extract_timeline_events_deduplication():
    text = (
        "In 2020, Alice founded TechCorp. "
        "In 2020, Alice founded TechCorp."
    )
    events = extract_timeline_events(text, known_people={"Alice"})
    assert len(events) == 2  # One for Alice, one for TechCorp

