import os


def colab_check() -> bool:
    is_colab = False
    try:
        from IPython.core.getipython import get_ipython  # noqa: PLC0415

        from_ipynb = get_ipython()
        if "google.colab" in str(from_ipynb):
            is_colab = True
    except (ImportError, NameError):
        pass
    return is_colab


def is_hosted_notebook() -> bool:
    return bool(
        os.environ.get("KAGGLE_KERNEL_RUN_TYPE")
        or os.path.exists("/home/ec2-user/SageMaker")
    )


def ipython_check() -> bool:
    is_ipython = False
    try:
        from IPython.core.getipython import get_ipython  # noqa: PLC0415

        if get_ipython() is not None:
            is_ipython = True
    except (ImportError, NameError):
        pass
    return is_ipython
