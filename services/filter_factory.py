from models import Filter as DbFilter
from filters.text_filter import TextFilter
from filters.re_filter import RegexFilter

class FilterFactory:
    def create(self, db_filter: DbFilter):
        """
        Creates a runtime filter instance (TextFilter or RegexFilter)
        based on the provided database filter configuration.
        """
        filter_type = db_filter.type
        filter_value = db_filter.value

        if filter_type == "text":
            # TextFilter expects a list of search terms
            return TextFilter([filter_value])
        elif filter_type == "regex":
            # RegexFilter expects a list of regex patterns
            return RegexFilter([filter_value])
        else:
            # Potentially log an error or raise a more specific/handled exception
            raise ValueError(f"Unknown filter type encountered: {filter_type}") 