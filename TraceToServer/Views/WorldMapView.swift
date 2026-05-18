import SwiftUI
import MapKit

struct WorldMapView: NSViewRepresentable {
    @ObservedObject var countryService: CountryService
    @ObservedObject var geoService: GeoService
    let connections: [Connection]
    @Binding var selectedCountry: Country?

    func makeNSView(context: Context) -> MKMapView {
        let map = MKMapView()
        map.delegate = context.coordinator
        map.mapType = .mutedStandard
        map.showsCompass = false
        map.showsScale = false
        map.showsZoomControls = true
        map.isPitchEnabled = false

        // World overview centered on 20°N, 10°E
        let region = MKCoordinateRegion(
            center: CLLocationCoordinate2D(latitude: 20, longitude: 10),
            span: MKCoordinateSpan(latitudeDelta: 140, longitudeDelta: 240)
        )
        map.setRegion(region, animated: false)

        let click = NSClickGestureRecognizer(target: context.coordinator,
                                             action: #selector(Coordinator.handleClick(_:)))
        click.numberOfClicksRequired = 1
        map.addGestureRecognizer(click)

        return map
    }

    func updateNSView(_ map: MKMapView, context: Context) {
        context.coordinator.parent = self

        // Add country polygons once
        if context.coordinator.countriesAdded == false && !countryService.countries.isEmpty {
            context.coordinator.countriesAdded = true
            let polygons = countryService.countries.flatMap { $0.polygons }
            map.addOverlays(polygons, level: .aboveRoads)
        }

        // Update selected country highlight
        let newCode = selectedCountry?.id
        if context.coordinator.selectedCode != newCode {
            let old = context.coordinator.selectedCode
            context.coordinator.selectedCode = newCode

            if let code = old, let renderer = context.coordinator.renderers[code] {
                renderer.fillColor = Self.countryFill(selected: false)
                renderer.strokeColor = Self.countryStroke(selected: false)
                renderer.lineWidth = Self.countryLineWidth(selected: false)
                renderer.setNeedsDisplay()
            }
            if let code = newCode, let renderer = context.coordinator.renderers[code] {
                renderer.fillColor = Self.countryFill(selected: true)
                renderer.strokeColor = Self.countryStroke(selected: true)
                renderer.lineWidth = Self.countryLineWidth(selected: true)
                renderer.setNeedsDisplay()
            }
        }

        // Refresh connection arcs
        let arcOverlays = map.overlays.filter { $0 is MKGeodesicPolyline }
        map.removeOverlays(arcOverlays)

        if let own = geoService.ownLocation {
            for conn in connections {
                guard let geo = geoService.locations[conn.remoteIP] else { continue }
                let arc = MKGeodesicPolyline(
                    coordinates: [own.coordinate, geo.coordinate],
                    count: 2
                )
                arc.title = conn.remoteIP
                map.addOverlay(arc, level: .aboveLabels)
            }
        }

        // Own location annotation
        let ownPins = map.annotations.compactMap { $0 as? OwnAnnotation }
        map.removeAnnotations(ownPins)
        if let own = geoService.ownLocation {
            map.addAnnotation(OwnAnnotation(coordinate: own.coordinate))
        }

        // Remote annotations
        let remotePins = map.annotations.compactMap { $0 as? RemoteAnnotation }
        map.removeAnnotations(remotePins)
        for conn in connections {
            guard let geo = geoService.locations[conn.remoteIP] else { continue }
            map.addAnnotation(RemoteAnnotation(
                coordinate: geo.coordinate,
                connection: conn,
                city: geo.city,
                country: geo.country
            ))
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    // MARK: - Styling helpers

    static func countryFill(selected: Bool) -> NSColor {
        selected
            ? NSColor(red: 0.15, green: 0.55, blue: 1.0, alpha: 0.35)
            : NSColor(white: 1.0, alpha: 0.04)
    }

    static func countryStroke(selected: Bool) -> NSColor {
        selected
            ? NSColor(red: 0.4, green: 0.75, blue: 1.0, alpha: 0.9)
            : NSColor(white: 1.0, alpha: 0.18)
    }

    static func countryLineWidth(selected: Bool) -> CGFloat {
        selected ? 1.2 : 0.4
    }

    // MARK: - Coordinator

    class Coordinator: NSObject, MKMapViewDelegate {
        var parent: WorldMapView
        var countriesAdded = false
        var selectedCode: String?
        var renderers: [String: MKPolygonRenderer] = [:]   // countryCode -> renderer

        init(parent: WorldMapView) { self.parent = parent }

        @objc func handleClick(_ recognizer: NSClickGestureRecognizer) {
            guard let map = recognizer.view as? MKMapView else { return }
            let pt = recognizer.location(in: map)
            let coord = map.convert(pt, toCoordinateFrom: map)
            let tapped = parent.countryService.country(at: coord)
            DispatchQueue.main.async { self.parent.selectedCountry = tapped }
        }

        // MARK: MKMapViewDelegate

        func mapView(_ map: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
            if let polygon = overlay as? MKPolygon {
                let code = polygon.title ?? ""
                let isSelected = code == selectedCode
                let renderer = MKPolygonRenderer(polygon: polygon)
                renderer.fillColor = WorldMapView.countryFill(selected: isSelected)
                renderer.strokeColor = WorldMapView.countryStroke(selected: isSelected)
                renderer.lineWidth = WorldMapView.countryLineWidth(selected: isSelected)
                // Register one renderer per country (last polygon wins, fine for our use)
                if !code.isEmpty { renderers[code] = renderer }
                return renderer
            }

            if let polyline = overlay as? MKGeodesicPolyline {
                let r = MKPolylineRenderer(polyline: polyline)
                r.strokeColor = NSColor(red: 0.18, green: 0.85, blue: 1.0, alpha: 0.6)
                r.lineWidth = 1.4
                r.lineDashPattern = [6, 5]
                return r
            }

            return MKOverlayRenderer(overlay: overlay)
        }

        func mapView(_ map: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
            if annotation is MKUserLocation { return nil }

            if let own = annotation as? OwnAnnotation {
                let v = map.dequeueReusableAnnotationView(withIdentifier: "own")
                    ?? MKAnnotationView(annotation: own, reuseIdentifier: "own")
                v.image = Self.circleImage(color: .systemYellow, size: 14)
                v.zPriority = .max
                return v
            }

            if let remote = annotation as? RemoteAnnotation {
                let v = map.dequeueReusableAnnotationView(withIdentifier: "remote")
                    ?? MKAnnotationView(annotation: remote, reuseIdentifier: "remote")
                v.image = Self.circleImage(color: .systemRed, size: 8)
                v.canShowCallout = true
                v.detailCalloutAccessoryView = calloutLabel(for: remote)
                return v
            }

            return nil
        }

        private func calloutLabel(for remote: RemoteAnnotation) -> NSView {
            let label = NSTextField(labelWithString:
                "\(remote.connection.processName) → :\(remote.connection.remotePort)\n\(remote.city), \(remote.country)"
            )
            label.textColor = .secondaryLabelColor
            label.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
            return label
        }

        private static func circleImage(color: NSColor, size: CGFloat) -> NSImage {
            let img = NSImage(size: NSSize(width: size, height: size))
            img.lockFocus()
            color.setFill()
            NSColor.black.withAlphaComponent(0.4).setStroke()
            let rect = NSRect(x: 1, y: 1, width: size - 2, height: size - 2)
            let path = NSBezierPath(ovalIn: rect)
            path.fill()
            path.lineWidth = 1
            path.stroke()
            img.unlockFocus()
            return img
        }
    }
}

// MARK: - Annotation types

class OwnAnnotation: NSObject, MKAnnotation {
    var coordinate: CLLocationCoordinate2D
    var title: String? = "Your location"
    init(coordinate: CLLocationCoordinate2D) { self.coordinate = coordinate }
}

class RemoteAnnotation: NSObject, MKAnnotation {
    var coordinate: CLLocationCoordinate2D
    var title: String? { "\(city), \(country)" }
    var subtitle: String? { "\(connection.processName) :\(connection.remotePort)" }
    let connection: Connection
    let city: String
    let country: String
    init(coordinate: CLLocationCoordinate2D, connection: Connection, city: String, country: String) {
        self.coordinate = coordinate
        self.connection = connection
        self.city = city
        self.country = country
    }
}
