import json
from pathlib import Path

import pytest

import zelf

FIXTURES = json.loads((Path(__file__).parents[2] / "fixtures" / "fixtures.json").read_text())
CASES = [
    (name, case, document)
    for name, cases in FIXTURES["reports"].items()
    for case, document in cases.items()
]


@pytest.mark.parametrize(("name", "case", "document"), CASES)
def test_report_decodes_softly(name, case, document):
    report = getattr(zelf, name).model_validate_json(json.dumps(document))
    assert report.model_dump(exclude_unset=True, by_alias=True) == document


def test_decimal_in_a_whole_number_field_is_kept():
    document = FIXTURES["reports"]["AdvancedAiAnalysisReport"]["decimals"]
    report = zelf.AdvancedAiAnalysisReport.model_validate(document)
    assert report.summary.videos == 12.6
    assert report.top_creators[0].posts == 12.6


def test_whole_numbers_stay_int():
    report = zelf.AdvancedAiAnalysisReport.model_validate({"summary": {"videos": 42}})
    assert report.summary.videos == 42
    assert type(report.summary.videos) is int


def test_missing_and_null_read_as_none():
    report = zelf.CreatorVettingReport.model_validate({"violations": None})
    assert report.profile_summary is None
    assert report.top_themes is None
    assert report.violations is None
