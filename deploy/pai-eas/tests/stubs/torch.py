"""Minimal torch stub: only what app.py touches."""
from contextlib import contextmanager
class _Cuda:
    @staticmethod
    def is_available(): return False
    @staticmethod
    def memory_allocated(): return 0
    @staticmethod
    def memory_reserved(): return 0
    @staticmethod
    def get_device_name(i=0): return "stub"
    @staticmethod
    def empty_cache(): pass
cuda = _Cuda()
@contextmanager
def inference_mode():
    yield
