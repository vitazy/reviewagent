from pathlib import Path

import pytest

from schedule_agent.context import RuntimeContext
from schedule_agent.schemas import CaseSpec
from schedule_agent.storage import seed_db


@pytest.fixture
def ctx_factory(tmp_path):
    serial = 0

    def make(name="normal", case=None):
        nonlocal serial
        serial += 1
        case = case or CaseSpec.model_validate_json(Path(f"examples/cases/{name}.json").read_text())
        db = tmp_path / f"case_{serial}.db"
        seed_db(db, case.fixture)
        return RuntimeContext(case.request, db_path=db, preset_answers=case.preset_answers)
    return make
