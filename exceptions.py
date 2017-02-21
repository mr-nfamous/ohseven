
class Base(Exception):
  def __init__(self, *args, **kwargs):
    super().__init__(self.msg.format(*args, **kwargs))
    
class ItemPropertyIsReadOnlyError(Base):
  msg = 'attribute {attr!r} is read-only'
