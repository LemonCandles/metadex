import pytest

from app.core.errors import DataError, MetadexError, PermanentError, RecoverableError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("error_type", [RecoverableError, DataError, PermanentError])
def test_error_categories_share_a_stable_base(error_type: type[MetadexError]) -> None:
    assert isinstance(error_type("example"), MetadexError)
