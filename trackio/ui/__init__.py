def __getattr__(name: str):
    if name == "demo":
        import trackio.ui.main as ui_main

        return ui_main.demo
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["demo"]
