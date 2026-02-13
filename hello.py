import datetime

def get_birthday():
    """Get user's birthday and return it as a datetime object."""
    while True:
        try:
            birthday_str = input("Enter your birthday (MM/DD/YYYY): ")
            birthday = datetime.datetime.strptime(birthday_str, "%m/%d/%Y")
            return birthday
        except ValueError:
            print("Invalid date format. Please use MM/DD/YYYY.")

def main():
    """Main function to get and display user's birthday."""
    print("Birthday Input Program")
    print("=" * 20)
    
    birthday = get_birthday()
    
    # Display the birthday
    print(f"\nYour birthday is: {birthday.strftime('%B %d, %Y')}")
    print(f"Day of the week: {birthday.strftime('%A')}")
    
    # Calculate age
    today = datetime.date.today()
    age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
    print(f"You are {age} years old.")

if __name__ == "__main__":
    main()