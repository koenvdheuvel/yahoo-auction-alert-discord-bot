from peewee import Model, CharField, TextField, DeferredForeignKey, ForeignKeyField, SmallIntegerField, IntegerField, BigIntegerField, BooleanField, DateTimeField, SqliteDatabase
from datetime import datetime
from typing import Optional
import os

# Define the database connection
database = SqliteDatabase(os.getenv('DATABASE_URL', 'alerts.db'))

# BaseModel to connect to the Peewee database
class BaseModel(Model):
    class Meta:
        database = database

# Define your models
class Alert(BaseModel):
    channel_id = BigIntegerField(index=True)
    search_query = CharField(unique=True)

class Item(BaseModel):
    item_id = CharField(unique=True)
    checker = CharField(null=True)
    title = TextField(null=True)
    stock = SmallIntegerField(default=0)
    price = IntegerField(default=0)
    buyout_price = IntegerField(default=0)
    message_id = BigIntegerField(unique=True, null=True)
    muted = BooleanField(default=False)
    found_at = DateTimeField(default=datetime.now, null=True)
    updated_at = DateTimeField(default=datetime.now, null=True)
    alert = ForeignKeyField(Alert, backref='items', null=True)

    def blacklisted(self, channel_id) -> bool:
        return Blacklist.select().where(Blacklist.item == self, Blacklist.channel_id == channel_id).exists()

class Blacklist(BaseModel):
    item = ForeignKeyField(Item, backref='blacklists')
    channel_id = BigIntegerField(index=True)

class Notification(BaseModel):
    item = ForeignKeyField(Item, backref='notifications')
    user_id = CharField(index=True)

class Filter(BaseModel):
    alert = ForeignKeyField(Alert, backref='filters')
    type = CharField()
    value = CharField()
    inverse = BooleanField(default=False)
    matches = IntegerField(default=0)

# simple utility function to create tables
def create_tables():
    with database:
        database.create_tables([Alert, Item, Blacklist, Notification, Filter])