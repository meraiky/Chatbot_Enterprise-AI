from app.services import topic_guard_service

def test_check_topic_guard_blocked(mock_db):
    """Test that a restricted topic is correctly blocked."""
    # Setup mock DB to return a blocking rule
    mock_db.fetchall.return_value = [
        ("salary", "Salary information is confidential", False)
    ]
    
    blocked, reason = topic_guard_service.check_topic_guard("What is the average salary?", "Internal")
    assert blocked is True
    assert reason == "Salary information is confidential"

def test_check_topic_guard_allowed(mock_db):
    """Test that a non-restricted topic is allowed."""
    # Setup mock DB to return a rule that doesn't match
    mock_db.fetchall.return_value = [
        ("salary", "Salary information is confidential", False)
    ]
    
    blocked, reason = topic_guard_service.check_topic_guard("How to apply for leave?", "Internal")
    assert blocked is False
    assert reason is None

def test_check_topic_guard_regex_blocked(mock_db):
    """Test that a regex pattern correctly blocks a topic."""
    # Setup mock DB to return a regex rule
    mock_db.fetchall.return_value = [
        (r"password\s*is\s*\w+", "Do not ask for passwords", True)
    ]
    
    blocked, reason = topic_guard_service.check_topic_guard("My password is 12345", "Internal")
    assert blocked is True
    assert reason == "Do not ask for passwords"

def test_check_topic_guard_db_error_fails_closed(mock_db):
    """Test that the service fails-closed on database errors by default."""
    mock_db.execute.side_effect = Exception("DB Connection Error")

    blocked, reason = topic_guard_service.check_topic_guard("Any question", "Internal")
    assert blocked is True
    assert reason == "Policy guard temporarily unavailable. Please try again later."


def test_check_topic_guard_db_error_can_fail_open(mock_db, monkeypatch):
    mock_db.execute.side_effect = Exception("DB Connection Error")
    monkeypatch.setattr(topic_guard_service.settings, "TOPIC_GUARD_FAIL_CLOSED", False)

    blocked, reason = topic_guard_service.check_topic_guard("Any question", "Internal")
    assert blocked is False
    assert reason is None
