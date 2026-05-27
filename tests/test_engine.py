"""Engine protocol: abstract, requires drive(), returns a TaskResult (R2)."""

from __future__ import annotations

import pytest

from convertible.config import EngineConfig
from convertible.contract import OK, Task, TaskResult
from convertible.engine import Engine


def test_engine_is_abstract() -> None:
    with pytest.raises(TypeError):
        Engine()  # type: ignore[abstract]


def test_subclass_missing_drive_cannot_instantiate() -> None:
    class Broken(Engine):
        name = "broken"

    with pytest.raises(TypeError):
        Broken()  # type: ignore[abstract]


def test_concrete_subclass_drives() -> None:
    class Tiny(Engine):
        name = "tiny"

        def drive(self, task: Task, config: EngineConfig) -> TaskResult:
            return TaskResult(task_id=task.id, status=OK, summary="ok")

    engine = Tiny()
    result = engine.drive(Task.new("/repo", "do it"), EngineConfig.resolve())
    assert isinstance(result, TaskResult)
    assert result.status == OK
