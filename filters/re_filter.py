import re


class RegexFilter:
    """Compiled regular expressions shared by repeated matches."""
    def __init__(self, patterns: list):
        self.patterns = [re.compile(pattern) for pattern in patterns]

    def match(self, input_text: str) -> bool:
        return any(pattern.search(input_text) for pattern in self.patterns)
