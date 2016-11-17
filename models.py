from google.appengine.ext import ndb


class Algorithm(ndb.Model):
    author = ndb.UserProperty()
    name = ndb.StringProperty()
    category = ndb.StringProperty(indexed=False)
    script = ndb.StringProperty(indexed=False)
    viz = ndb.StringProperty(indexed=False)
    date = ndb.DateTimeProperty(auto_now=True)
    public = ndb.BooleanProperty()
    events = ndb.StringProperty(indexed=False)


class Log(ndb.Model):
    author = ndb.UserProperty()
    msg = ndb.StringProperty(indexed=False)
    date = ndb.DateTimeProperty(auto_now=True)


class Comment(ndb.Model):
    author = ndb.UserProperty()
    name = ndb.StringProperty()
    content = ndb.TextProperty()
    date = ndb.DateTimeProperty(auto_now=True)
    
