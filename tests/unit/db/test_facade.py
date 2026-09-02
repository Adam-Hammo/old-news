"""The two `__all__` lists that have to agree, `db` re-exporting `db.models` by hand."""

import old_news.db
import old_news.db.models


def test_the_facade_re_exports_every_model_name():
    """An explicit list, so a name added to `db.models` reaches `db` only if added twice."""
    assert set(old_news.db.models.__all__) <= set(old_news.db.__all__)


def test_every_exported_name_resolves():
    for module in (old_news.db, old_news.db.models):
        missing = [name for name in module.__all__ if not hasattr(module, name)]

        assert not missing, f"{module.__name__}.__all__ names {missing}, which it does not define"
