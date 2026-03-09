from __future__ import annotations

from gradio_client import Client


class RemoteClient:
    def __init__(self, space: str, hf_token: str | None = None):
        self._space = space
        kwargs: dict = {"verbose": False}
        if hf_token:
            kwargs["hf_token"] = hf_token
        try:
            self._client = Client(space, **kwargs)
        except Exception as e:
            raise ConnectionError(
                f"Could not connect to Space '{space}'. Is it running?\n{e}"
            )

    def predict(self, *args, api_name: str):
        try:
            return self._client.predict(*args, api_name=api_name)
        except Exception as e:
            if "API Not Found" in str(e) or "api_name" in str(e):
                raise RuntimeError(
                    f"Space '{self._space}' does not support '{api_name}'. "
                    "Redeploy with `trackio sync`."
                )
            raise
