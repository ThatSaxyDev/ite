"""Build structured composer choices from registered command argument forms."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ArgumentChoice:
    label: str
    tokens: tuple[str, ...]
    description: str
    runnable: bool = False
    children: list[ArgumentChoice] = field(default_factory=list)


def argument_choices(variants: tuple[tuple[str, str], ...]) -> list[ArgumentChoice]:
    """Read the catalog's usage grammar, never its prose descriptions.

    Literal tokens form a tree. Required placeholders remain display-only;
    optional enumerations become children, and optional free input stays editable.
    """
    roots: list[ArgumentChoice] = []
    for usage, description in variants:
        siblings = roots
        prefix: tuple[str, ...] = ()
        node: ArgumentChoice | None = None
        for token in usage.split():
            if token.startswith("<"):
                if node is None:
                    siblings.append(ArgumentChoice(usage, (), description))
                else:
                    node.description = description + f" Requires {token}."
                break
            if token.startswith("["):
                if node is not None:
                    node.runnable = True
                    node.description = description
                    values = token[1:-1].split("|")
                    if len(values) > 1 and all(not value.startswith("<") for value in values):
                        for value in values:
                            node.children.append(ArgumentChoice(value, (*prefix, value), description, True))
                break
            prefix = (*prefix, token)
            found = next((choice for choice in siblings if choice.label == token), None)
            if found is None:
                found = ArgumentChoice(token, prefix, description)
                siblings.append(found)
            node = found
            siblings = node.children
        else:
            if node is not None:
                node.runnable = True
                node.description = description
    return roots
