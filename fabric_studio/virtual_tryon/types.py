"""Provider-neutral request/response types.

Nothing in these types is FASHN-specific: `mode` is "fast" or "quality", not a
model name, and the result carries a generic status. That is what makes the
self-hosted VTON 1.5 swap a provider change rather than an application change.
"""


class TryOnRequest(object):
    """Inputs for one try-on generation.

    person_image / garment_image accept an https URL or a base64 data URI.
    garment_metadata describes the garment for providers that can use it
    (category, fabric colours, pattern, a styling prompt); providers ignore
    what they cannot use.
    """

    def __init__(self, person_image, garment_image, garment_metadata=None,
                 options=None, request_id=None):
        self.person_image = person_image
        self.garment_image = garment_image
        self.garment_metadata = dict(garment_metadata or {})
        self.options = dict(options or {})
        self.request_id = request_id

    @property
    def mode(self):
        """'fast' (cheap, default) or 'quality'."""
        return self.options.get("mode") or "fast"

    @property
    def strategy(self):
        """How the garment reaches the model.

        'composite' (default) sends the outfit template filled with the chosen
        fabric as one flat-lay; 'fabric' sends the bare swatch and describes the
        garment in the prompt; 'template' is the composite on the cheap legacy
        model; 'edit' sends the person with the fabric as visual context.
        """
        return self.options.get("strategy") or "composite"

    @property
    def category(self):
        """tops | bottoms | one-pieces — how much of the body to replace."""
        return self.garment_metadata.get("category") or "one-pieces"

    @property
    def prompt(self):
        return (self.options.get("prompt") or "").strip()

    def summary(self):
        return {
            "mode": self.mode,
            "strategy": self.strategy,
            "category": self.category,
            "hasPrompt": bool(self.prompt),
            "requestId": self.request_id,
        }


class GarmentRemakeRequest(object):
    """Inputs for step one: remake a garment in a different fabric.

        fabric image + garment reference  ->  the same garment, new cloth

    The garment reference may be a flat-lay or a photo of someone wearing the
    outfit; the engine keeps the cut and replaces the material. The result is
    a garment image, not a try-on, and is cached by the caller so a fabric and
    garment pairing is only ever remade once.
    """

    def __init__(self, garment_image, fabric_image, prompt=None, options=None, request_id=None):
        self.garment_image = garment_image
        self.fabric_image = fabric_image
        self.prompt = (prompt or "").strip()
        self.options = dict(options or {})
        self.request_id = request_id

    @property
    def mode(self):
        return self.options.get("mode") or "fast"

    def summary(self):
        return {
            "mode": self.mode,
            "hasPrompt": bool(self.prompt),
            "requestId": self.request_id,
        }


# Terminal and non-terminal statuses used across every provider.
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
TERMINAL_STATUSES = (STATUS_COMPLETED, STATUS_FAILED)


class TryOnResult(object):
    def __init__(self, status, provider, generation_id=None, result_image=None,
                 metadata=None, error=None, error_code=None):
        self.status = status
        self.provider = provider
        self.generation_id = generation_id
        self.result_image = result_image
        self.metadata = dict(metadata or {})
        self.error = error
        self.error_code = error_code

    @property
    def is_terminal(self):
        return self.status in TERMINAL_STATUSES

    @property
    def succeeded(self):
        return self.status == STATUS_COMPLETED and bool(self.result_image)

    def to_dict(self):
        return {
            "status": self.status,
            "resultImage": self.result_image,
            "generationId": self.generation_id,
            "provider": self.provider,
            "metadata": self.metadata,
            "error": self.error,
            "errorCode": self.error_code,
        }

    def __repr__(self):  # pragma: no cover - debugging aid
        return "<TryOnResult %s %s %s>" % (self.provider, self.status, self.generation_id)
