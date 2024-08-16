class ItemFilter:
    def __init__(self) -> None:
        pass

    def match(self, item) -> bool:
        raise NotImplementedError("This method should be overridden in child classes.")