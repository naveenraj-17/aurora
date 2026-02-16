#!/usr/bin/env python3
"""
Test script for the time.py tool to validate date logic
This simulates tool calls without needing the MCP server running
"""

from datetime import datetime, timedelta
import calendar
import zoneinfo

def simulate_get_datetime(
    timezone="UTC",
    days=None,
    weeks=None,
    months=None,
    weekday=None,
    date_param=None,
    month_param=None,
    year_param=None,
):
    """Simulates the logic from the time tool"""
    try:
        tz = zoneinfo.ZoneInfo(timezone)
        base_date = datetime.now(tz)
        target_date = base_date
        
        # 1. Handle days offset
        if days is not None:
            target_date += timedelta(days=days)
        
        # 2. Handle WEEKS + WEEKDAY combination (weeks first, then weekday)
        if weeks is not None:
            target_date += timedelta(weeks=weeks)
        
        # 3. Handle MONTHS + DATE combination (months first, then date)
        if months is not None:
            year = target_date.year
            month = target_date.month + months
            
            # Normalize month and year
            while month > 12:
                month -= 12
                year += 1
            while month < 1:
                month += 12
                year -= 1
            
            # Handle day overflow (e.g., Jan 30 + 1 month -> Feb 30 invalid)
            last_day = calendar.monthrange(year, month)[1]
            day = min(target_date.day, last_day)
            target_date = target_date.replace(year=year, month=month, day=day)
            
            # If date parameter exists with months, set to that specific date
            if date_param is not None and '/' not in str(date_param):
                try:
                    day = int(date_param)
                    last_day = calendar.monthrange(year, month)[1]
                    if 1 <= day <= last_day:
                        target_date = target_date.replace(day=day)
                except (ValueError, TypeError):
                    pass
        
        # 4. Handle MONTH (name) + DATE + optional YEAR
        if month_param is not None:
            month_names = ['january', 'february', 'march', 'april', 'may', 'june',
                          'july', 'august', 'september', 'october', 'november', 'december']
            month_lower = month_param.lower().strip()
            
            if month_lower in month_names:
                target_month = month_names.index(month_lower) + 1
                target_year = year_param if year_param is not None else base_date.year
                
                # Get day from date parameter or keep current day
                if date_param is not None and '/' not in str(date_param):
                    try:
                        target_day = int(date_param)
                    except (ValueError, TypeError):
                        target_day = target_date.day
                else:
                    target_day = target_date.day
                
                # Validate and clamp day
                last_day = calendar.monthrange(target_year, target_month)[1]
                target_day = min(target_day, last_day)
                
                # Create candidate date
                candidate = base_date.replace(year=target_year, month=target_month, day=target_day)
                
                # If no year specified and date has passed, use next year
                if year_param is None and candidate.date() < base_date.date():
                    candidate = candidate.replace(year=target_year + 1)
                
                target_date = candidate
        
        # 5. Handle WEEKDAY (after weeks offset if applicable)
        if weekday is not None:
            weekday_lower = weekday.lower().strip()
            weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            
            if weekday_lower not in weekdays:
                return {"error": f"Invalid weekday '{weekday}'. Must be one of {weekdays}"}
            
            current_weekday = target_date.weekday()  # Mon=0, Sun=6
            target_weekday = weekdays.index(weekday_lower)
            
            days_ahead = target_weekday - current_weekday
            
            # If weeks was specified, we're already in the target week
            if weeks is not None:
                if days_ahead < 0:
                    days_ahead += 7
            else:
                if days_ahead <= 0:
                    days_ahead += 7
            
            target_date += timedelta(days=days_ahead)
        
        # Convert to 10-digit Unix timestamp
        unix_timestamp = int(target_date.timestamp())
        
        return {
            "timestamp": unix_timestamp,
            "datetime": target_date.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "timezone": timezone,
            "iso_format": target_date.isoformat()
        }
    except Exception as e:
        return {"error": str(e)}


def test_cases():
    """Run test cases"""
    print("=" * 80)
    print("TIME TOOL TEST CASES")
    print(f"Current time: {datetime.now()}")
    print("=" * 80)
    
    tests = [
        {
            "name": "Test 1: Tomorrow",
            "args": {"days": 1},
            "expected": "tomorrow's date"
        },
        {
            "name": "Test 2: Next Friday (weeks + weekday)",
            "args": {"weeks": 1, "weekday": "friday"},
            "expected": "Friday of next week"
        },
        {
            "name": "Test 3: 16th next month (months + date)",
            "args": {"months": 1, "date_param": "16"},
            "expected": "16th of next month"
        },
        {
            "name": "Test 4: April 15 (month + date)",
            "args": {"month_param": "april", "date_param": 15},
            "expected": "April 15 of current or next year"
        },
        {
            "name": "Test 5: April 15, 2027 (month + date + year)",
            "args": {"month_param": "april", "date_param": 15, "year_param": 2027},
            "expected": "April 15, 2027"
        },
        {
            "name": "Test 6: In 2 weeks on Monday",
            "args": {"weeks": 2, "weekday": "monday"},
            "expected": "Monday 2 weeks from now"
        },
        {
            "name": "Test 7: Next Monday (just weekday)",
            "args": {"weekday": "monday"},
            "expected": "Next Monday"
        },
        {
            "name": "Test 8: Current timestamp",
            "args": {},
            "expected": "Current time"
        },
    ]
    
    for test in tests:
        print(f"\n{test['name']}")
        print(f"Arguments: {test['args']}")
        print(f"Expected: {test['expected']}")
        result = simulate_get_datetime(**test['args'])
        if "error" in result:
            print(f"❌ ERROR: {result['error']}")
        else:
            print(f"✅ Timestamp: {result['timestamp']}")
            print(f"   DateTime: {result['datetime']}")
            print(f"   ISO: {result['iso_format']}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    test_cases()
