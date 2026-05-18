import Foundation
import MapKit

struct Country: Identifiable, Equatable {
    let id: String   // ISO A2 code
    let name: String
    let polygons: [MKPolygon]

    static func == (lhs: Country, rhs: Country) -> Bool {
        lhs.id == rhs.id
    }

    func contains(coordinate: CLLocationCoordinate2D) -> Bool {
        polygons.contains { $0.contains(coordinate: coordinate) }
    }
}

extension MKPolygon {
    func contains(coordinate: CLLocationCoordinate2D) -> Bool {
        let renderer = MKPolygonRenderer(polygon: self)
        let mapPoint = MKMapPoint(coordinate)
        let point = renderer.point(for: mapPoint)
        return renderer.path?.contains(point) ?? false
    }
}
