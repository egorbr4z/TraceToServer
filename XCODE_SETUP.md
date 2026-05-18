# Xcode Project Setup

## Create New Project

1. Xcode → File → New → Project
2. **macOS → App**
3. Product Name: `TraceToServer`
4. Interface: SwiftUI
5. Language: Swift
6. Minimum Deployment: macOS 15.0

## Add Source Files

Delete the default `ContentView.swift` and drag all files from this folder into the project:

```
TraceToServer/
├── TraceToServerApp.swift
├── ContentView.swift
├── Models/
│   ├── Connection.swift
│   ├── GeoLocation.swift
│   └── Country.swift
├── Services/
│   ├── NetworkMonitor.swift
│   ├── GeoService.swift
│   └── CountryService.swift
└── Views/
    ├── WorldMapView.swift
    └── HUDPanel.swift
```

## Add GeoJSON Resource

Drag `Resources/countries.geojson` into the project.
Make sure **"Add to target: TraceToServer"** is checked.

## Entitlements & Info.plist

1. In **Signing & Capabilities**:
   - Uncheck **App Sandbox** (needed for lsof access to all processes)
   - Or keep Sandbox and accept that only your own user's connections will show

2. In the target's **Info** tab, add:
   - Key: `NSAppTransportSecurity` → Dictionary → `NSAllowsArbitraryLoads` = YES
   - (Required because ip-api.com free tier uses HTTP)

## Framework

In **Build Phases → Link Binary With Libraries**, ensure these are linked:
- MapKit.framework (should be auto-linked)
- CoreLocation.framework (should be auto-linked)

## Running

```bash
# For full system-wide connection monitoring:
sudo /path/to/TraceToServer.app/Contents/MacOS/TraceToServer

# Or just build & run from Xcode (shows your user's connections only)
```

## How It Works

| Component | Description |
|---|---|
| `NetworkMonitor` | Polls `lsof -i TCP -n -P -F pcn` every 2s |
| `GeoService` | Batch-queries `ip-api.com` (free, 45 req/min limit) |
| `CountryService` | Parses Natural Earth GeoJSON via `MKGeoJSONDecoder` |
| `WorldMapView` | `MKMapView` via `NSViewRepresentable`; polygon click detection |
| `HUDPanel` | Bottom bar with stats, process filter, country detail |

## Click Interaction

- Click any country → highlights it blue, shows connections in HUD
- Click background → deselects
- Yellow dot = your location
- Red dot = remote server
- Dashed blue arc = active connection
