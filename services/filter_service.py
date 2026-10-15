from models import Filter, FilterHit
from datetime import datetime
from dataclasses import dataclass

@dataclass
class FilterResult:
    is_filtered: bool
    matched_filters: list[Filter]

class FilterService:
    def __init__(self, filter_factory):
        self.filter_factory = filter_factory

    def check_item(self, item, alert) -> FilterResult:
        filters = alert.filters
        matched_filters = []
        
        for db_filter in filters:
            filter_instance = self.filter_factory.create(db_filter)
            item_matches_filter = filter_instance.match(item.title)
            
            is_hit = (item_matches_filter and not db_filter.inverse) or (not item_matches_filter and db_filter.inverse)
            
            if is_hit:
                db_filter.matches += 1
                db_filter.save()
                matched_filters.append(db_filter)
        
        if matched_filters:
            for matched_filter in matched_filters:
                FilterHit.create(
                    item=item.id,
                    filter=matched_filter.id,
                    matched_at=datetime.now()
                )
            
        return FilterResult(len(matched_filters) > 0, matched_filters)
