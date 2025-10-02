from dataclasses import dataclass, field

try:
    import trackio.utils as utils
except ImportError:
    import utils


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
            base = set(preferred)
        else:
            base = set(runs)
        self.selected = [run for run in self.choices if run in base]
        return True

    def select(self, runs: list[str]) -> list[str]:
        choice_set = set(self.choices)
        self.selected = [run for run in runs if run in choice_set]
        self.locked = True
        return self.selected

    def replace_group(
        self, group_runs: list[str], new_subset: list[str] | None
    ) -> tuple[list[str], list[str]]:
        new_subset = utils.ordered_subset(group_runs, new_subset)
        selection_set = set(self.selected)
        selection_set.difference_update(group_runs)
        selection_set.update(new_subset)
        self.selected = [run for run in self.choices if run in selection_set]
        self.locked = True
        return new_subset, self.selected
