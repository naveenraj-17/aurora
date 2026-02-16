# Time Tool Documentation

## Overview

The `get_datetime` tool converts natural language date/time requests into 10-digit Unix timestamps. It handles complex date combinations including relative dates (next week, next month) and absolute dates (April 15, 2027).

## Tool Name
`get_datetime`

## Response Format

The tool returns a JSON object with:
- **timestamp** (integer): 10-digit Unix timestamp
- **datetime** (string): Human-readable format (YYYY-MM-DD HH:MM:SS TZ)
- **timezone** (string): The timezone used
- **iso_format** (string): ISO 8601 format

Example response:
```json
{
  "timestamp": 1740067800,
  "datetime": "2026-02-20 21:00:00 IST",
  "timezone": "Asia/Kolkata",
  "iso_format": "2026-02-20T21:00:00+05:30"
}
```

## Parameters

All parameters are optional. If no parameters are provided, returns the current timestamp.

| Parameter | Type | Description |
|-----------|------|-------------|
| `timezone` | string | Timezone (default: "UTC"). Examples: "UTC", "America/New_York", "Asia/Kolkata" |
| `days` | integer | Add N days to current date |
| `weeks` | integer | Add N weeks. If combined with weekday, weeks offset is applied FIRST |
| `months` | integer | Add N months. If combined with date, month offset is applied FIRST |
| `weekday` | string | Target weekday (monday-sunday). If weeks provided, finds this weekday in that week |
| `date` | string | Day of month (1-31) or dd/mm format |
| `month` | string | Month name (january-december) |
| `year` | integer | Specific year (e.g., 2027) |

## Logic Rules

### 1. WEEKS + WEEKDAY
**Rule**: Apply weeks offset FIRST, then find the weekday from that week.

**Example**: "next friday"
```json
{
  "weeks": 1,
  "weekday": "friday"
}
```
**Logic**: 
1. Advance 1 week from today
2. Find Friday in that week

---

### 2. MONTHS + DATE (numeric)
**Rule**: Complete month offset FIRST, then take the date from that month.

**Example**: "16th next month"
```json
{
  "months": 1,
  "date": "16"
}
```
**Logic**:
1. Advance 1 month
2. Go to the 16th of that month

---

### 3. MONTH (name) + DATE
**Rule**: Go to that month and date in the CURRENT year. If already passed, use NEXT year.

**Example**: "April 15"
```json
{
  "month": "april",
  "date": 15
}
```
**Logic**:
1. Check if April 15 has passed this year
2. If yes, use April 15 of next year
3. If no, use April 15 of current year

---

### 4. MONTH + DATE + YEAR
**Rule**: Find that exact month and date in the specified year.

**Example**: "April 15, 2027"
```json
{
  "month": "april",
  "date": 15,
  "year": 2027
}
```
**Logic**: Go to April 15, 2027 (absolute date)

---

## Usage Examples

### Example 1: Tomorrow
**Request**: "Get timestamp for tomorrow"

**Tool Call**:
```json
{
  "tool_name": "get_datetime",
  "arguments": {
    "days": 1
  }
}
```

**Expected Response**:
```json
{
  "timestamp": 1739991090,
  "datetime": "2026-02-14 21:11:30 UTC",
  "timezone": "UTC",
  "iso_format": "2026-02-14T21:11:30+00:00"
}
```

---

### Example 2: Next Friday
**Request**: "What's the timestamp for next Friday?"

**Tool Call**:
```json
{
  "tool_name": "get_datetime",
  "arguments": {
    "weeks": 1,
    "weekday": "friday"
  }
}
```

**Logic Flow**:
1. Add 1 week to today (Feb 13, 2026) → Feb 20, 2026
2. Find Friday in that week → Feb 20, 2026 (already Friday)

---

### Example 3: 16th Next Month
**Request**: "Give me the timestamp for the 16th of next month"

