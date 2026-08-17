"""Mock provider — the whole workflow, zero API credits.

Set VTON_PROVIDER=mock to develop and test the frontend, the pipeline, the
history and the admin tools without spending FASHN credits. The mock does not
pretend to do a try-on: it returns a clearly-labelled composite of the person
photo and the composed garment so the plumbing is visibly working.
"""
import time

from .. import imaging, storage
from .provider import VirtualTryOnProvider
from .types import STATUS_COMPLETED, STATUS_FAILED, TryOnResult


class MockProvider(VirtualTryOnProvider):
    name = "mock"
    supports_prompt = True

    def __init__(self):
        self._results = {}

    def is_configured(self):
        return True

    def generate(self, request):
        generation_id = "mock_%s" % storage.new_id("job").split("_")[1]
        try:
            image = self._compose(request)
            relative = "generations/mock-%s.jpg" % generation_id
            storage.write_media(relative, imaging.encode_image(image, "JPEG", 88))
            result = TryOnResult(
                status=STATUS_COMPLETED,
                provider=self.name,
                generation_id=generation_id,
                result_image=storage.media_url(relative),
                metadata={"model": "mock", "mode": request.mode, "creditsUsed": 0},
            )
        except Exception as exc:  # pragma: no cover - mock must never 500
            result = TryOnResult(
                status=STATUS_FAILED,
                provider=self.name,
                generation_id=generation_id,
                error="We couldn't generate your outfit this time. Please try again.",
                error_code="MockCompositionError",
                metadata={"detail": str(exc)},
            )
        self._results[generation_id] = result
        return result

    def get_status(self, generation_id):
        result = self._results.get(generation_id)
        if result is not None:
            return result
        # A restart loses the in-memory map; report a definite failure rather
        # than leaving the caller polling forever.
        return TryOnResult(
            status=STATUS_FAILED,
            provider=self.name,
            generation_id=generation_id,
            error="We couldn't generate your outfit this time. Please try again.",
            error_code="MockResultExpired",
        )

    def _compose(self, request):
        """Person photo on the left, composed garment on the right."""
        imaging.require_pillow()
        from PIL import ImageDraw

        person, _ = imaging.load_image(request.person_image)
        person = imaging.to_rgb(imaging.fit_within(person, 900))
        garment = self._load_garment(request)

        height = person.size[1]
        garment_width = int(height * 0.62)
        garment = garment.resize(
            (garment_width, int(garment_width * garment.size[1] / float(garment.size[0]))),
            imaging.Image.LANCZOS,
        )
        garment = imaging.fit_within(garment, height)

        canvas = imaging.Image.new("RGB", (person.size[0] + garment.size[0], height), (24, 23, 20))
        canvas.paste(person, (0, 0))
        canvas.paste(garment, (person.size[0], (height - garment.size[1]) // 2))

        draw = ImageDraw.Draw(canvas)
        draw.rectangle([0, 0, canvas.size[0], 34], fill=(201, 167, 105))
        draw.text((12, 11), "MOCK TRY-ON — no AI credits used (%s)" % time.strftime("%H:%M:%S"),
                  fill=(33, 26, 14))
        return canvas

    def _load_garment(self, request):
        garment = request.garment_image
        if isinstance(garment, str) and garment.startswith("data:"):
            image, _ = imaging.load_image(garment)
            return imaging.to_rgb(image)
        if isinstance(garment, str) and garment.startswith("/media/"):
            path = storage.media_path(garment[len("/media/"):])
            with imaging.Image.open(str(path)) as opened:
                return imaging.to_rgb(opened.copy())
        raise ValueError("Mock provider needs a data URL or a /media path, got %r" % (garment,)[:80])
