import lightbulb

class BaseCommand:
    def __init__(self, bot):
        self.bot = bot
        self.register()

    def register(self):
        raise NotImplementedError("This method should be overridden in child classes.")
