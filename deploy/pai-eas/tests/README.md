# Local checks, no GPU required

`test_app.py` exercises the FastAPI layer with `torch` and `fashn_vton` stubbed
(`stubs/`), so routing, the pydantic ceilings and the SSRF guard are all
verifiable on a laptop or in CI before anything reaches a GPU node.

```bash
python3 -m venv venv && ./venv/bin/pip install \
    fastapi==0.115.6 pydantic==2.10.4 httpx==0.28.1 python-multipart==0.0.20 pillow
./venv/bin/python test_app.py
```

It does not test the model. Inference correctness needs the real weights on a
CUDA device -- run `examples/basic_inference.py` from the upstream repo for that.
