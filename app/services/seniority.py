"""
Определение уровня квалификации (seniority) по опыту и названию вакансии.
"""

from enum import IntEnum
import re


class SeniorityLevel(IntEnum):
    UNKNOWN = 0
    JUNIOR = 1
    MIDDLE = 2
    SENIOR = 3
    LEAD = 4


_SENIORITY_PATTERNS: dict[SeniorityLevel, re.Pattern] = {
    # Full-word patterns use \b on both sides; prefix patterns (ведущ, руководител, начинающ)
    # use only a leading \b — the word continues past the matched prefix.
    SeniorityLevel.JUNIOR: re.compile(
        r"\b(junior|младший|intern|стажёр|стажер|entry.level)\b|\bначинающ",
        re.IGNORECASE,
    ),
    SeniorityLevel.MIDDLE: re.compile(
        r"\b(middle|средний|middle\+|мидл)\b",
        re.IGNORECASE,
    ),
    SeniorityLevel.SENIOR: re.compile(
        r"\b(senior|старший|expert|эксперт|principal)\b|\bведущ",
        re.IGNORECASE,
    ),
    SeniorityLevel.LEAD: re.compile(
        r"\b(lead|глава|head|chief|team.lead|тех.лид|tech.lead)\b|\bруководител",
        re.IGNORECASE,
    ),
}


def detect_seniority_from_experience(experience_years: str | None) -> SeniorityLevel:
    if not experience_years:
        return SeniorityLevel.UNKNOWN
    match = re.match(r"(\d+)\s*г", experience_years)
    if not match:
        return SeniorityLevel.UNKNOWN
    years = int(match.group(1))
    if years < 2:
        return SeniorityLevel.JUNIOR
    if years < 4:
        return SeniorityLevel.MIDDLE
    if years < 7:
        return SeniorityLevel.SENIOR
    return SeniorityLevel.LEAD


def detect_seniority_from_title(title: str) -> SeniorityLevel:
    if not title:
        return SeniorityLevel.UNKNOWN
    for level, pattern in _SENIORITY_PATTERNS.items():
        if pattern.search(title):
            return level
    return SeniorityLevel.UNKNOWN


def is_seniority_compatible(
    candidate_level: SeniorityLevel,
    vacancy_level: SeniorityLevel,
) -> bool:
    if candidate_level == SeniorityLevel.UNKNOWN or vacancy_level == SeniorityLevel.UNKNOWN:
        return True
    return abs(candidate_level - vacancy_level) <= 1
