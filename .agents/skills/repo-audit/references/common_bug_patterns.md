# Common Bug Patterns by Language

Bug patterns and anti-patterns specific to each programming language.

## Python

### Mutable Default Arguments

**The bug:**
```python
def append_to_list(value, my_list=[]):
    my_list.append(value)
    return my_list

# Problem: Same list is shared across calls
print(append_to_list(1))  # [1]
print(append_to_list(2))  # [1, 2] - unexpected!
```

**The fix:**
```python
def append_to_list(value, my_list=None):
    if my_list is None:
        my_list = []
    my_list.append(value)
    return my_list
```

### Bare Except Clauses

**The bug:**
```python
try:
    do_something()
except:
    pass  # Catches KeyboardInterrupt, SystemExit too!
```

**The fix:**
```python
try:
    do_something()
except SpecificException as e:
    handle_error(e)
```

### Resource Leaks

**The bug:**
```python
f = open("file.txt", "r")
data = f.read()
# File never closed if exception occurs
```

**The fix:**
```python
with open("file.txt", "r") as f:
    data = f.read()
# File always closed
```

### Late Binding in Closures

**The bug:**
```python
functions = []
for i in range(3):
    functions.append(lambda: i)

for f in functions:
    print(f())  # Prints 2, 2, 2 not 0, 1, 2
```

**The fix:**
```python
functions = []
for i in range(3):
    functions.append(lambda i=i: i)  # Capture current value
```

### Is vs ==

**The bug:**
```python
if x is "hello":  # Works sometimes, fails sometimes
    pass
```

**The fix:**
```python
if x == "hello":  # Correct string comparison
    pass
```

## JavaScript/TypeScript

### Loose Equality (== vs ===)

**The bug:**
```javascript
0 == "0"   // true
0 == []    // true
"" == false // true
[] == ![]   // true (wat?!)
```

**The fix:**
```javascript
0 === "0"   // false
0 === []    // false
"" === false // false
```

### this Binding

**The bug:**
```javascript
class Counter {
    count = 0;
    increment() {
        this.count++;
    }
}

const c = new Counter();
const button = document.getElementById('btn');
button.addEventListener('click', c.increment);  // 'this' is button, not Counter!
```

**The fix:**
```javascript
button.addEventListener('click', c.increment.bind(c));
// Or use arrow function
button.addEventListener('click', () => c.increment());
// Or define as arrow function in class
increment = () => { this.count++; }
```

### Variable Hoisting

**The bug:**
```javascript
function example() {
    console.log(x);  // undefined, not ReferenceError
    var x = 5;
}
```

**The fix:**
```javascript
function example() {
    const x = 5;  // or let
    console.log(x);  // 5
}
```

### Async/Await Error Handling

**The bug:**
```javascript
async function fetchData() {
    const response = fetch("/api/data");  // Missing await!
    const data = await response.json();  // Runtime error
}
```

**The fix:**
```javascript
async function fetchData() {
    const response = await fetch("/api/data");
    if (!response.ok) throw new Error("Request failed");
    const data = await response.json();
}
```

### Array Mutation Methods

**The bug:**
```javascript
const items = ["a", "b", "c"];
const index = items.indexOf("a");
if (index) {  // 0 is falsy!
    items.splice(index, 1);
}
```

**The fix:**
```javascript
if (index !== -1) {  // Explicit check
    items.splice(index, 1);
}
```

## Go

### Error Checking

**The bug:**
```go
f, _ := os.Open("file.txt")  // Error ignored!
data, _ := io.ReadAll(f)
```

**The fix:**
```go
f, err := os.Open("file.txt")
if err != nil {
    return fmt.Errorf("open failed: %w", err)
}
defer f.Close()
data, err := io.ReadAll(f)
if err != nil {
    return err
}
```

### Goroutine Leaks

**The bug:**
```go
func process(items []int) {
    for _, item := range items {
        go func() {
            fmt.Println(item)  // All see same value!
        }()
    }
}
```

**The fix:**
```go
func process(items []int) {
    for _, item := range items {
        go func(i int) {
            fmt.Println(i)
        }(item)  // Pass value to goroutine
    }
}
```

### Map Concurrency

**The bug:**
```go
counter := make(map[string]int)
var wg sync.WaitGroup

for i := 0; i < 100; i++ {
    wg.Add(1)
    go func() {
        counter["x"]++  // Data race!
        wg.Done()
    }()
}
wg.Wait()
```

**The fix:**
```go
var counter sync.Map
var wg sync.WaitGroup

for i := 0; i < 100; i++ {
    wg.Add(1)
    go func() {
        counter.Store("x", 0)
        val, _ := counter.Load("x")
        counter.Store("x", val.(int)+1)
        wg.Done()
    }()
}
wg.Wait()
```

### String/Bytes Confusion

**The bug:**
```go
s := "hello"
b := []byte(s)
s[0] = 'j'  // Compile error: strings are immutable
```

**The fix:**
```go
s := []byte("hello")
s[0] = 'j'
fmt.Println(string(s))  // "jello"
```

## General Patterns

### Race Conditions

**The bug:**
Any code where multiple threads access shared mutable state without synchronization.

**The fix:**
- Use atomic operations for simple counters
- Use mutexes for protecting critical sections
- Prefer immutable data structures
- Use channels (Go) or message passing

### Off-by-One Errors

**The bug:**
```python
for i in range(len(items)):  # Often wrong
    # ...
```

**The fix:**
- Prefer direct iteration: `for item in items:`
- Know your bounds: `range(len(items) - 1)` or `range(1, len(items))`
- Use enumerate when you need index: `for i, item in enumerate(items)`

### Null/Undefined Checks

**The bug:**
```javascript
const name = user.profile.name.trim();  // Explodes if profile is null
```

**The fix:**
```javascript
const name = user?.profile?.name?.trim() ?? "Anonymous";
```

### Resource Exhaustion

**The bug:**
- Unbounded goroutines spawning
- Reading untrusted file sizes into memory
- No timeout on network calls
- Infinite recursion

**The fix:**
- Use worker pools and semaphores
- Validate and limit inputs
- Set timeouts on all I/O operations
- Add recursion depth limits
