import datetime, bday_messages
today = datetime.date.today()
next_birthday = datetime.date(int(input("Enter the year of your next birthday (YYYY): ")),
                              int(input("Enter the month of your next birthday (MM): ")),
                              int(input("Enter the day of your next birthday (DD): ")))
days_away = next_birthday - today
if today == next_birthday:
    print(bday_messages.random_message)
else:
    print(f"My next birthday is in {days_away.days} days!")