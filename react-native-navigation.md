# React Native Navigation Guide

React Navigation is the standard navigation library for React Native apps. It provides declarative routing with stack, tab, and drawer navigators.

---

## Installation

```bash
# Install core packages
npm install @react-navigation/native

# Install dependencies
npm install react-native-screens react-native-safe-area-context

# Install navigators
npm install @react-navigation/native-stack
npm install @react-navigation/bottom-tabs
npm install @react-navigation/drawer
```

---

## 1. Stack Navigator

Stack navigation provides a hierarchical, push/pop navigation pattern—ideal for screens that flow from one to another.

```tsx
// App.tsx
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import HomeScreen from './screens/HomeScreen';
import DetailsScreen from './screens/DetailsScreen';

const Stack = createNativeStackNavigator();

export default function App() {
  return (
    <NavigationContainer>
      <Stack.Navigator>
        <Stack.Screen 
          name="Home" 
          component={HomeScreen}
          options={{ title: 'My App' }}
        />
        <Stack.Screen 
          name="Details" 
          component={DetailsScreen}
          options={{ title: 'Details' }}
        />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
```

### Navigating Between Screens

```tsx
// HomeScreen.tsx
import { useNavigation } from '@react-navigation/native';
import { Button, View } from 'react-native';

export default function HomeScreen() {
  const navigation = useNavigation();

  return (
    <View>
      <Button
        title="Go to Details"
        onPress={() => navigation.navigate('Details', { id: 1, name: 'Item' })}
      />
    </View>
  );
}
```

### Receiving Parameters

```tsx
// DetailsScreen.tsx
import { useNavigation, useRoute } from '@react-navigation/native';

export default function DetailsScreen() {
  const route = useRoute();
  const { id, name } = route.params;

  return <Text>Item: {name} (ID: {id})</Text>;
}
```

---

## 2. Bottom Tab Navigator

Tab navigation displays a row of tabs at the bottom of the screen for quick access to top-level sections.

```tsx
// App.tsx
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import HomeScreen from './screens/HomeScreen';
import ProfileScreen from './screens/ProfileScreen';
import { Ionicons } from '@expo/vector-icons';

const Tab = createBottomTabNavigator();

export default function App() {
  return (
    <NavigationContainer>
      <Tab.Navigator
        screenOptions={({ route }) => ({
          tabBarIcon: ({ focused, color, size }) => {
            let iconName = route.name === 'Home' ? 'home' : 'person';
            return <Ionicons name={iconName} size={size} color={color} />;
          },
          tabBarActiveTintColor: 'tomato',
          tabBarInactiveTintColor: 'gray',
        })}
      >
        <Tab.Screen name="Home" component={HomeScreen} />
        <Tab.Screen name="Profile" component={ProfileScreen} />
      </Tab.Navigator>
    </NavigationContainer>
  );
}
```

---

## 3. Drawer Navigation

Drawer navigation provides a slide-out menu from the side of the screen.

```bash
npm install @react-navigation/drawer react-native-gesture-handler react-native-reanimated
```

```tsx
// App.tsx
import { NavigationContainer } from '@react-navigation/native';
import { createDrawerNavigator } from '@react-navigation/drawer';
import HomeScreen from './screens/HomeScreen';
import SettingsScreen from './screens/SettingsScreen';

const Drawer = createDrawerNavigator();

export default function App() {
  return (
    <NavigationContainer>
      <Drawer.Navigator>
        <Drawer.Screen name="Home" component={HomeScreen} />
        <Drawer.Screen name="Settings" component={SettingsScreen} />
      </Drawer.Navigator>
    </NavigationContainer>
  );
}
```

---

## 4. Nested Navigation

Combine navigators to create complex navigation structures.

```tsx
// App.tsx
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';

const Stack = createNativeStackNavigator();
const Tab = createBottomTabNavigator();

function TabNavigator() {
  return (
    <Tab.Navigator>
      <Tab.Screen name="Feed" component={FeedScreen} />
      <Tab.Screen name="Messages" component={MessagesScreen} />
    </Tab.Navigator>
  );
}

export default function App() {
  return (
    <NavigationContainer>
      <Stack.Navigator>
        <Stack.Screen name="Main" component={TabNavigator} />
        <Stack.Screen name="Profile" component={ProfileScreen} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
```

---

## 5. Navigation Props

Each screen receives these props automatically:

| Prop | Description |
|------|-------------|
| `navigation.navigate(name, params)` | Navigate to a route |
| `navigation.goBack()` | Go back one screen |
| `navigation.push(name, params)` | Add a new route on top |
| `navigation.pop()` | Pop the current screen |
| `navigation.replace(name, params)` | Replace current route |
| `navigation.setOptions(options)` | Update screen options |
| `route.params` | Parameters passed to the screen |

---

## 6. TypeScript Types

```tsx
import type { NativeStackScreenProps } from '@react-navigation/native-stack';

type RootStackParamList = {
  Home: undefined;
  Details: { id: number; name: string };
};

type Props = NativeStackScreenProps<RootStackParamList, 'Details'>;

export default function DetailsScreen({ route, navigation }: Props) {
  const { id, name } = route.params;
  return <Text>{name}</Text>;
}
```

---

## Summary

| Navigator | Use Case |
|-----------|----------|
| **Stack** | Linear flow, drill-down into details |
| **Bottom Tabs** | Top-level sections, persistent navigation |
| **Drawer** | Settings, menus, less-used sections |

Install the required packages, wrap your app in `<NavigationContainer>`, and use the appropriate navigator for your UI pattern.
