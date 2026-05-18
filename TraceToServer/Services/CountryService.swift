import Foundation
import MapKit
import CoreLocation

@MainActor
class CountryService: ObservableObject {
    @Published var countries: [Country] = []
    @Published var isLoaded = false

    init() {
        Task { await load() }
    }

    private func load() async {
        guard let url = Bundle.main.url(forResource: "countries", withExtension: "geojson"),
              let data = try? Data(contentsOf: url) else {
            print("CountryService: countries.geojson not found in bundle")
            return
        }

        let parsed = await Task.detached(priority: .background) {
            Self.parseGeoJSON(data)
        }.value

        countries = parsed
        isLoaded = true
    }

    private static func parseGeoJSON(_ data: Data) -> [Country] {
        let decoder = MKGeoJSONDecoder()
        guard let objects = try? decoder.decode(data) else { return [] }

        var result: [Country] = []

        for object in objects {
            guard let feature = object as? MKGeoJSONFeature,
                  let propsData = feature.properties,
                  let props = try? JSONSerialization.jsonObject(with: propsData) as? [String: Any] else { continue }

            let name = props["NAME"] as? String ?? props["name"] as? String ?? "Unknown"
            let code = (props["ISO_A2"] as? String ?? props["iso_a2"] as? String ?? "-").uppercased()

            var polygons: [MKPolygon] = []
            for shape in feature.geometry {
                if let poly = shape as? MKPolygon {
                    poly.title = code
                    polygons.append(poly)
                } else if let multi = shape as? MKMultiPolygon {
                    for poly in multi.polygons {
                        poly.title = code
                        polygons.append(poly)
                    }
                }
            }

            guard !polygons.isEmpty else { continue }
            result.append(Country(id: code, name: name, polygons: polygons))
        }

        return result
    }

    func country(at coordinate: CLLocationCoordinate2D) -> Country? {
        countries.first { $0.contains(coordinate: coordinate) }
    }

    func country(forCode code: String) -> Country? {
        countries.first { $0.id == code.uppercased() }
    }
}
