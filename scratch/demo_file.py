"""Demo module for testing tool card rendering in the chat feed.

This module intentionally contains several sections so that file edits
can be made in multiple places and observed in the UI.
"""


class Greeter:
    """A simple greeting utility with configurable punctuation."""

    def __init__(self, name: str = "world", punct: str = "!"):
        self.name = name
        self.punct = punct

    def greet(self) -> str:
        return f"Hello, {self.name}{self.punct}"


def add(a: int, b: int) -> int:
    return a + b


def subtract(a: int, b: int) -> int:
    return a - b


def multiply(a: int, b: int) -> int:
    return a * b


def power(base: int, exponent: int) -> int:
    return base**exponent


def divide(a: int, b: int) -> float:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


if __name__ == "__main__":
    greeter = Greeter("developer", punct="!")
    print(greeter.greet())
    print(add(2, 3))
    print(power(2, 10))
