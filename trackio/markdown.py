class Markdown:
    """
    Markdown report data type for Trackio.

    Args:
        text (`str`):
            Markdown content to log.
    """

    TYPE = "trackio.markdown"

    def __init__(self, text: str = ""):
        if not isinstance(text, str):
            raise ValueError("Markdown text must be a string")
        self.text = text

    def _to_dict(self) -> dict:
        return {
            "_type": self.TYPE,
            "_value": self.text,
        }
