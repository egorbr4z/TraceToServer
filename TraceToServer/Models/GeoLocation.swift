import Foundation
import CoreLocation

struct GeoLocation {
    let ip: String
    let latitude: Double
    let longitude: Double
    let city: String
    let country: String
    let countryCode: String

    var coordinate: CLLocationCoordinate2D {
        CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }
}

struct IPAPIResponse: Decodable {
    let status: String
    let country: String
    let countryCode: String
    let city: String
    let lat: Double
    let lon: Double
    let query: String
}
