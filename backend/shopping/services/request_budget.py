"""Per-request network budget, propagated explicitly to research worker threads."""
from contextlib import contextmanager
from contextvars import ContextVar,copy_context
import time

deadline=ContextVar('shopping_network_deadline',default=None)
class BudgetExceeded(Exception):pass

def check():
    end=deadline.get()
    if end is not None and end-time.monotonic()<=.05:raise BudgetExceeded()

def http_timeout(connect,read):
    end=deadline.get()
    if end is None:return (connect,read)
    check();remaining=end-time.monotonic()
    c=min(connect,remaining*.35)
    return (max(.01,c),max(.01,min(read,remaining-c)))

@contextmanager
def within(end):
    token=deadline.set(end)
    try:yield
    finally:deadline.reset(token)

def submit(pool,fn,*args):return pool.submit(copy_context().run,fn,*args)
