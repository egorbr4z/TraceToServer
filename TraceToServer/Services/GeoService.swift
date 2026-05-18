import Foundation
import CoreLocation
import Observation

@MainActor
@Observable
class GeoService {
    var locations: [String: GeoLocation] = [:]
    var ownLocation: GeoLocation?

    private var pending: Set<String> = []
    private var cacheOrder: [String] = []
    private let maxCache = 512
    private var batchTask: Task<Void, Never>?

    init() {
        Task { await self.fetchOwnLocation() }
    }

    func lookup(ips: [String]) {
        let novel = ips.filter { locations[$0] == nil && !pending.contains($0) }
        guard !novel.isEmpty else { return }
        pending.formUnion(novel)
        scheduleBatch()
    }

    private func scheduleBatch() {
        batchTask?.cancel()
        batchTask = Task {
            try? await Task.sleep(nanoseconds: 500_000_000)
            guard !Task.isCancelled else { return }
            await self.flushBatch()
        }
    }

    private func flushBatch() async {
        let batch = Array(pending.prefix(100))
        pending.subtract(batch)
        guard !batch.isEmpty else { return }

        guard let url = URL(string: "http://ip-api.com/batch?fields=status,country,countryCode,city,lat,lon,query") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = try? JSONEncoder().encode(batch)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        guard let (data, _) = try? await URLSession.shared.data(for: request),
              let responses = try? JSONDecoder().decode([IPAPIResponse].self, from: data) else { return }

        for r in responses where r.status == "success" {
            let geo = GeoLocation(ip: r.query, latitude: r.lat, longitude: r.lon,
                                  city: r.city, country: r.country, countryCode: r.countryCode)
            locations[r.query] = geo
            cacheOrder.append(r.query)
        }
        while cacheOrder.count > maxCache {
            let old = cacheOrder.removeFirst()
            locations.removeValue(forKey: old)
        }

        if !pending.isEmpty { scheduleBatch() }
    }

    private func fetchOwnLocation() async {
        guard let url = URL(string: "http://ip-api.com/json?fields=status,country,countryCode,city,lat,lon,query"),
              let (data, _) = try? await URLSession.shared.data(from: url),
              let r = try? JSONDecoder().decode(IPAPIResponse.self, from: data),
              r.status == "success" else { return }

        ownLocation = GeoLocation(ip: r.query, latitude: r.lat, longitude: r.lon,
                                  city: r.city, country: r.country, countryCode: r.countryCode)
    }
}
