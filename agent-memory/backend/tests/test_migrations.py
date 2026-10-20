"""Static checks on the Alembic migration chain (no database needed)."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_ROOT = Path(__file__).resolve().parents[2]

# alembic_version.version_num is VARCHAR(32); a longer revision id makes
# `alembic upgrade head` fail on PostgreSQL and rolls back the whole upgrade.
_MAX_REVISION_LEN = 32


def _script_dir() -> ScriptDirectory:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_revision_ids_fit_alembic_version_column() -> None:
    too_long = [
        rev.revision
        for rev in _script_dir().walk_revisions()
        if len(rev.revision) > _MAX_REVISION_LEN
    ]
    assert too_long == [], f"revision ids longer than {_MAX_REVISION_LEN} chars: {too_long}"


def test_single_head() -> None:
    assert len(_script_dir().get_heads()) == 1
