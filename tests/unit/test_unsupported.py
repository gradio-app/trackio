import pytest

import trackio

UNSUPPORTED_CLASSES = (
    "ArtifactTTL",
    "Classes",
    "Config",
    "EvalTable",
    "Graph",
    "JoinedTable",
    "Molecule",
    "Plotly",
    "Settings",
)


@pytest.mark.parametrize("name", UNSUPPORTED_CLASSES)
@pytest.mark.parametrize(
    "args, kwargs",
    [
        ((), {}),
        (("value",), {}),
        ((), {"option": "value"}),
        (("value", None), {"option": "value"}),
    ],
)
def test_unsupported_class_instantiation(name, args, kwargs):
    cls = getattr(trackio, name)

    assert isinstance(cls, type)
    with pytest.raises(NotImplementedError) as exc_info:
        cls(*args, **kwargs)

    message = str(exc_info.value)
    assert f"trackio.{name} is not implemented" in message
    assert "If you need this feature, please open a GitHub issue" in message
    assert "https://github.com/gradio-app/trackio/issues/new" in message


def test_unsupported_classes_are_publicly_importable():
    namespace = {}
    exec("from trackio import " + ", ".join(UNSUPPORTED_CLASSES), namespace)
    star_namespace = {}
    exec("from trackio import *", star_namespace)

    for name in UNSUPPORTED_CLASSES:
        assert namespace[name] is getattr(trackio, name)
        assert star_namespace[name] is getattr(trackio, name)
