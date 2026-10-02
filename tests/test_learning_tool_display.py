from io import StringIO
from pathlib import Path

from rich.console import Console

from ite.ui.reup.tool_views import render_args_table
from ite.ui.tool_narrative import (
    activity_title,
    describe_tool_activity,
    progress_label,
    tool_icon,
)


def test_learning_tool_has_readable_titles_and_activity():
    assert activity_title("learn_progress") == "Saving your learning step"
    assert (
        activity_title("learn_progress", stage="complete", success=True)
        == "Learning step saved"
    )
    assert (
        activity_title("learn_progress", stage="complete", success=False)
        == "Could not save learning step"
    )
    assert (
        describe_tool_activity("learn_progress")
        == "Saving your learning goal and next step."
    )
    assert (
        describe_tool_activity("learn_progress", stage="complete", success=True)
        == "Saved your learning goal and next step."
    )
    assert "Could not save" in describe_tool_activity(
        "learn_progress", stage="complete", success=False
    )
    assert progress_label(tool_name="learn_progress") == "Saving your learning step"
    assert tool_icon("learn_progress") == "📘"


def test_learning_details_use_goal_and_next_step_without_internal_field_names():
    output = StringIO()
    console = Console(file=output, width=80, color_system=None)
    console.print(
        render_args_table(
            "learn_progress",
            {
                "current_step": "Try the empty input case.",
                "objective": "Learn validation.",
            },
            cwd=Path.cwd(),
        )
    )
    rendered = output.getvalue()
    assert "Goal" in rendered
    assert "Next step" in rendered
    assert "Learn validation." in rendered
    assert "Try the empty input case." in rendered
    assert "current_step" not in rendered
    assert "objective" not in rendered
