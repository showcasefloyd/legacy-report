from unittest.mock import patch
from legacy_report import comicvine


def test_get_issues_for_volume_returns_structured_dict():
    fake_response = {
        "results": [
            {"id": 1, "issue_number": "1", "name": "First Issue",
             "cover_date": "1963-03-01", "person_credits": [], "image": {}}
        ],
        "number_of_total_results": 342,
        "offset": 0,
        "limit": 100,
    }
    with patch("legacy_report.comicvine._fetch", return_value=fake_response):
        result = comicvine.get_issues_for_volume("123")

    assert result["total"] == 342
    assert result["offset"] == 0
    assert result["limit"] == 100
    assert len(result["results"]) == 1
    assert result["results"][0]["issue_number"] == "1"


def test_get_issues_for_volume_passes_offset_to_fetch():
    fake_response = {
        "results": [],
        "number_of_total_results": 342,
        "offset": 100,
        "limit": 100,
    }
    with patch("legacy_report.comicvine._fetch", return_value=fake_response) as mock_fetch:
        comicvine.get_issues_for_volume("123", offset=100)

    _, call_params = mock_fetch.call_args[0]
    assert call_params["offset"] == 100
    assert call_params["limit"] == 100
