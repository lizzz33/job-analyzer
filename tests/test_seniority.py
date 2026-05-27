"""Tests for seniority detection and compatibility."""

import pytest

from app.services.seniority import (
    SeniorityLevel,
    detect_seniority_from_experience,
    detect_seniority_from_title,
    is_seniority_compatible,
)


class TestDetectFromExperience:
    @pytest.mark.parametrize(
        "exp, expected",
        [
            (None, SeniorityLevel.UNKNOWN),
            ("", SeniorityLevel.UNKNOWN),
            ("нет опыта", SeniorityLevel.UNKNOWN),
            ("1 г.", SeniorityLevel.JUNIOR),
            ("1 г. 6 мес.", SeniorityLevel.JUNIOR),
            ("3 г.", SeniorityLevel.MIDDLE),
            ("5 г. 0 мес.", SeniorityLevel.SENIOR),
            ("8 г.", SeniorityLevel.LEAD),
        ],
    )
    def test_experience_mapping(self, exp, expected):
        assert detect_seniority_from_experience(exp) == expected


class TestDetectFromTitle:
    @pytest.mark.parametrize(
        "title, expected",
        [
            ("", SeniorityLevel.UNKNOWN),
            ("Python Developer", SeniorityLevel.UNKNOWN),
            ("Junior Python Developer", SeniorityLevel.JUNIOR),
            ("Младший разработчик", SeniorityLevel.JUNIOR),
            ("Middle Backend Developer", SeniorityLevel.MIDDLE),
            ("Senior Data Engineer", SeniorityLevel.SENIOR),
            ("Ведущий программист", SeniorityLevel.SENIOR),
            ("Tech Lead", SeniorityLevel.LEAD),
            ("Руководитель отдела", SeniorityLevel.LEAD),
        ],
    )
    def test_title_detection(self, title, expected):
        assert detect_seniority_from_title(title) == expected


class TestCompatibility:
    @pytest.mark.parametrize(
        "candidate, vacancy, compatible",
        [
            (SeniorityLevel.JUNIOR, SeniorityLevel.JUNIOR, True),
            (SeniorityLevel.JUNIOR, SeniorityLevel.MIDDLE, True),
            (SeniorityLevel.JUNIOR, SeniorityLevel.SENIOR, False),
            (SeniorityLevel.MIDDLE, SeniorityLevel.SENIOR, True),
            (SeniorityLevel.SENIOR, SeniorityLevel.JUNIOR, False),
            (SeniorityLevel.LEAD, SeniorityLevel.SENIOR, True),
            (SeniorityLevel.UNKNOWN, SeniorityLevel.SENIOR, True),
            (SeniorityLevel.SENIOR, SeniorityLevel.UNKNOWN, True),
        ],
    )
    def test_compatibility(self, candidate, vacancy, compatible):
        assert is_seniority_compatible(candidate, vacancy) is compatible