**Tool Call**:
```json
{
  "tool_name": "get_datetime",
  "arguments": {
    "months": 1,
    "date": "16"
  }
}
```

**Logic Flow**:
1. Today is Feb 13, 2026
2. Add 1 month → March 2026
3. Go to 16th → March 16, 2026

---

### Example 4: April 15
**Request**: "When is April 15?"

**Tool Call**:
```json
{
  "tool_name": "get_datetime",
  "arguments": {
    "month": "april",
    "date": 15
  }
}
```

**Logic Flow**:
1. Today is Feb 13, 2026
2. Check April 15, 2026 (hasn't passed yet)
3. Return April 15, 2026

**If today was May 1, 2026**:
1. Check April 15, 2026 (already passed)
2. Return April 15, 2027

---

### Example 5: April 15, 2027
**Request**: "Get me the timestamp for April 15, 2027"

**Tool Call**:
```json
{
  "tool_name": "get_datetime",
  "arguments": {
    "month": "april",
    "date": 15,
    "year": 2027
  }
}
```

**Logic Flow**: Direct lookup → April 15, 2027

---

### Example 6: In 2 Weeks on Monday
**Request**: "What's the timestamp for Monday in 2 weeks?"

**Tool Call**:
```json
{
  "tool_name": "get_datetime",
  "arguments": {
    "weeks": 2,
    "weekday": "monday"
  }
}
```

**Logic Flow**:
1. Today is Feb 13, 2026 (Friday)
2. Add 2 weeks → Feb 27, 2026 (Friday)
3. Find Monday in that week → March 2, 2026 (Monday)

---

### Example 7: With Timezone
**Request**: "What's tomorrow's timestamp in New York timezone?"

**Tool Call**:
```json
{
  "tool_name": "get_datetime",
  "arguments": {
    "days": 1,
    "timezone": "America/New_York"
  }
}
```

---

### Example 8: Legacy dd/mm Format
**Request**: "Get timestamp for 25/12 (Christmas)"

**Tool Call**:
```json
{
  "tool_name": "get_datetime",
  "arguments": {
    "date": "25/12"
  }
}
```

**Logic Flow**:
1. Parse as December 25
2. If Dec 25 of current year has passed, use next year
3. Otherwise use current year

---

## Common Patterns

### Relative Dates
```json
// Tomorrow
{"days": 1}

// Next week
{"weeks": 1}

// Next month
{"months": 1}

// In 3 days
{"days": 3}
```

### Specific Weekdays
```json
// Next Monday (from today's perspective)
{"weekday": "monday"}

// Friday next week
{"weeks": 1, "weekday": "friday"}

// Monday in 2 weeks
{"weeks": 2, "weekday": "monday"}
```

### Specific Dates
```json
// 15th next month
{"months": 1, "date": "15"}

// April 15 (this year or next)
{"month": "april", "date": 15}

// April 15, 2027 (absolute)
{"month": "april", "date": 15, "year": 2027}
```

---

## Error Handling

The tool returns error messages in JSON format:

```json
{
  "error": "Error message here"
}
```

**Common Errors**:
- Invalid weekday: Must be monday-sunday
- Invalid date format: dd/mm expected
- Invalid month name: Must be january-december
- Invalid timezone: Timezone not found

---

## Integration Notes

1. **Always use the timestamp field** for database storage and comparisons
2. **Use datetime field** for display purposes
3. **Check for error field** before processing the response
4. The tool maintains timezone awareness throughout calculations
5. All timestamps are in seconds (10 digits), not milliseconds

---

## Migration from FastMCP

**Before** (fastMCP):
- Tool returned a formatted string
- No timestamp in response
- Less detailed documentation

**After** (Standard MCP):
- Tool returns JSON object
- Includes 10-digit Unix timestamp
- Multiple output formats (timestamp, datetime, ISO)
- Comprehensive parameter documentation with examples
- Clear logic rules for parameter combinations
