from dataclasses import dataclass, field

import gradio as gr


@dataclass
class RunSelection:
    choices: list[str] = field(default_factory=list)
    selected: list[str] = field(default_factory=list)
    locked: bool = False

    def update_choices(
        self, runs: list[str], preferred: list[str] | None = None
    ) -> bool:
        if self.choices == runs:
            return False
        new_choices = set(runs) - set(self.choices)
        self.choices = list(runs)
        if self.locked:
            base = set(self.selected) | new_choices
        elif preferred:
            print("preferred", preferred)
            base = set(preferred)
        else:
            base = set(runs) 
        self.selected = [run for run in self.choices if run in base]
        return True

    def select(self, runs: list[str]) -> list[str]:
        print("select", runs)
        choice_set = set(self.choices)
        self.selected = [run for run in runs if run in choice_set]
        self.locked = True
        return self.selected

    def replace_group(
        self, group_runs: list[str], new_subset: list[str] | None
    ) -> tuple[list[str], list[str]]:
        print("replace_group", group_runs, new_subset)
        new_subset = ordered_subset(group_runs, new_subset)
        selection_set = set(self.selected)
        selection_set.difference_update(group_runs)
        selection_set.update(new_subset)
        self.selected = [run for run in self.choices if run in selection_set]
        self.locked = True
        return new_subset, self.selected


def ordered_subset(items: list[str], subset: list[str] | None) -> list[str]:
    subset_set = set(subset or [])
    return [item for item in items if item in subset_set]


def get_selected_runs(selection: RunSelection | list[str] | None) -> list[str]:
    if isinstance(selection, RunSelection):
        return list(selection.selected)
    return list(selection or [])


def run_checkbox_update(selection: RunSelection, **kwargs) -> gr.CheckboxGroup:
    return gr.CheckboxGroup(
        choices=selection.choices,
        value=selection.selected,
        **kwargs,
    )


def handle_run_checkbox_change(
    selected_runs: list[str] | None, selection: RunSelection
) -> RunSelection:
    selection.select(selected_runs or [])
    return selection


def handle_group_checkbox_change(
    group_selected: list[str] | None,
    selection: RunSelection,
    group_runs: list[str] | None,
):
    subset, _ = selection.replace_group(group_runs or [], group_selected or [])
    return (
        selection,
        gr.CheckboxGroup(value=subset),
        run_checkbox_update(selection),
    )


def handle_group_toggle(
    select_all: bool,
    selection: RunSelection,
    group_runs: list[str] | None,
):
    target = list(group_runs or []) if select_all else []
    subset, _ = selection.replace_group(group_runs or [], target)
    return (
        selection,
        gr.CheckboxGroup(value=subset),
        run_checkbox_update(selection),
    )
