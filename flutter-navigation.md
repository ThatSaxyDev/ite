# Flutter Navigation Guide

Flutter offers two main approaches to navigation:
1. **GoRouter** (recommended) - declarative, path-based routing
2. **Navigator 2.0** - Flutter's built-in imperative navigation

This guide focuses on GoRouter as it's the modern standard.

---

## Installation

```bash
flutter pub add go_router
```

---

## 1. Basic Setup

```dart
// main.dart
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'screens/home_screen.dart';
import 'screens/details_screen.dart';

void main() => runApp(const MyApp());

final router = GoRouter(
  routes: [
    GoRoute(
      path: '/',
      builder: (context, state) => const HomeScreen(),
    ),
    GoRoute(
      path: '/details',
      builder: (context, state) => const DetailsScreen(),
    ),
  ],
);

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      routerConfig: router,
    );
  }
}
```

---

## 2. Navigating Between Screens

```dart
// Using context (recommended)
context.go('/details');

// Using the router directly
GoRouter.of(context).go('/details');

// With parameters
context.go('/details/123');

// Push (keeps history, allows going back)
context.push('/details');
```

---

## 3. Route Parameters

```dart
// Define routes with parameters
final router = GoRouter(
  routes: [
    GoRoute(
      path: '/user builder: (context/:id',
     , state) {
        final id = state.pathParameters['id']; // '123'
        return UserScreen(userId: id!);
      },
    ),
  ],
);

// Navigate with params
context.go('/user/123');

// Query parameters
// URL: /search?query=flutter&page=1
final query = state.uri.queryParameters['query']; // 'flutter'
final page = state.uri.queryParameters['page'];    // '1'
```

---

## 4. Passing Data via Extra

```dart
// Navigate with extra data
context.push('/details', extra: {'name': 'Item', 'price': 29.99});

// Receive in destination
final extra = state.extra as Map<String, dynamic>;
```

---

## 5. Shell Route (Persistent UI)

Use `ShellRoute` to keep a bottom nav bar while navigating.

```dart
final router = GoRouter(
  routes: [
    ShellRoute(
      builder: (context, state, child) => MainShell(child: child),
      routes: [
        GoRoute(path: '/', builder: (_, __) => const HomeTab()),
        GoRoute(path: '/search', builder: (_, __) => const SearchTab()),
        GoRoute(path: '/profile', builder: (_, __) => const ProfileTab()),
      ],
    ),
  ],
);

class MainShell extends StatelessWidget {
  final Widget child;
  const MainShell({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: child,
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _calculateIndex(context),
        onTap: (index) => _onItemTapped(index, context),
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home), label: 'Home'),
          BottomNavigationBarItem(icon: Icon(Icons.search), label: 'Search'),
          BottomNavigationBarItem(icon: Icon(Icons.person), label: 'Profile'),
        ],
      ),
    );
  }

  int _calculateIndex(BuildContext context) {
    final location = GoRouterState.of(context).uri.path;
    if (location.startsWith('/search')) return 1;
    if (location.startsWith('/profile')) return 2;
    return 0;
  }

  void _onItemTapped(int index, BuildContext context) {
    switch (index) {
      case 0: context.go('/'); break;
      case 1: context.go('/search'); break;
      case 2: context.go('/profile'); break;
    }
  }
}
```

---

## 6. Redirects & Guards

```dart
final router = GoRouter(
  redirect: (context, state) {
    final isLoggedIn = AuthService.isLoggedIn;
    final isLoggingIn = state.uri.path == '/login';

    // Not logged in? Redirect to login
    if (!isLoggedIn && !isLoggingIn) {
      return '/login';
    }

    // Logged in but on login page? Redirect to home
    if (isLoggedIn && isLoggingIn) {
      return '/';
    }

    return null; // Allow navigation
  },
);
```

---

## 7. Nested Routes

```dart
GoRoute(
  path: '/products',
  builder: (context, state) => const ProductsScreen(),
  routes: [
    GoRoute(
      path: ':id',
      builder: (context, state) {
        final id = state.pathParameters['id'];
        return ProductDetailScreen(productId: id!);
      },
    ),
  ],
),
```

---

## 8. Error Handling

```dart
final router = GoRouter(
  errorBuilder: (context, state) => NotFoundScreen(),
);
```

---

## 9. Named Routes (Optional)

```dart
// Define name
GoRoute(
  path: '/details',
  name: 'details',  // Add name
  builder: (_, __) => const DetailsScreen(),
)

// Navigate by name
context.namedLocation('details', pathParameters: {'id': '123'});
```

---

## 10. Type-Safe Routing (Recommended)

```dart
// Define route paths as constants
class AppRoutes {
  static const home = '/';
  static const details = '/details';
  static const user = '/user/:id';
}

// Typed navigation extension
extension GoRouterExtension on BuildContext {
  void goToDetails(int id) => go('/details/$id');
  void goToUser(String id) => go('/user/$id');
}

// Usage
context.goToDetails(123);
```

---

## Comparison: GoRouter vs Navigator 1.0

| Feature | GoRouter | Navigator 1.0 |
|---------|----------|---------------|
| Declarative | ✅ | ❌ |
| Deep linking | ✅ | Manual |
| Type safety | ✅ | Manual |
| Nested routes | ✅ | Limited |
| Web support | ✅ | ✅ |

---

## Summary

| Navigator | Use Case |
|-----------|----------|
| **Stack** (GoRoute) | Linear flow, drill-down into details |
| **ShellRoute + BottomNav** | Top-level sections with persistent nav |
| **Nested Routes** | Master-detail views |
| **Redirects** | Auth guards, conditional routing |

Install `go_router`, wrap your app in `MaterialApp.router`, and define routes with `GoRoute`.
