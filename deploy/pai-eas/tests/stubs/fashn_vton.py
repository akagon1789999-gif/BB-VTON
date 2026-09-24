"""Stub pipeline that records the kwargs it was handed."""
from PIL import Image
CALLS = []
class _Result:
    def __init__(self, images): self.images = images
class TryOnPipeline:
    def __init__(self, weights_dir, device=None):
        self.weights_dir, self.device = weights_dir, device
    def __call__(self, **kwargs):
        CALLS.append(kwargs)
        n = kwargs.get("num_samples", 1)
        return _Result([Image.new("RGB", (64, 96), (10 * i + 5, 80, 160)) for i in range(n)])
