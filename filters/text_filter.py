class TextFilter:
    def __init__(self, search_terms: list):
        self.search_terms = search_terms

    def match(self, input_text: str) -> bool:
        return any(term in input_text for term in self.search_terms)
