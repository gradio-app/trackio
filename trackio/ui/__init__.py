try:
    from trackio.ui.main import demo
    from trackio.ui.run_detail import run_detail_page
    from trackio.ui.runs import run_page
except ImportError:
    from ui.main import demo
    from ui.run_detail import run_detail_page
    from ui.runs import run_page

__all__ = ["demo", "run_page", "run_detail_page"]
