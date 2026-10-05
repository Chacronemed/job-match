"""Written numbers shared by the experience parser and the funding extractor."""

WORD_NUMBERS: dict[str, float] = {
    "un": 1, "une": 1, "one": 1,
    "deux": 2, "two": 2,
    "trois": 3, "three": 3,
    "quatre": 4, "four": 4,
    "cinq": 5, "five": 5,
    "six": 6,
    "sept": 7, "seven": 7,
    "huit": 8, "eight": 8,
    "neuf": 9, "nine": 9,
    "dix": 10, "ten": 10,
}


def word_to_number(word: str) -> float | None:
    return WORD_NUMBERS.get(word.lower())
