import re

class RegexFilter:
    def __init__(self, patterns: list):
        self.pattersn = patterns = [re.compile(pattern) for pattern in patterns]
    
    def match(self, input_text: str) -> bool:
        for pattern in self.patterns:
            if pattern.search(input_text):
                return True
        return False
            