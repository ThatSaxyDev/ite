print("Hello, World! I changed it")
birthday = input("Enter your birthday (MM/DD/YYYY): ")
print(f"Your birthday is: {birthday}")

def print_even_numbers(n):
    """Print even numbers between 1 and n."""
    evens = [str(i) for i in range(2, n + 1, 2)]
    if evens:
        print(f"Even numbers between 1 and {n}: {', '.join(evens)}")