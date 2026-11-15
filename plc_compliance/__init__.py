"""Industrial-control security baseline assessment starter project."""

__all__ = ["build_assessment_graph"]


def build_assessment_graph(*args, **kwargs):
    """Lazily import the graph so domain models work without runtime extras."""
    from plc_compliance.graph import build_assessment_graph as _build_assessment_graph

    return _build_assessment_graph(*args, **kwargs)
