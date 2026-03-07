# React Native Project Setup Guide

This guide covers setting up a new React Native project for both iOS and Android development.

---

## Prerequisites

### For iOS (macOS required)

```bash
# Install Node.js (via nvm or homebrew)
brew install node

# Install Xcode from App Store
# Install Xcode Command Line Tools
xcode-select --install

# Install CocoaPods for iOS dependencies
sudo gem install cocoapods
```

### For Android

```bash
# Install Node.js
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
nvm install node

# Install Android Studio from https://developer.android.com/studio
# Install Android SDK via Android Studio SDK Manager

# Set environment variables
export ANDROID_HOME=$HOME/Library/Android/sdk
export PATH=$PATH:$ANDROID_HOME/emulator
export PATH=$PATH:$ANDROID_HOME/tools
export PATH=$PATH:$ANDROID_HOME/tools/bin
export PATH=$PATH:$ANDROID_HOME/platform-tools

# Add to ~/.zshrc or ~/.bash_profile for persistence
```

---

## Method 1: Expo CLI (Recommended for Beginners)

### Install Expo CLI

```bash
npm install -g expo-cli
```

### Create New Project

```bash
# Interactive creation
expo init MyNewApp

# Or with specific template
expo init MyNewApp --template blank

# TypeScript template
expo init MyNewApp --template blank-typescript

# Navigate to project
cd MyNewApp
```

### Install Expo Go App (Optional)

- **iOS**: Install "Expo Go" from App Store
- **Android**: Install "Expo Go" from Google Play Store

### Run the App

```bash
# Start development server
expo start

# Or with specific platform
expo start --ios
expo start --android
expo start --web

# Press '?' in terminal for available commands
```

### Project Structure

```
MyNewApp/
├── app.json          # Expo configuration
├── babel.config.js   # Babel configuration
├── package.json      # Dependencies and scripts
├── tsconfig.json     # TypeScript config (if using TS)
├── src/              # Your source code
│   ├── App.tsx       # Main app component
│   └── components/   # Reusable components
└── assets/           # Images, fonts, etc.
```

---

## Method 2: React Native CLI (For Advanced Users)

### Install React Native CLI

```bash
npm install -g react-native-cli
```

### Create New Project

```bash
# Create project
react-native init MyNewApp

# Navigate to project
cd MyNewApp
```

### Run the App

```bash
# iOS
cd ios
pod install
cd ..
npx react-native run-ios

# Android
npx react-native run-android
```

### Project Structure

```
MyNewApp/
├── android/          # Android native code
├── ios/              # iOS native code
├── src/              # Your React Native code
│   ├── App.js        # Main app component
│   └── components/   # Reusable components
├── package.json      # Dependencies and scripts
├── metro.config.js   # Metro bundler config
└── index.js          # Entry point
```

---

## Essential Dependencies

### UI Components

```bash
# React Native Elements (UI toolkit)
npm install react-native-elements

# React Native Paper (Material Design)
npm install react-native-paper

# UI Kitten (Eva Design System)
npm install @ui-kitten/components @eva-design/eva
```

### State Management

```bash
# Redux
npm install @reduxjs/toolkit react-redux

# Context API (built-in)
# No installation needed

# Zustand
npm install zustand
```

### HTTP Client

```bash
# Axios
npm install axios

# Fetch API (built-in)
# No installation needed
```

### Navigation (from previous doc)

```bash
npm install @react-navigation/native
npm install react-native-screens react-native-safe-area-context
npm install @react-navigation/native-stack
```

---

## Development Tools

### VS Code Extensions

- React Native Tools
- React Native Snippet
- ES7+ React/Redux/React-Native snippets
- Auto Rename Tag

### Debugging

```bash
# React Native Debugger (standalone)
# Download from https://github.com/jhen0409/react-native-debugger

# Chrome DevTools
# Press Cmd+D (iOS) or Cmd+M (Android) → Debug JS Remotely
```

### Linting and Formatting

```bash
# ESLint
npm install --save-dev eslint eslint-plugin-react-hooks

# Prettier
npm install --save-dev prettier eslint-config-prettier

# Add scripts to package.json
"scripts": {
  "lint": "eslint src/",
  "format": "prettier --write src/"
}
```

---

## iOS-Specific Setup

### Configure Bundle Identifier

Edit `ios/MyNewApp/Info.plist`:
```xml
<key>CFBundleIdentifier</key>
<string>com.yourcompany.mynewapp</string>
```

### Configure App Icon

Replace icons in `ios/MyNewApp/Assets.xcassets/AppIcon.appiconset/`

### Push Notifications

```bash
# Install react-native-push-notification
npm install react-native-push-notification
```

---

## Android-Specific Setup

### Configure Package Name

Edit `android/app/build.gradle`:
```gradle
defaultConfig {
    applicationId "com.yourcompany.mynewapp"
}
```

### Configure App Icon

Replace icons in `android/app/src/main/res/`

### Permissions

Edit `android/app/src/main/AndroidManifest.xml`:
```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
```

---

## Common Issues and Solutions

### Metro Bundler Issues

```bash
# Clear cache
npx react-native start --reset-cache

# Delete node_modules and reinstall
rm -rf node_modules package-lock.json
npm install
```

### iOS Build Issues

```bash
# Clean build
cd ios && xcodebuild clean -workspace MyNewApp.xcworkspace -scheme MyNewApp

# Reinstall pods
cd ios && pod deinstall && pod install
```

### Android Build Issues

```bash
# Clean Gradle cache
cd android && ./gradlew clean

# Reinstall dependencies
cd android && rm -rf .gradle && ./gradlew assembleDebug
```

### Connection Issues

```bash
# Ensure devices are connected
adb devices

# Restart Metro bundler
npx react-native start --port 8081
```

---

## Testing

### Unit Tests

```bash
# Jest (comes with React Native)
npm test

# React Native Testing Library
npm install --save-dev @testing-library/react-native
```

### E2E Tests

```bash
# Detox
npm install --save-dev detox

# Cypress React Native
npm install --save-dev cypress-react-native
```

---

## Deployment

### iOS

```bash
# Build for App Store
cd ios && xcodebuild -workspace MyNewApp.xcworkspace -scheme MyNewApp -configuration Release

# Upload to App Store Connect
# Use Xcode Organizer or Transporter
```

### Android

```bash
# Generate signed APK
cd android && ./gradlew assembleRelease

# Upload to Google Play Console
# Use Android Studio or command line tools
```

---

## Summary

| Method | Best For | Pros | Cons |
|--------|----------|------|------|
| **Expo CLI** | Beginners, quick prototyping | Easy setup, no native code, over-the-air updates | Limited native module access, larger app size |
| **React Native CLI** | Production apps, custom native modules | Full control, smaller app size | Complex setup, requires native knowledge |

Choose Expo for learning and quick projects, React Native CLI for production apps requiring custom native functionality.
